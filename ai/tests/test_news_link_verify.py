"""생성 요약(C) 규칙 검사. 실제로 걸렸던 요약을 그대로 옮겨 둔다."""

from app.services.news_link.compare.verify import hangul_ratio, verify_summary

BODY = (
    "솔리다임이 미국에 첫 낸드 양산라인 구축을 검토 중인 것으로 19일 파악됐다.\n"
    "최근 AI 인프라 구축 확대로 낸드 수요가 폭증하는 만큼, 미국 현지 고객과 협력을 "
    "강화하기 위한 전략이란 풀이가 나온다.\n"
    "올 2분기 SK하이닉스 낸드 매출은 142억 달러로 전 분기보다 89.5% 뛰었다."
)


def kinds(flags: list[str]) -> list[str]:
    return [f.split(":")[0] for f in flags]


def test_faithful_summary_passes() -> None:
    summary = "SK하이닉스 손자회사 솔리다임이 미국에 첫 낸드 양산라인 구축을 검토 중인 것으로 파악됐다."
    assert verify_summary(summary, "SK하이닉스", "", BODY) == []


def test_speculation_stated_as_fact_is_caught() -> None:
    """텔레그램 테스트에서 실제로 나왔다. '풀이가 나온다' 를 '전략이다' 로 단정했다."""
    summary = "최근 AI 인프라 확대로 낸드 수요가 폭증함에 따라 미국 현지 고객과 협력을 강화하기 위한 전략이다."
    assert kinds(verify_summary(summary, "SK하이닉스", "", BODY)) == ["hedge"]


def test_source_attribution_may_be_dropped() -> None:
    """'업계에 따르면' 같은 출처는 빠져도 된다. 처음 규칙은 이걸 잡아서 42건 중 10건이 걸렸다."""
    body = "21일 업계에 따르면 티엘비는 PCB 회로 프린팅 기술 확보에 성공했다."
    assert verify_summary("티엘비는 PCB 회로 프린팅 기술 확보에 성공했다.", "티엘비", "", body) == []


def test_number_missing_from_source_is_caught() -> None:
    summary = "SK하이닉스 낸드 매출은 전 분기보다 95% 뛰었다."
    assert "numbers" in kinds(verify_summary(summary, "SK하이닉스", "", BODY))


def test_number_in_title_is_not_invented() -> None:
    """파일럿에서 제목에만 있던 7.56 이 오탐으로 걸렸다."""
    body = "메타의 AI 에이전트가 여행 예약 플랫폼을 약화할 수 있다는 우려가 나왔다."
    flags = verify_summary("에어비앤비 주가는 7.56% 급락했다.", "에어비앤비",
                           "에어비앤비 7.56% 급락", body)
    assert "numbers" not in kinds(flags)


def test_summary_not_in_korean_is_caught() -> None:
    body = "受AI需求強勁帶動，三星電機出貨量創近五年單月新高。"
    flags = verify_summary("三星電機出貨量創近五年單月新高。", "삼성전기", "", body)
    assert "not_korean" in kinds(flags)


def test_foreign_source_skips_character_matching() -> None:
    """영어 원문을 한국어로 요약하면 글자가 겹칠 수 없다. 걸리는 게 전부면 검사가 아니다."""
    body = "Nvidia CEO Jensen Huang said the company will double the number of chips it sells."
    flags = verify_summary("엔비디아는 내년에 칩 판매량을 두 배로 늘릴 것이라고 밝혔다.", "엔비디아", "", body)
    assert flags == []


def test_translated_number_is_only_a_hint() -> None:
    body = "It points to growth for the next six quarters."
    flags = verify_summary("향후 6개 분기 동안 성장이 이어질 전망이다.", "엔비디아", "", body)
    assert kinds(flags) == ["numbers(참고·번역)"]


def test_summary_for_article_without_the_stock_is_caught() -> None:
    body = "8월 생산자물가는 전력·가스 요금 상승으로 0.2% 올랐다."
    flags = verify_summary("전력·가스 요금 상승으로 생산자물가가 0.2% 올랐다.", "한국전력", "", body)
    assert "stock_absent" in kinds(flags)


def test_none_answer_when_stock_is_present_is_caught() -> None:
    flags = verify_summary("관련 내용 없음", "SK하이닉스", "", BODY)
    assert kinds(flags) == ["stock_present"]


def test_hangul_ratio_ignores_digits_and_spaces() -> None:
    assert hangul_ratio("삼성 2026") == 1.0
    assert hangul_ratio("SK하이닉스") == 4 / 6  # 로마자 2 + 한글 4
