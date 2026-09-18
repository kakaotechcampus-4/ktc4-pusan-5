"""네이버 리서치 응답 파싱. 실제 응답을 그대로 붙여 픽스처로 쓴다.

네트워크를 타지 않는다 — 남의 서버 사정에 우리 테스트가 흔들리면 안 된다.
"""

from datetime import date

import pytest

from app.services.analyst.naver import (
    CATEGORIES,
    NaverResearchClient,
    extract_sector_view,
    is_ai_generated,
    merge_detail,
    parse_list_row,
    strip_html,
    to_int,
)

# 2026-09-14 m.stock.naver.com/api/research/company?page=1 실제 응답 한 줄
LIST_ROW = {
    "researchCategory": "종목분석",
    "category": "종목분석",
    "itemCode": "271560",
    "itemName": "오리온",
    "researchId": 96141,
    "title": "실적 안정성과 주주 환원으로 리레이팅 기대",
    "brokerName": "DS투자증권",
    "writeDate": "2026-09-14",
    "readCount": "613",
    "endUrl": "https://m.stock.naver.com/research/company/96141",
}

DETAIL = {
    "itemCode": "271560",
    "itemName": "오리온",
    "researchId": 96141,
    "title": "실적 안정성과 주주 환원으로 리레이팅 기대",
    "brokerName": "DS투자증권",
    "writeDate": "2026-09-14",
    "readCount": "613",
    "attachUrl": "https://stock.pstatic.net/stock-research/company/66/20260914_company_148994000.pdf",
    "content": "<p><strong>26년 8월: 소비 둔화</strong></p><p><br>매출액 3,010억원(+9% YoY)</p>",
    "opinion": "매수",
    "goalPrice": "180000",
    "prevGoalPrice": "119300",
    "priceAtWriteDate": "119300",
}

# 산업분석에는 종목코드·투자의견·목표주가가 없다
INDUSTRY_DETAIL = {
    "researchId": "46078",
    "title": "[매태호] 27년 국방예산으로 보는 K-방산 발전 방향성",
    "brokerName": "DS투자증권",
    "writeDate": "2026-09-14",
    "readCount": "445",
    "attachUrl": "https://stock.pstatic.net/stock-research/industry/199_20260914.pdf",
    "content": "<p>방산 예산이 늘었다</p>",
}


def test_parse_list_row_maps_naver_fields() -> None:
    """네이버 목록 한 줄을 AnalystReportItem 으로."""
    item = parse_list_row("company", LIST_ROW)
    assert item.source_id == "96141"  # int 로 오지만 문자열로 통일한다
    assert item.source_category == "company"
    assert item.category == "company"
    assert item.item_code == "271560"
    assert item.write_date == date(2026, 9, 14)
    assert item.read_count == 613


def test_merge_detail_fills_summary_and_goal_price() -> None:
    """요약·목표주가·PDF 링크는 상세 응답에만 있다."""
    item = merge_detail(parse_list_row("company", LIST_ROW), DETAIL)
    assert item.opinion == "매수"
    assert item.goal_price == 180_000
    # prevGoalPrice 는 직전 목표주가가 아니라 현재가의 중복이라 저장하지 않는다
    assert item.price_at_write == 119_300
    assert item.upside_pct == pytest.approx(50.88, abs=0.01)  # 상승여력
    assert item.summary_text is not None
    assert "<p>" not in item.summary_text
    assert item.attach_url is not None and item.attach_url.endswith(".pdf")


def test_industry_report_parses_without_item_code() -> None:
    row = {**LIST_ROW, "researchId": 46078, "itemCode": None, "itemName": None}
    item = merge_detail(parse_list_row("industry", row), INDUSTRY_DETAIL)
    assert item.item_code is None
    assert item.goal_price is None
    assert item.opinion is None
    assert item.summary_text == "방산 예산이 늘었다"


def test_strip_html_keeps_line_breaks() -> None:
    """네이버 요약은 HTML 이다. 태그는 걷되 <br> 은 줄바꿈으로 살린다."""
    assert strip_html("<p>가<br>나</p>") == "가\n나"
    assert strip_html("<p>&amp;컴퍼니</p>") == "&컴퍼니"
    assert strip_html("") is None
    assert strip_html(None) is None


def test_to_int_handles_commas_and_blanks() -> None:
    """네이버는 숫자를 문자열로 준다. 빈 값·콤마·'-' 가 섞여 온다."""
    assert to_int("180,000") == 180_000
    assert to_int("") is None
    assert to_int("-") is None
    assert to_int(None) is None
    assert to_int("0") == 0


def test_skips_ai_generated_reports() -> None:
    """한국IR협의회가 AI 로 만들어 올리는 자료는 애널리스트 리포트가 아니다.

    실제로 데이터도 틀려 있다 — 아이디스홀딩스(054800)와 씨에스베어링(297090)이
    같은 제목을 달고 있고, 에르코스(435570)는 앞 종목의 제목을 달고 있다.
    네이버 API 원본이 그렇다(2026-09-15 직접 확인).
    """
    row = {
        **LIST_ROW,
        "brokerName": "한국IR협의회",
        "title": "[AI] 풍력 터빈용 피치·요 베어링 제조기업",
    }
    assert is_ai_generated(parse_list_row("company", row)) is True

    # 같은 기관이어도 사람이 쓴 건 받는다
    row2 = {**LIST_ROW, "brokerName": "한국IR협의회", "title": "Control the Heat, Lead the Chip"}
    assert is_ai_generated(parse_list_row("company", row2)) is False

    # 제목에 AI 라는 말이 들어가는 증권사 리포트는 걸리지 않는다
    row3 = {**LIST_ROW, "title": "AI 수요의 저변 확장"}
    assert is_ai_generated(parse_list_row("company", row3)) is False


def test_sector_view_ignores_compliance_appendix() -> None:
    """리포트 뒤쪽 컴플라이언스 부록에 과거 의견이 잔뜩 있어서 뒤를 보면 안 된다."""
    head = "투자의견 Overweight 유지. Top picks: 인텔리안테크, RFHIC\n" + "본문 " * 500
    tail = "투자의견 비율 매수 87% 중립 12%\n투자의견 변동 내역: Underweight\n" * 20
    opinion, picks = extract_sector_view(head + tail)
    assert opinion == "비중확대"
    assert picks == ["인텔리안테크", "RFHIC"]

    assert extract_sector_view(None) == (None, [])
    assert extract_sector_view("아무 의견 없는 본문") == (None, [])


class FakeResponse:
    status_code = 200

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> object:
        return self._payload


class FakeClient:
    """목록 2페이지를 흉내 낸다. 2페이지는 since 보다 옛날 글이다."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def get(self, url: str, params: dict | None = None):
        self.calls.append((url, params or {}))
        page = (params or {}).get("page", 1)
        if page == 1:
            return FakeResponse(
                [
                    LIST_ROW,
                    {**LIST_ROW, "researchId": 96140, "writeDate": "2026-09-13"},
                ]
            )
        return FakeResponse([{**LIST_ROW, "researchId": 90000, "writeDate": "2026-08-01"}])

    async def aclose(self) -> None:
        pass


async def test_collect_since_stops_at_older_rows() -> None:
    fake = FakeClient()
    client = NaverResearchClient(client=fake)  # type: ignore[arg-type]
    items = await client.collect_since("company", date(2026, 9, 13), page_size=2)
    assert [i.source_id for i in items] == ["96141", "96140"]  # 8월 글은 안 들어온다
    assert len(fake.calls) == 2  # 2페이지를 보고 멈췄다


async def test_collect_since_skips_known_ids() -> None:
    client = NaverResearchClient(client=FakeClient())  # type: ignore[arg-type]
    items = await client.collect_since(
        "company", date(2026, 9, 13), page_size=2, known_ids={"96141"}
    )
    assert [i.source_id for i in items] == ["96140"]


def test_invest_and_daily_share_researchid_but_stay_distinct() -> None:
    """invest 와 daily 를 market 으로 합쳐도 서로 다른 행으로 남아야 한다.

    두 카테고리의 researchId 시퀀스가 각자 올라가서 구간이 어긋나 있을 뿐,
    번호 자체는 겹친다. 실측(2026-09-18)으로 invest 2026-01-16 자 37550 과
    daily 2026-09-17 자 37550 이 둘 다 살아 있었고 같은 번호대에서 42건이 겹쳤다.

    category 로 구별하려 들면 둘 다 market 이라 같은 건이 된다. source_category
    가 갈라준다.
    """
    row = {"researchId": 37550, "title": "x", "brokerName": "대신증권",
           "writeDate": "2026-01-16"}
    a = parse_list_row("invest", row)
    b = parse_list_row("daily", {**row, "writeDate": "2026-09-17"})

    assert a.source_id == b.source_id == "37550"
    assert a.category == b.category == "market"       # 여기서는 같아진다
    assert a.source_category != b.source_category     # 여기서 갈린다

    def key(item):
        return ("naver", item.source_category, item.source_id)

    assert key(a) != key(b)


def test_naver_categories_map_to_four_kinds() -> None:
    """네이버 5종이 우리 4종으로 들어온다. invest·daily 만 합쳐진다."""
    got = {c: parse_list_row(c, {"researchId": 1, "title": "x", "brokerName": "y",
                                 "writeDate": "2026-09-14"}).category
           for c in CATEGORIES}
    assert got == {
        "company": "company",
        "industry": "industry",
        "economy": "economy",
        "invest": "market",
        "daily": "market",
    }
