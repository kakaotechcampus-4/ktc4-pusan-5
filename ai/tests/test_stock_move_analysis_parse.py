"""파싱·정규화 계약. DB 없이 돈다.

metadata 검사만으로는 잡히지 않는 것들이다 — background 의 문자열/객체 혼용,
counter 의 null, 상한 초과를 자르지 않는다는 약속, 래퍼가 2단이라는 사실.
픽스처는 실제 실행 산출물(`tests/fixtures/reports/`)을 그대로 쓴다.
"""

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app.repositories.stock_move_analysis import (
    KST,
    build_analysis,
    normalize_background,
    parse_analysis_file,
    parse_wrapper,
)

FIXTURES = Path(__file__).parent / "fixtures" / "reports"

SAMSUNG = FIXTURES / "삼성전자-2026-09-18-with-indirect__B__r1.json"
HYNIX = FIXTURES / "SK하이닉스-2026-09-18-with-indirect__B__r1.json"
NO_CAUSE = FIXTURES / "SK이노베이션-2026-09-18-with-indirect__B__r2.json"


def test_wrapper_is_opened_then_final_text_reparsed() -> None:
    """입력 파일은 2단이다. 바깥은 실험 파이프라인의 실행 기록이고 보고서 JSON 은
    final_text 안에 **문자열로** 들어 있다. 한 번만 파싱하면 보고서가 안 나온다."""
    parsed = parse_analysis_file(SAMSUNG)
    assert parsed.parse_status == "ok"
    assert parsed.analysis["ticker"] == "005930"
    assert parsed.run_id


def test_unknown_wrapper_fields_are_ignored() -> None:
    """래퍼는 실험 환경 산출물이라 필드가 늘거나 준다. 우리가 보는 다섯 개
    (final_text, json_status, schema_problems, is_error, asked_question) 밖은
    흘려보낸다. 여기서 죽으면 적재가 통째로 멈춘다."""
    parsed = parse_wrapper(
        {
            "final_text": '{"ticker": "005930"}',
            "json_status": "clean",
            "무엇인지_모를_새_필드": {"깊게": ["중첩", 1, None]},
            "n_tool_calls": 7,
        }
    )
    assert parsed.parse_status == "ok"
    assert parsed.analysis["ticker"] == "005930"


def test_tool_metrics_and_pubdate_do_not_mark_failure() -> None:
    """툴을 막아둬서 툴 지표는 언제나 0 이고, pubdate_* 는 당일 생성으로 바뀌면서
    의미가 없어졌다. pubdate_missing 이 0 이 아니어도 문제가 아니다."""
    parsed = parse_wrapper(
        {"final_text": "{}", "json_status": "clean", "pubdate_missing": 5, "n_tool_calls": 0}
    )
    assert parsed.parse_status == "ok"
    assert parsed.parse_error is None


def test_parse_failure_is_still_loaded_with_raw_json() -> None:
    """원인 분석 자료가 사라지면 왜 깨졌는지 영영 알 수 없다. 상태만 달아 적재한다."""
    parsed = parse_wrapper({"run_id": "r1", "final_text": "{이건 JSON 이 아니다"})
    assert parsed.parse_status == "parse_failed"
    assert parsed.parse_error
    assert parsed.raw_json["final_text"]  # 래퍼가 통째로 남는다

    analysis = build_analysis(parsed)
    assert analysis.ticker is None
    assert analysis.raw_json is parsed.raw_json


def test_run_error_and_asked_question_become_schema_violation() -> None:
    """파싱은 됐지만 그대로 믿으면 안 되는 회차다. 셋은 원인이 다르지만 '서비스에
    내보내면 안 된다'는 뜻은 같아 한 상태로 묶고, 무엇이 걸렸는지는 사유에 남긴다."""
    parsed = parse_wrapper(
        {
            "final_text": '{"ticker": "005930"}',
            "json_status": "clean",
            "is_error": True,
            "asked_question": True,
            "schema_problems": ["size_fit 누락"],
        }
    )
    assert parsed.parse_status == "schema_violation"
    assert "is_error" in parsed.parse_error
    assert "asked_question" in parsed.parse_error
    assert "size_fit 누락" in parsed.parse_error
    # 그래도 보고서 본문은 정상적으로 펴진다 — 원인 분석이 목적이다.
    assert build_analysis(parsed).ticker == "005930"


def test_background_accepts_both_string_and_object_items() -> None:
    """프롬프트가 같은 칸에 두 형태를 섞어 낸다. **둘 다 정상값이다.**
    모델에게 일관성을 요구할 수 없으니(프롬프트는 검증 스크립트와 짝이라 못 고친다)
    적재가 {text, watch} 로 펴서 화면이 매번 타입을 확인하지 않게 한다."""
    normalized = normalize_background(
        {
            "bullish": ["문자열 항목입니다."],
            "bearish": [],
            "neutral": [{"text": "다음에 확인할 사건", "watch": True}, "또 문자열"],
        }
    )
    assert normalized["bullish"] == [{"text": "문자열 항목입니다.", "watch": False}]
    assert normalized["bearish"] == []
    assert normalized["neutral"] == [
        {"text": "다음에 확인할 사건", "watch": True},
        {"text": "또 문자열", "watch": False},
    ]


def test_background_watch_string_false_is_not_true() -> None:
    """bool("false") 는 True 다. 모델이 watch 를 문자열로 내면 "false" 항목에 박스가
    떠 버린다. 진짜 true 만 참이고, 문자열·숫자·누락은 전부 false 로 편다 —
    화면이 null 을 따지지 않도록 bool 로 고정한다."""
    normalized = normalize_background(
        {
            "neutral": [
                {"text": "문자열 false", "watch": "false"},
                {"text": "문자열 true", "watch": "true"},
                {"text": "숫자", "watch": 1},
                {"text": "누락"},
                {"text": "진짜 true", "watch": True},
            ]
        }
    )
    assert [item["watch"] for item in normalized["neutral"]] == [False, False, False, False, True]


def test_real_report_background_is_normalized() -> None:
    """합성 입력만으로는 부족하다. 실제 산출물에 watch 객체와 문자열이 같은 칸에 있다."""
    analysis = build_analysis(parse_analysis_file(SAMSUNG))
    neutral = analysis.background["neutral"]
    assert all(set(item) == {"text", "watch"} for item in neutral)
    assert any(item["watch"] for item in neutral)


def test_null_counter_is_a_valid_value() -> None:
    """방향이 어긋나는 재료가 없는 날과 no_clear_cause 인 날은 counter 가 null 이다.
    빈 문자열로 바꾸면 화면이 '없음'과 '못 채움'을 구분하지 못한다."""
    analysis = build_analysis(parse_analysis_file(NO_CAUSE))
    assert analysis.verdict == "no_clear_cause"
    assert analysis.summary_counter is None
    assert analysis.summary_move  # 나머지 칸은 채워져 있다
    assert analysis.factors == []  # no_clear_cause 면 factors 는 빈 배열이다


def test_as_of_is_combined_with_date_into_kst_aware() -> None:
    """프롬프트 출력은 'HH:MM' 문자열뿐이다. 루트 CLAUDE.md 가 naive datetime 을
    금지하므로 date 와 합쳐 타임존을 붙인다. 원본 문자열은 raw_json 에 남는다."""
    analysis = build_analysis(parse_analysis_file(SAMSUNG))
    assert analysis.target_date == date(2026, 9, 18)
    assert analysis.as_of == datetime(2026, 9, 18, 15, 30, tzinfo=KST)
    assert analysis.raw_json["as_of"] == "15:30"


def test_change_pct_keeps_its_exact_value() -> None:
    """Decimal(3.37) 은 3.370000000000000106... 이 된다. 루트 CLAUDE.md 가
    가공하지 않은 값을 요구하므로 적재가 값을 바꾸면 안 된다."""
    analysis = build_analysis(parse_analysis_file(SAMSUNG))
    assert analysis.change_pct == Decimal("3.37")
    assert str(analysis.change_pct) == "3.37"


def test_factors_and_sources_keep_their_order() -> None:
    """factors 는 중요도 순이라 배열 순서 자체가 정보다. 순서가 섞이면 화면의
    '이유' 절이 덜 중요한 것부터 나온다."""
    analysis = build_analysis(parse_analysis_file(HYNIX))
    assert [f.order_index for f in analysis.factors] == [0, 1, 2, 3]
    first = analysis.factors[0]
    assert first.claim and first.stance in {"bullish", "bearish", "neutral"}
    assert first.direction_match is True
    assert [s.order_index for s in first.sources] == list(range(len(first.sources)))
    assert first.sources[0].source == "telegram"
    assert first.sources[0].datetime_kst is None or first.sources[0].datetime_kst.tzinfo


def test_limit_overflow_is_not_truncated(caplog) -> None:
    """factors 4 / terms 8 / background 전체 6·칸당 3 이 프롬프트의 상한이다.
    적재가 말없이 자르면 실행 점검 스크립트의 상한 위반 검사가 영원히 통과한다.
    그대로 넣고 로그로만 알린다."""
    raw = json.loads(HYNIX.read_text(encoding="utf-8"))
    analysis_json = json.loads(raw["final_text"])
    total = sum(len(analysis_json["background"][k]) for k in ("bullish", "bearish", "neutral"))
    assert total > 6, "픽스처가 상한을 안 넘어 이 테스트가 의미를 잃었다"

    with caplog.at_level("WARNING"):
        analysis = build_analysis(parse_wrapper(raw))

    assert sum(len(v) for v in analysis.background.values()) == total
    assert "background" in caplog.text


def test_verify_status_is_passed_in_as_an_argument() -> None:
    """적재 모듈이 근거 검증을 수행하지 않는다. 판정과 적재를 분리해야 한쪽을
    고쳐도 다른 쪽이 안 흔들린다. 검증기 연결은 후속 PR 이다."""
    parsed = parse_analysis_file(SAMSUNG)
    assert build_analysis(parsed).verify_status == "not_verified"

    failed = build_analysis(parsed, verify_status="failed", verify_error="quote 불일치 1건")
    assert failed.verify_status == "failed"
    assert failed.verify_error == "quote 불일치 1건"


def test_file_hash_is_taken_from_file_bytes(tmp_path: Path) -> None:
    """재적재 방지 키는 파일 바이트의 sha256 이다. final_text 가 같아도 파일이 1바이트
    다르면 다른 키여야 한다 — 재생성본은 새 행으로 남겨야 해서다."""
    data = SAMSUNG.read_bytes()
    copy = tmp_path / SAMSUNG.name
    copy.write_bytes(data)
    changed = tmp_path / "changed.json"
    changed.write_bytes(data + b"\n")

    key = parse_analysis_file(SAMSUNG).source_file_sha256
    assert key == hashlib.sha256(data).hexdigest()
    assert parse_analysis_file(copy).source_file_sha256 == key
    assert parse_analysis_file(changed).source_file_sha256 != key
    assert build_analysis(parse_analysis_file(SAMSUNG)).source_file_sha256 == key


def test_broken_file_still_gets_a_hash(tmp_path: Path) -> None:
    """JSON 이 아닌 파일도 적재된다. 그러니 재적재도 막혀야 한다."""
    broken = tmp_path / "broken.json"
    broken.write_bytes(b"not json")
    parsed = parse_analysis_file(broken)
    assert parsed.parse_status == "parse_failed"
    assert parsed.source_file_sha256 == hashlib.sha256(b"not json").hexdigest()


def test_wrapper_without_file_has_no_hash() -> None:
    """파일 없이 래퍼 dict 로 넣는 경로는 키가 없다. NULL 은 UNIQUE 에서 충돌하지 않는다."""
    assert parse_wrapper(json.loads(SAMSUNG.read_text(encoding="utf-8"))).source_file_sha256 is None
