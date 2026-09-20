"""파싱·정규화 계약. DB 없이 돈다.

metadata 검사만으로는 잡히지 않는 것들이다 — background 의 문자열/객체 혼용,
counter 의 null, 상한 초과를 자르지 않는다는 약속, 래퍼가 2단이라는 사실.
픽스처는 실제 실행 산출물(`tests/fixtures/reports/`)을 그대로 쓴다.
"""

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app.repositories.stock_move_report import (
    KST,
    build_report,
    normalize_background,
    parse_report_file,
    parse_wrapper,
)

FIXTURES = Path(__file__).parent / "fixtures" / "reports"

SAMSUNG = FIXTURES / "삼성전자-2026-09-18-with-indirect__B__r1.json"
HYNIX = FIXTURES / "SK하이닉스-2026-09-18-with-indirect__B__r1.json"
NO_CAUSE = FIXTURES / "SK이노베이션-2026-09-18-with-indirect__B__r2.json"


def test_래퍼를_열고_final_text_를_다시_파싱한다() -> None:
    """입력 파일은 2단이다. 바깥은 실험 파이프라인의 실행 기록이고 보고서 JSON 은
    final_text 안에 **문자열로** 들어 있다. 한 번만 파싱하면 보고서가 안 나온다."""
    parsed = parse_report_file(SAMSUNG)
    assert parsed.parse_status == "ok"
    assert parsed.report["ticker"] == "005930"
    assert parsed.run_id


def test_모르는_래퍼_필드에_걸려_죽지_않는다() -> None:
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
    assert parsed.report["ticker"] == "005930"


def test_툴_지표와_pubdate_는_실패_판정에_쓰지_않는다() -> None:
    """툴을 막아둬서 툴 지표는 언제나 0 이고, pubdate_* 는 당일 생성으로 바뀌면서
    의미가 없어졌다. pubdate_missing 이 0 이 아니어도 문제가 아니다."""
    parsed = parse_wrapper(
        {"final_text": "{}", "json_status": "clean", "pubdate_missing": 5, "n_tool_calls": 0}
    )
    assert parsed.parse_status == "ok"
    assert parsed.parse_error is None


def test_파싱_실패도_버리지_않고_원본을_남긴다() -> None:
    """원인 분석 자료가 사라지면 왜 깨졌는지 영영 알 수 없다. 상태만 달아 적재한다."""
    parsed = parse_wrapper({"run_id": "r1", "final_text": "{이건 JSON 이 아니다"})
    assert parsed.parse_status == "parse_failed"
    assert parsed.parse_error
    assert parsed.raw_json["final_text"]  # 래퍼가 통째로 남는다

    report = build_report(parsed)
    assert report.ticker is None
    assert report.raw_json is parsed.raw_json


def test_실행_실패와_되묻기_위반은_상태로_표시된다() -> None:
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
    assert build_report(parsed).ticker == "005930"


def test_background_는_문자열과_객체를_둘_다_받는다() -> None:
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


def test_실제_보고서에서도_혼용이_펴진다() -> None:
    """합성 입력만으로는 부족하다. 실제 산출물에 watch 객체와 문자열이 같은 칸에 있다."""
    report = build_report(parse_report_file(SAMSUNG))
    neutral = report.background["neutral"]
    assert all(set(item) == {"text", "watch"} for item in neutral)
    assert any(item["watch"] for item in neutral)


def test_counter_가_null_인_것은_정상값이다() -> None:
    """방향이 어긋나는 재료가 없는 날과 no_clear_cause 인 날은 counter 가 null 이다.
    빈 문자열로 바꾸면 화면이 '없음'과 '못 채움'을 구분하지 못한다."""
    report = build_report(parse_report_file(NO_CAUSE))
    assert report.verdict == "no_clear_cause"
    assert report.summary_counter is None
    assert report.summary_move  # 나머지 칸은 채워져 있다
    assert report.factors == []  # no_clear_cause 면 factors 는 빈 배열이다


def test_as_of_는_날짜와_합쳐_KST_aware_로_저장된다() -> None:
    """프롬프트 출력은 'HH:MM' 문자열뿐이다. 루트 CLAUDE.md 가 naive datetime 을
    금지하므로 date 와 합쳐 타임존을 붙인다. 원본 문자열은 raw_json 에 남는다."""
    report = build_report(parse_report_file(SAMSUNG))
    assert report.target_date == date(2026, 9, 18)
    assert report.as_of == datetime(2026, 9, 18, 15, 30, tzinfo=KST)
    assert report.raw_json["as_of"] == "15:30"


def test_change_pct_는_값이_흔들리지_않는다() -> None:
    """Decimal(3.37) 은 3.370000000000000106... 이 된다. 루트 CLAUDE.md 가
    가공하지 않은 값을 요구하므로 적재가 값을 바꾸면 안 된다."""
    report = build_report(parse_report_file(SAMSUNG))
    assert report.change_pct == Decimal("3.37")
    assert str(report.change_pct) == "3.37"


def test_factor_와_출처는_순서를_지켜_펴진다() -> None:
    """factors 는 중요도 순이라 배열 순서 자체가 정보다. 순서가 섞이면 화면의
    '이유' 절이 덜 중요한 것부터 나온다."""
    report = build_report(parse_report_file(HYNIX))
    assert [f.order_index for f in report.factors] == [0, 1, 2, 3]
    first = report.factors[0]
    assert first.claim and first.stance in {"bullish", "bearish", "neutral"}
    assert first.direction_match is True
    assert [s.order_index for s in first.sources] == list(range(len(first.sources)))
    assert first.sources[0].source == "telegram"
    assert first.sources[0].datetime_kst is None or first.sources[0].datetime_kst.tzinfo


def test_상한_초과를_잘라내지_않는다(caplog) -> None:
    """factors 4 / terms 8 / background 전체 6·칸당 3 이 프롬프트의 상한이다.
    적재가 말없이 자르면 실행 점검 스크립트의 상한 위반 검사가 영원히 통과한다.
    그대로 넣고 로그로만 알린다."""
    raw = json.loads(HYNIX.read_text(encoding="utf-8"))
    report_json = json.loads(raw["final_text"])
    total = sum(len(report_json["background"][k]) for k in ("bullish", "bearish", "neutral"))
    assert total > 6, "픽스처가 상한을 안 넘어 이 테스트가 의미를 잃었다"

    with caplog.at_level("WARNING"):
        report = build_report(parse_wrapper(raw))

    assert sum(len(v) for v in report.background.values()) == total
    assert "background" in caplog.text


def test_검증_판정은_인자로_받는다() -> None:
    """적재 모듈이 근거 검증을 수행하지 않는다. 판정과 적재를 분리해야 한쪽을
    고쳐도 다른 쪽이 안 흔들린다. 검증기 연결은 후속 PR 이다."""
    parsed = parse_report_file(SAMSUNG)
    assert build_report(parsed).verify_status == "not_verified"

    failed = build_report(parsed, verify_status="failed", verify_error="quote 불일치 1건")
    assert failed.verify_status == "failed"
    assert failed.verify_error == "quote 불일치 1건"
