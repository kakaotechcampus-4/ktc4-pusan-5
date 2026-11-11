"""Real PostgreSQL checks for stock_move_analyses file-level idempotency.

같은 산출물 파일을 두 번 적재해도 행이 하나여야 하고, 재생성본(바이트가 다른 파일)은
지금처럼 새 행이어야 한다. MIGRATION_TEST_ADMIN_URL 이 없으면 skip 된다.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.repositories.stock_move_analysis import insert_analysis_files
from tests.test_migrations import alembic, columns, query

FIXTURES = Path(__file__).parent / "fixtures" / "reports"
SAMSUNG = FIXTURES / "삼성전자-2026-09-18-with-indirect__B__r1.json"
CURRENT = FIXTURES / "SK하이닉스-2026-11-03-1845__r1.json"


def load(url, paths):
    """한 번의 배치. 새로 들어간 행 수를 돌려준다."""

    async def work():
        engine = create_async_engine(url)
        try:
            async with async_sessionmaker(engine)() as session:
                inserted = await insert_analysis_files(session, paths)
                await session.commit()
                return len(inserted)
        finally:
            await engine.dispose()

    return asyncio.run(work())


def counts(url):
    analyses = query(url, "SELECT count(*) AS n FROM stock_move_analyses")[0]["n"]
    factors = query(url, "SELECT count(*) AS n FROM stock_move_analysis_factors")[0]["n"]
    sources = query(url, "SELECT count(*) AS n FROM stock_move_analysis_factor_sources")[0]["n"]
    return analyses, factors, sources


def test_same_file_loaded_twice_leaves_one_row(database):
    alembic(database, "upgrade", "head")

    assert load(database, [SAMSUNG]) == 1
    first = counts(database)
    assert first[0] == 1 and first[1] > 0 and first[2] > 0

    # 다른 배치에서 다시, 그리고 같은 배치 안에 두 번 — 둘 다 아무것도 넣지 않는다.
    assert load(database, [SAMSUNG]) == 0
    assert load(database, [SAMSUNG, SAMSUNG]) == 0
    assert counts(database) == first


def test_regenerated_file_is_still_a_new_row(database, tmp_path):
    """재생성본은 바이트가 달라 키가 다르다. 보고서 재생성은 막지 않는다."""
    alembic(database, "upgrade", "head")
    regenerated = tmp_path / SAMSUNG.name
    regenerated.write_bytes(SAMSUNG.read_bytes() + b"\n")

    assert load(database, [SAMSUNG]) == 1
    assert load(database, [regenerated]) == 1
    assert counts(database)[0] == 2


def test_report_sources_are_linked_to_source_cards_now_or_later(database, tmp_path):
    """출처 주소로 저장된 원문을 찾아 공통 자료 ID 를 잇는다. 못 찾은 출처는 나중에 다시 찾는다."""
    from app.repositories.source_card import register_missing_sources
    from app.repositories.stock_move_analysis import link_analysis_sources
    from tests.db import in_session

    alembic(database, "upgrade", "head")
    assert load(database, [SAMSUNG]) == 1
    linked = "SELECT count(*) FROM stock_move_analysis_factor_sources WHERE source_card_id IS NOT NULL"
    assert query(database, linked)[0][0] == 0, "원문이 아직 없다"

    # 보고서를 적재한 뒤에 그 메시지를 수집했다
    query(database, """
        INSERT INTO channel (telegram_handle, name, is_public, created_at)
        VALUES ('KISGregKim', 'KISGregKim', true, now())
    """)
    query(database, """
        INSERT INTO telegram_messages (channel_id, msg_id, url, posted_at, text, collected_via)
        SELECT id, 18692, 'https://t.me/KISGregKim/18692', '2026-09-18 09:00+09', '메시지', 'web'
        FROM channel
    """)
    in_session(database, register_missing_sources)
    wanted = query(database, "SELECT count(*) FROM stock_move_analysis_factor_sources "
                             "WHERE url = 'https://t.me/KISGregKim/18692'")[0][0]
    assert wanted > 0
    assert in_session(database, link_analysis_sources) == wanted
    assert query(database, linked)[0][0] == wanted
    assert in_session(database, link_analysis_sources) == 0, "이미 이은 출처는 다시 보지 않는다"

    # 원문이 이미 있으면 적재할 때 바로 잇는다 (재생성본은 새 행이다)
    regenerated = tmp_path / SAMSUNG.name
    regenerated.write_bytes(SAMSUNG.read_bytes() + b"\n")
    assert load(database, [regenerated]) == 1
    assert query(database, linked)[0][0] == wanted * 2


def test_iso_as_of_is_stored_at_the_same_instant_as_hhmm(database, tmp_path):
    """as_of 칼럼은 timestamptz 다. 새 보고서의 ISO(+09:00) 와 옛 보고서의 "HH:MM"(target_date 와 합쳐 KST)이 같은
    시각으로 저장되고, 서버 시간대가 UTC 여도 9시간 밀리지 않는다. 다음 날 아침 cutoff 는 그 날짜 그대로 들어간다."""
    from datetime import datetime

    from app.repositories.stock_move_analysis import KST

    alembic(database, "upgrade", "head")
    files = []
    for i, as_of in enumerate(["15:30", "2026-11-02T15:30:00+09:00", "2026-11-03T08:30:00+09:00"]):
        report = {"ticker": "105560", "name": "KB금융", "date": "2026-11-02", "as_of": as_of, "summary": {}}
        path = tmp_path / f"r{i}.json"
        path.write_text(json.dumps({"run_id": f"r{i}", "final_text": json.dumps(report)}), encoding="utf-8")
        files.append(path)
    assert load(database, files) == 3

    rows = query(database, "SELECT run_id, as_of, to_char(as_of AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD HH24:MI') AS kst "
                           "FROM stock_move_analyses ORDER BY run_id")
    assert [(r["run_id"], r["kst"]) for r in rows] == [
        ("r0", "2026-11-02 15:30"), ("r1", "2026-11-02 15:30"), ("r2", "2026-11-03 08:30")]
    assert rows[0]["as_of"] == rows[1]["as_of"] == datetime(2026, 11, 2, 15, 30, tzinfo=KST)
    assert rows[2]["as_of"] == datetime(2026, 11, 3, 8, 30, tzinfo=KST)


def test_current_report_keeps_event_and_background_sources(database):
    """지금 형식 보고서. 원인 한 문장(event)이 claim 칼럼에, 참고 항목 출처가 background 칼럼에 들어간다."""
    alembic(database, "upgrade", "head")
    assert load(database, [CURRENT]) == 1

    claims = query(database, "SELECT f.claim, a.raw_json -> 'factors' -> f.order_index ->> 'event' AS event "
                             "FROM stock_move_analysis_factors f JOIN stock_move_analyses a ON a.id = f.analysis_id")
    assert claims and all(r["claim"] and r["claim"] == r["event"] for r in claims)

    # 칼럼의 출처가 원본(raw_json)의 출처와 같다
    same = query(database, """
        SELECT bool_and(c.item -> 'sources' = r.item -> 'sources') AS same, count(*) AS n
        FROM stock_move_analyses a,
             LATERAL jsonb_array_elements(a.background -> 'bullish') WITH ORDINALITY c(item, i)
             JOIN LATERAL jsonb_array_elements(a.raw_json -> 'background' -> 'bullish') WITH ORDINALITY r(item, i)
               ON r.i = c.i
    """)[0]
    assert same["n"] > 0 and same["same"]


DISPLAY_COLUMNS = ("display_as_of", "display_is_close", "relative_verdict", "summary_relative")


def report_wrappers(reports):
    return [{"run_id": f"r{i}", "final_text": json.dumps(r, ensure_ascii=False)} for i, r in enumerate(reports)]


def insert_before_0028(url, wrappers):
    """0027 표에 보고서를 넣는다(0028 칼럼이 없어 적재 코드를 못 쓴다). 적재가 같은 래퍼로 채울 값을 돌려준다."""
    from app.repositories.stock_move_analysis import build_analysis, parse_wrapper

    expected = {}
    for w in wrappers:
        a = build_analysis(parse_wrapper(w))
        expected[a.run_id] = ({c: getattr(a, c) for c in DISPLAY_COLUMNS}, {f.order_index: f.links for f in a.factors})
        analysis_id = query(url, "INSERT INTO stock_move_analyses (run_id, raw_json, parse_status, verify_status) "
                                 "VALUES ($1, $2::jsonb, $3, 'not_verified') RETURNING id",
                            a.run_id, json.dumps(a.raw_json, ensure_ascii=False), a.parse_status)[0]["id"]
        for f in a.factors:
            query(url, "INSERT INTO stock_move_analysis_factors (analysis_id, order_index) VALUES ($1, $2)",
                  analysis_id, f.order_index)
    return expected


def stored_display(url):
    rows = query(url, f"SELECT id, run_id, {', '.join(DISPLAY_COLUMNS)}, skipped_llm FROM stock_move_analyses")
    links = query(url, "SELECT analysis_id, order_index, links FROM stock_move_analysis_factors")
    got = {}
    for r in rows:
        factor_links = {f["order_index"]: json.loads(f["links"]) if f["links"] else None
                        for f in links if f["analysis_id"] == r["id"]}
        assert r["skipped_llm"] is None  # raw_json 에 없는 칸이라 채우지 않는다
        got[r["run_id"]] = ({c: r[c] for c in DISPLAY_COLUMNS}, factor_links)
    return got


def test_display_columns_are_backfilled_like_the_loader(database):
    """0028 은 기존 행의 화면 칼럼을 raw_json 으로 채운다. 채운 값이 적재(build_analysis)가 같은 보고서로
    채우는 값과 같아야 한다 — 다르면 리비전 전후에 적재된 행이 화면에서 다르게 보인다.
    downgrade 하면 칼럼이 지워지고, 다시 upgrade 하면 같은 값으로 채워진다."""
    alembic(database, "upgrade", "0027_classification")

    odd = {  # 타입이 어긋난 칸, 시간대 없는 시각, 객체가 아닌 factor·link(중첩 배열 포함)
        "ticker": "105560", "date": "2026-11-02", "summary": ["배열"],
        "display_as_of": "2026-11-02T15:30:00", "display_is_close": "true", "relative_verdict": 1,
        "factors": ["문자열 factor",
                    {"event": "e", "links": [{"layer": "move", "strength": "partial"}, "x", [{"layer": "relative"}]]},
                    {"event": "links 가 객체", "links": {"layer": "move"}}],
    }
    wrappers = [json.loads(CURRENT.read_text(encoding="utf-8")), json.loads(SAMSUNG.read_text(encoding="utf-8"))]
    wrappers += report_wrappers([
        odd,
        {"summary": {"relative": "상대 문장"}, "display_as_of": "오후", "display_is_close": False},
        {"summary": {}, "display_as_of": "2026-13-45T25:00:00+09:00", "relative_verdict": "explained"},
    ])
    # 파싱이 깨진 행은 raw_json 이 래퍼다. 래퍼에 보고서 칸 이름이 있어도 채우지 않는다.
    wrappers.append({"run_id": "broken", "final_text": "{깨짐", "relative_verdict": "explained",
                     "summary": {"relative": "래퍼"}})
    expected = insert_before_0028(database, wrappers)
    assert expected["r0"][0]["display_as_of"] is not None and expected["r0"][1] == {
        1: [{"layer": "move", "strength": "partial"}], 2: None}, "odd 보고서가 의도한 경우를 덮지 못한다"

    alembic(database, "upgrade", "head")
    assert stored_display(database) == expected
    assert expected["SK하이닉스-2026-11-03-1845__r1"][0]["display_is_close"] is True

    alembic(database, "downgrade", "0027_classification")
    assert not set(DISPLAY_COLUMNS) & set(columns(database, "stock_move_analyses"))
    assert "links" not in columns(database, "stock_move_analysis_factors")
    alembic(database, "upgrade", "head")
    assert stored_display(database) == expected
    alembic(database, "check")


# 러너가 쓰는 꼴과 그 주변. 리비전과 적재가 같은 값을 낸다(범위 밖이면 둘 다 NULL).
SAME_AS_LOADER = [
    "2026-11-03T15:30:00+09:00", "2026-11-03T15:30:00", "2026-11-03 15:30", "2026-11-03T15:30Z",
    "2026-11-03T15:30:00.123456+09:00", "2026-11-03T15:30:00.1+0900", "2026-11-03T15:30:00+09",
    "\t2026-11-03T15:30:00+09:00\n",
    "2026-11-03T24:00:00+09:00",  # Postgres 는 다음 날 00:00 으로 받지만 적재(3.12)는 NULL. 리비전도 NULL
    "2026-11-03 15:30:00 UTC",  # 시간대 이름은 둘 다 NULL. 이름을 버리고 KST 로 읽으면 9시간 틀린다
    "2026-11-03T15:30:60",  # Postgres 는 다음 분으로 받지만 적재는 NULL
    "2026-02-30T10:00",
]
# 적재(fromisoformat)는 받지만 러너가 쓰지 않는 꼴. 리비전은 NULL 로 둔다(0028 docstring).
# 소수 7자리는 Postgres 가 반올림하고 적재가 버려 값이 달라지므로 받지 않는다.
LOADER_ONLY = ["2026-11-03", "2026-11-03T15", "20261103T1530", "2026-11-03T15:30:00,5+09:00",
               "2026-11-03T15:30:00+09:00:00", "2026-11-03T15:30:00.1234567+09:00"]


def test_display_as_of_backfill_accepts_only_runner_forms(database):
    alembic(database, "upgrade", "0027_classification")
    expected = insert_before_0028(database, report_wrappers(
        [{"summary": {}, "display_as_of": s} for s in SAME_AS_LOADER + LOADER_ONLY]))
    alembic(database, "upgrade", "head")
    got = stored_display(database)

    for i, s in enumerate(SAME_AS_LOADER):
        assert got[f"r{i}"] == expected[f"r{i}"], s
    for i, s in enumerate(LOADER_ONLY, start=len(SAME_AS_LOADER)):
        assert expected[f"r{i}"][0]["display_as_of"] is not None, f"적재가 더는 받지 않는다: {s}"
        assert got[f"r{i}"][0]["display_as_of"] is None, s


def test_rows_without_new_fields_are_not_rewritten(database):
    """새 칸이 하나도 없는 옛 형식 행은 고치지 않는다. 다시 쓰면 행 수만큼 표가 불어난다."""
    alembic(database, "upgrade", "0027_classification")
    insert_before_0028(database, [json.loads(SAMSUNG.read_text(encoding="utf-8")),
                                  json.loads(CURRENT.read_text(encoding="utf-8"))])
    xmin = "SELECT run_id, xmin::text AS x FROM stock_move_analyses ORDER BY run_id"
    before = {r["run_id"]: r["x"] for r in query(database, xmin)}
    alembic(database, "upgrade", "head")
    after = {r["run_id"]: r["x"] for r in query(database, xmin)}
    legacy = json.loads(SAMSUNG.read_text(encoding="utf-8"))["run_id"]
    assert after[legacy] == before[legacy]
    assert after["SK하이닉스-2026-11-03-1845__r1"] != before["SK하이닉스-2026-11-03-1845__r1"]


def test_too_long_relative_verdict_stops_with_sample_ids(database):
    """relative_verdict 칼럼(24자)에 안 들어가는 값이 있으면 채우기 전에 표본 id 와 함께 멈춘다. 아무것도 바뀌지 않는다."""
    alembic(database, "upgrade", "0027_classification")
    insert_before_0028(database, report_wrappers([
        {"summary": {}, "relative_verdict": "partially_explained"},
        {"summary": {}, "relative_verdict": "partially_explained_by_market"},
    ]))
    long_id = query(database, "SELECT id FROM stock_move_analyses WHERE run_id = 'r1'")[0]["id"]

    result = alembic(database, "upgrade", "head", success=False)
    assert f"Cannot fill relative_verdict: 1 row(s) longer than 24 characters. Sample analysis IDs: {{{long_id}}}" \
        in result
    assert query(database, "SELECT version_num FROM alembic_version_ai")[0][0] == "0027_classification"
    assert "relative_verdict" not in columns(database, "stock_move_analyses")


def test_upgrade_gives_up_waiting_for_a_held_table_lock(database):
    """다른 트랜잭션이 표를 쥐고 있으면 칼럼 추가가 줄을 서는 대신 lock_timeout 으로 실패한다(뒤의 조회를 막지 않는다)."""
    import asyncpg

    alembic(database, "upgrade", "0027_classification")

    async def hold_and_upgrade():
        conn = await asyncpg.connect(database.replace("postgresql+asyncpg://", "postgresql://", 1))
        try:
            await conn.execute("BEGIN; SELECT count(*) FROM stock_move_analyses")
            return await asyncio.to_thread(alembic, database, "upgrade", "head", success=False)
        finally:
            await conn.close()

    assert "lock timeout" in asyncio.run(hold_and_upgrade())
    assert query(database, "SELECT version_num FROM alembic_version_ai")[0][0] == "0027_classification"
    alembic(database, "upgrade", "head")  # 잠금이 풀리면 다시 돌리면 된다


def test_loader_fills_display_columns_and_skipped_llm(database, tmp_path):
    """적재가 새 칼럼을 채운다. skipped_llm 은 보고서가 아니라 래퍼에서 읽는다."""
    alembic(database, "upgrade", "head")
    canned = tmp_path / "canned.json"
    report = {"ticker": "005930", "date": "2026-10-30", "verdict": "no_clear_cause",
              "relative_verdict": "no_clear_cause", "summary": {"relative": None}, "factors": []}
    canned.write_text(json.dumps({"run_id": "canned", "final_text": json.dumps(report),
                                  "skipped_llm": "NO_DIRECT_MESSAGES"}), encoding="utf-8")
    assert load(database, [CURRENT, canned]) == 2

    rows = {r["run_id"]: r for r in query(database, "SELECT * FROM stock_move_analyses")}
    current = rows["SK하이닉스-2026-11-03-1845__r1"]
    raw = json.loads(current["raw_json"])
    assert current["skipped_llm"] is None
    assert current["relative_verdict"] == raw["relative_verdict"]
    assert current["summary_relative"] == raw["summary"]["relative"]
    assert current["display_as_of"] == datetime.fromisoformat(raw["display_as_of"])  # 같은 시각(asyncpg 는 UTC 로 준다)
    assert current["display_is_close"] is raw["display_is_close"]
    assert rows["canned"]["skipped_llm"] == "NO_DIRECT_MESSAGES"

    links = query(database, "SELECT f.links FROM stock_move_analysis_factors f WHERE f.analysis_id = $1 "
                            "ORDER BY f.order_index", current["id"])
    assert [json.loads(r["links"]) for r in links] == [f["links"] for f in raw["factors"]]
