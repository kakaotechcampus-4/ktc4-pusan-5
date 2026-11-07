"""동종 그룹 방향 엇갈림 회귀. 2026-11-04 현대모비스.

비교 종목 현대차 +2.16%, 기아 −0.83% 의 중앙값 0.67% 와 현대모비스 +1.28% 의 차이는 0.61%p 로 기준(1.0%p) 안이라
follows 였다. 정형 보고서는 "대체로 0.67% 안팎 오른 같은 자동차 그룹의 현대차·기아와 비슷하게 움직여" 라고 써
기아도 오른 것처럼 읽혔다. 비교 종목 방향이 엇갈리면(비교 종목 둘) inconclusive 이고, 정형 문장은 그룹 등락률을 쓰지 않는다.

KRX 값은 tests/fixtures/market_data/krx_2026-11-04_auto.json(e2e 고정 응답에서 3종목만 고른 파싱 값)이다.
코스피 비교(market_compare.kospi)와 대형주 비교(market)는 3종목으로는 실제 값이 안 나와 그날 러너 입력 값을 쓴다.
"""

import json
import re
from datetime import date
from pathlib import Path

from app.services.market_data import IndexDaily, StockDaily
from app.services.market_data.context import build_market_context
from app.services.stock_analysis import generate as gen
from app.services.stock_analysis import market_compare as mc
from app.services.stock_analysis.verify import (
    COMPARE_META_PHRASE,
    COMPARE_OPPOSITE_WORDING,
    check_warnings,
    code_of,
    verify,
)

DAY = date(2026, 11, 4)
FIXTURE = Path(__file__).parent / "fixtures" / "market_data" / "krx_2026-11-04_auto.json"


def _krx() -> tuple[IndexDaily, list[StockDaily]]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return IndexDaily.model_validate(data["kospi"]), [StockDaily.model_validate(s) for s in data["stocks"]]


def _mobis_payload() -> dict:
    kospi, stocks = _krx()
    compare = mc.to_input(build_market_context("012330", DAY, kospi, stocks))
    # 2026-11-04 e2e 러너 입력(inputs_used)의 코스피 비교 값. 3종목 fixture 로는 비중이 실제와 달라 그날 값을 쓴다
    compare["kospi"] = {
        "stock_change_rate_pct": 1.28, "kospi_change_rate_pct": 0.62, "excess_vs_kospi_pp": 0.66,
        "kospi_weight_pct": 0.7, "kospi_contribution_pp": 0.009, "kospi_ex_self_change_rate_pct": 0.62,
        "excess_vs_kospi_ex_self_pp": 0.66, "kospi_basis": "kospi", "kospi_relation": "follows"}
    return {
        "stock": "현대모비스", "code": "012330", "target_date": "2026-11-04",
        "cutoff": "2026-11-04T15:30:00+09:00", "change_pct": 1.28,
        "market": {"index": "코스피", "change_pct": 0.62, "as_of": "15:30", "url": "", "peer_median_pct": 0.84,
                   "peer_up": 12, "peer_down": 7, "peer_total": 20, "excess_pct": 0.44},
        "messages": [{"channel": "c", "url": "https://t.me/c/1", "datetime_kst": "2026-11-04T15:00:00+09:00",
                      "text": "코스피 마감 시황", "mention": "not_mentioned", "kind": "market_recap"}],
        "market_compare": compare,
    }


def test_mobis_auto_group_is_inconclusive_when_peers_split() -> None:
    kospi, stocks = _krx()
    ctx = build_market_context("012330", DAY, kospi, stocks)

    [peer] = ctx.peers
    assert peer.group == "자동차"
    assert peer.members_used == ["005380", "000270"]  # 현대차 +2.16, 기아 −0.83
    assert peer.median_change_rate_pct == 0.67
    assert peer.excess_vs_group_pp == 0.61  # 기준(1.0%p) 안 — 이전에는 follows 였다
    assert peer.relation == "inconclusive"


def test_mobis_canned_relative_does_not_say_group_moved_together() -> None:
    payload = _mobis_payload()
    assert payload["market_compare"]["peers"][0]["relation"] == "inconclusive"

    report = gen.canned_report(payload)
    relative = report["summary"]["relative"]
    kospi_sentence = "현대모비스는 코스피와 비슷하게 움직여 시장 전체 흐름을 따라갔습니다."
    assert relative == f"{kospi_sentence} 같은 자동차 그룹의 현대차·기아는 방향이 엇갈려 그룹 흐름과 비교하기 어렵습니다."
    # 코스피 판정이 follows 라 종목 자신의 결론(코스피를 따라 시장 흐름을 따라갔다)은 남는다
    assert relative.startswith(kospi_sentence)
    # "비슷하게 움직여" 는 코스피에 붙은 한 번뿐이다. 그룹(현대차·기아)과 비슷하게 움직였다고 쓰지 않는다
    assert relative.count("비슷하게 움직여") == 1 and "코스피와 비슷하게 움직여" in relative
    assert not re.search(r"현대차·기아(와|과)\s*(비슷하게|함께)", relative)
    assert not re.search(r"대체로 [\d.]+% 안팎", relative)
    assert "안팎" not in relative and "0.67" not in relative

    # 검증 통과, 비교 판정 금지 표현·opposite 표현 경고 없음
    assert verify(report, payload) == ("passed", [])
    warned = {code_of(w) for w in check_warnings(report, payload)}
    assert not warned & {COMPARE_META_PHRASE, COMPARE_OPPOSITE_WORDING}
