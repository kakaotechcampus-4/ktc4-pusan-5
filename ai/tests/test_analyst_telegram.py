"""텔레그램 PDF 에서 메타데이터 뽑기.

네트워크를 타지 않는다. 실제로 틀렸던 케이스를 그대로 픽스처로 박아둔다.
"""

from datetime import UTC, date, datetime

import pytest

from app.services.analyst.schema import PdfText
from app.services.analyst.telegram import (
    KST,
    classify,
    find_category,
    find_goal_price,
    find_opinion,
    find_publisher,
    find_sector_view,
    find_write_date,
    has_usable_body,
    is_ai_generated,
    normalize_opinion,
    parse_channel,
    to_row,
)


def test_parse_channel_accepts_username_and_peer_id() -> None:
    """이름으로 못 여는 채널이 있어서 id:access_hash 도 받는다.

    source_id 가 '이름/메시지번호'라 이름은 따로 받는다 — access_hash 를 거기 넣으면
    값이 바뀔 때 같은 리포트가 다른 행으로 또 들어간다.
    """
    assert parse_channel("sunstudy1234") == ("sunstudy1234", "sunstudy1234")

    label, peer = parse_channel("DOC_POOL=1234567890:1234567890123456789")
    assert label == "DOC_POOL"
    assert peer.channel_id == 1234567890
    assert peer.access_hash == 1234567890123456789

    # 이름을 안 주면 채널 id 를 이름으로 쓴다
    label, peer = parse_channel("1234567890:1234567890123456789")
    assert label == "1234567890"
    assert peer.channel_id == 1234567890


def test_publisher_is_searched_in_whole_body() -> None:
    """증권사명은 대부분 문서 끝 컴플라이언스 고지에 있다.

    앞 4,000자만 보면 표본 122건 중 10건밖에 못 잡았다. 전체를 봐야 97% 가 된다.
    """
    body = "반도체 업황 점검\n" + "본문 " * 3000 + "\n본 자료는 대신증권에서 작성한 것입니다. 대신증권"
    assert find_publisher("아무파일.pdf", body) == "대신증권"


def test_publisher_falls_back_to_filename() -> None:
    """재배포 파일명에는 증권사가 영문으로 박힌다."""
    fn = "현대지에프홀딩스［005440］_20260914_Hungkuk_1131056.pdf"
    assert find_publisher(fn, "증권사 이름이 없는 본문") == "흥국증권"
    assert find_publisher("반도체_삼성증권_260914.pdf", "본문") == "삼성증권"


def test_publisher_is_none_when_unknown() -> None:
    """채널명을 넣으면 거짓 출처가 된다.

    선진짱 55건 중 7건이 증권사가 아니었다 — 기업 IR 자료, 스터닝밸류 리서치, 쟁글.
    """
    assert find_publisher("주식회사 매드업_IR-Book.pdf", "회사 소개 자료입니다") is None


def test_publisher_matches_non_brokerage_houses() -> None:
    body = "SV Research 스터닝밸류 리서치 WEB: www.svresearch.co.kr " * 3
    assert find_publisher("야스［255440］_20260914.pdf", body) == "스터닝밸류 리서치"


def test_opinion_is_searched_near_goal_price_anchor() -> None:
    """리포트 끝의 '투자의견 비율' 공시에 걸리면 안 된다.

    본문 전체를 뒤지는 방식은 표본 122건에서 29건을 틀렸다. 앵커 방식은 1건이다.
    """
    body = (
        "투자의견 매수 유지, 목표주가 180,000원으로 상향\n"
        + "본문 " * 500
        + "\n투자의견 비율: 매수 87.0% 중립 12.0% 매도 0.0%\n목표주가 괴리율 -12.3%"
    )
    assert find_opinion(body) == "매수"


def test_opinion_returns_none_label_when_absent() -> None:
    """전략·경제 자료는 투자의견을 아예 안 낸다. 못 뽑은 게 아니라 없는 것이다."""
    assert find_opinion("9월 FOMC 프리뷰. 금리 동결 전망") == "없음"


def test_normalize_opinion_handles_variants() -> None:
    """증권사마다 표기가 다르다. 네이버가 쓰는 말로 맞춘다."""
    assert normalize_opinion("Buy") == "매수"
    assert normalize_opinion("비중 확대") == "매수"
    assert normalize_opinion("Marketperform") == "중립"
    # N.R / NR / Not Rated 는 의견 없음이다. 네이버의 '없음'과 같은 뜻
    assert normalize_opinion("N.R") == "없음"
    assert normalize_opinion("Not Rated") == "없음"
    assert normalize_opinion(None) == "없음"


def test_goal_price_is_searched_before_appendix() -> None:
    body = "목표주가 180,000원 제시\n" + "본문 " * 3000 + "\n2024년 목표주가 90,000원"
    assert find_goal_price(body) == 180_000
    assert find_goal_price("목표주가 없음") is None


def test_classify_splits_by_item_code_count() -> None:
    """창을 넓히는 문제가 아니었다.

    본문 전체를 뒤지면 채움률이 44% → 56% 로 오르는데 새로 잡힌 8건이 전부 산업
    리포트였다. 종목 9개짜리 방산 리포트에 맨 앞 코드를 넣으면 업종 리포트가
    종목 리포트인 척 끼어든다.
    """
    assert classify("오리온［271560］_20260914.pdf", "") == ("company", "271560")
    assert classify("아무거나.pdf", "오리온(271560) 실적 점검") == ("company", "271560")
    # 코드가 여러 개면 산업 리포트다. 그중 하나를 고르면 거짓이 된다
    body = "한화에어로스페이스(012450) LIG넥스원(079550) 현대로템(064350)"
    assert classify("방산_전략.pdf", body) == ("industry", None)
    assert classify("아무거나.pdf", "종목코드 없는 본문") == (None, None)


def test_filename_item_code_requires_delimiter() -> None:
    """`_코드` 뒤에 세미콜론이 없으면 날짜를 집는다.

    파두_2Q26 IR Book_KOR_260813_D-2 에서 260813 은 2026-08-13 이다.
    값으로는 못 가른다 — 030520(한컴)도 YYMMDD 로 파싱된다. 뒤 구분자가 답이다.
    """
    assert classify("로킷헬스케어_376900;재생은 로킷이 잘 합니다.pdf", "") == ("company", "376900")
    assert classify("파두_2Q26 IR Book_KOR_260813_D-2.pdf", "")[1] is None


def test_category_prefers_title_prefix() -> None:
    """재배포 채널이 증권사 분류를 접두사로 붙인다. 출처가 붙인 라벨이라 제일 세다.

    이걸 안 쓰고 판정에 맡겼더니 '산업_은행…' 을 economy 로, '기업_LG에너지솔루션' 을
    market 으로 보냈다. 본문에 종목코드가 없어 구조 신호가 안 잡히는 건들이다.
    """
    assert find_category("산업_은행_8월_여수신_한화투자증권", "x.pdf", "") == "industry"
    assert find_category("기업_LG에너지솔루션_서프라이즈", "x.pdf", "") == "company"
    assert find_category("경제_같은_환율_다른_충격", "x.pdf", "") == "economy"
    # 접두사가 없으면 종목코드 개수로 본다
    assert find_category("오리온 실적", "오리온［271560］.pdf", "") == "company"
    # 둘 다 없으면 market. 경제와 시황은 규칙으로 안 갈린다
    assert find_category("9월 FOMC 프리뷰", "x.pdf", "금리 동결 전망") == "market"


def test_ai_generated_is_detected_from_body_notice() -> None:
    """네이버는 제목의 '[AI] ' 로 거르는데 재배포 파일명에는 그게 안 남는다.

    본문 고지로 잡으면 파일명이 어떻게 바뀌어도 걸린다. 실제로 파일 10개가
    이름 2개씩으로 들어와 20행이 될 뻔했다.
    """
    assert is_ai_generated("본 보고서는 인공지능(AI) 기술을 사용하여 생성되었습니다.")
    assert is_ai_generated("Company AI Report\n한국IR협의회")
    assert not is_ai_generated("AI 데이터센터 수요가 늘고 있다. 반도체 업황 점검")


def test_filename_date_formats_differ_by_channel() -> None:
    """선진짱은 6자리 날짜, DOC_POOL 은 8자리를 쓴다. 둘 다 받아야 한다."""
    doc_pool = "파크시스템스_수주_호조_기반_실적_성장_지속_메리츠증권_20260915.pdf"
    assert find_publisher(doc_pool, "본문") == "메리츠증권"
    assert find_write_date(doc_pool, datetime(2026, 9, 16, tzinfo=KST)) == date(2026, 9, 15)


def test_write_date_prefers_filename_over_posted_at() -> None:
    """텔레그램에 올린 날과 리포트 발행일이 다를 수 있다. 파일명이 더 정확하다."""
    posted = datetime(2026, 9, 15, 22, 0, tzinfo=KST)
    assert find_write_date("리포트_20260914_Hana_1131056.pdf", posted) == date(2026, 9, 14)
    assert find_write_date("리포트_대신증권_260914.pdf", posted) == date(2026, 9, 14)
    # 파일명에 날짜가 없으면 올린 날로 대신한다
    assert find_write_date("리포트.pdf", posted) == date(2026, 9, 15)
    # UTC 로 와도 KST 로 바꿔서 본다 (UTC 15:00 = KST 다음날 00:00)
    utc_late = datetime(2026, 9, 15, 15, 30, tzinfo=UTC)
    assert find_write_date("리포트.pdf", utc_late) == date(2026, 9, 16)


def test_to_row_fills_analyst_report_columns() -> None:
    """텔레그램 메시지 하나를 analyst_reports 한 행으로."""
    row = to_row(
        channel="sunstudy1234",
        message_id=1131056,
        filename="현대지에프홀딩스［005440］_20260914_Hungkuk_1131056.pdf",
        posted_at=datetime(2026, 9, 15, 9, 0, tzinfo=KST),
        pdf=PdfText(status="ok", text="목표주가 12,000원, 투자의견 매수", chars=22, pages=7),
    )
    # (source, source_category, source_id) 가 자연키다.
    # 메시지 번호는 채널 안에서만 유일해서 채널까지 봐야 한 건이 정해진다.
    assert row["source"] == "telegram"
    assert row["source_category"] == "sunstudy1234"
    assert row["source_id"] == "1131056"
    # category 에 출처를 넣지 않는다. 출처는 source 가 말한다 — 여기는 리포트 종류다
    assert row["category"] == "company"
    assert row["broker"] == "흥국증권"
    assert row["item_code"] == "005440"
    assert row["write_date"] == date(2026, 9, 14)
    assert row["opinion"] == "매수"
    assert row["goal_price"] == 12_000
    assert row["end_url"] == "https://t.me/sunstudy1234/1131056"
    # 작성 시점 주가는 뽑지 않는다. 표본에서 34% 밖에 안 맞아 KRX 에서 계산한다
    assert row["price_at_write"] is None


def test_empty_body_leaves_opinion_and_goal_price_null() -> None:
    """이미지 스캔본이다. '없음'이라고 단정하면 거짓이 된다 — 못 읽은 것뿐이다."""
    row = to_row(
        channel="DOC_POOL",
        message_id=1,
        filename="스캔본.pdf",
        posted_at=datetime(2026, 9, 15, tzinfo=KST),
        pdf=PdfText(status="empty", sha256="a" * 64, size_bytes=2_650_000),
    )
    assert row["opinion"] is None
    assert row["goal_price"] is None
    assert row["body_status"] == "empty"


def test_goal_price_uses_revised_value() -> None:
    """'A에서 B로 조정' 은 B 가 새 목표주가다. 앞 숫자를 집으면 조정 전 값이 된다."""
    assert find_goal_price("목표주가를 58만원에서 45만원으로 조정한다") == 450_000
    assert find_goal_price("목표주가를 580,000원에서 450,000원으로 하향") == 450_000


def test_goal_price_skips_previous_target() -> None:
    """'(D)직전 목표주가 340,000원' 은 현재 값이 아니다."""
    assert find_goal_price("직전 목표주가 340,000원\n목표주가 420,000원") == 420_000
    assert find_goal_price("기존 목표주가 50,000원 목표주가 62,000원") == 62_000


def test_goal_price_handles_notation_variants() -> None:
    """이 네 가지를 못 잡아 47.5% 에 머물렀다. 넣고 나서 네이버 대조 100% 가 됐다."""
    assert find_goal_price("목표주가(12M) 155,000원") == 155_000
    assert find_goal_price("TP 37,000원(유지)") == 37_000
    assert find_goal_price("매수/TP 14만원") == 140_000
    assert find_goal_price("6개월 목표주가 370,000유지") == 370_000


@pytest.mark.parametrize(
    "body",
    [
        "Not Rated목표주가 N/A현재주가 9,350원",
        "투자의견 NotRated목표주가 제시하지않음현재주가 1,721원",
        "Not Rated목표주가 Not Rated현재주가 44,800원",
        "N/R목표주가 - 원현재주가 19,080 원",
        "Not Rated목표주가 n/a현재주가 9,140원",
        "NotRated목표주가:-현재주가:5,300 원",
        "목표주가·투자등급을제시하지않습니다딥노이드(315640,KOSDAQ)",
        "목표주가 미제시 시가총액 10,000억원",
        "목표주가 없음 현재가 10,000원",
    ],
)
def test_goal_price_does_not_cross_missing_target_or_current_price(body: str) -> None:
    """실제 NR 리포트의 현재가와 종목코드를 목표가로 읽지 않는다."""
    assert find_goal_price(body) is None


def test_goal_price_is_independent_of_rating() -> None:
    """의견이 없어도 원문이 직접 제시한 목표가는 보존한다."""
    assert find_goal_price("Not Rated\n목표주가: 25,000 원") == 25_000
    assert find_goal_price("목표주가 (원) 18,000현재주가 (원) 13,400") == 18_000
    assert find_goal_price("목표주가 = 21,000 원") == 21_000


def test_goal_price_ignores_appendix_history() -> None:
    """리포트 끝 '투자의견 및 목표주가 변동추이' 표에 과거 값이 줄줄이 있다."""
    body = "목표주가 180,000원\n투자의견 및 목표주가 변동추이\n목표주가 90,000원 120,000원"
    assert find_goal_price(body) == 180_000


def test_opinion_does_not_match_neutral_adjective() -> None:
    """농심 리포트에서 '환율에 중립적' 의 중립을 등급으로 집었다. 정답은 매수였다."""
    body = "환율에 중립적인 포지션을 유지한다. 저가 매수가 유효하다. BUY (유지)목표주가 540,000원"
    assert find_opinion(body) == "매수"


def test_opinion_ignores_rating_only_in_appendix() -> None:
    """ISC 리포트는 본문에 현재 의견이 없고 끝의 변동추이 표에만 Buy 가 있다."""
    body = "실적을 점검한다.\n투자의견 및 목표주가 변동추이\nBuy 목표주가 90,000원"
    assert find_opinion(body) == "없음"


def test_sector_view_extracts_opinion_and_top_picks() -> None:
    """산업 리포트는 종목별 목표주가 대신 이걸 담는다."""
    body = (
        "은행 업종에 대해 Overweight 의견을 유지한다.\nTop picks: KB금융, 신한지주\n"
        + "본문 " * 200
    )
    opinion, picks = find_sector_view(body)
    assert opinion == "비중확대"
    assert picks == ["KB금융", "신한지주"]


@pytest.mark.parametrize(
    "text",
    [
        "UNEP는 탄소중립을 최종 목표가 아닌 중간 단계로 재정의했다.",
        "중립금리 추정치를 검토하고 탄소 중립 정책을 살펴본다.",
        "네오클라우드: 중립성이라는 무기",
        "원달러 환율에 중립적이며 영향은 중립 판단이다.",
        "AGF US Market Neutral Anti-Beta Fund",
        "공개매수에 대한 의견 표명(수용, 거절, 중립 등)",
        "투자의견 비율: Hold(중립) 3.3% Sell(비중축소) 0%",
    ],
)
def test_sector_view_does_not_treat_neutral_topics_as_rating(text: str) -> None:
    opinion, _ = find_sector_view(text + "\n" + "본문 " * 200)
    assert opinion is None


@pytest.mark.parametrize(
    "text",
    ["반도체 (중립)", "업종의견: 중립", "투자의견 중립", "중립 의견을 유지한다.",
     "Neutral\n", "Neutral(유지)", "반도체 (NEUTRAL)", "업종의견: 중 립"],
)
def test_sector_view_preserves_explicit_neutral_rating(text: str) -> None:
    opinion, _ = find_sector_view(text + "\n" + "본문 " * 200)
    assert opinion == "중립"


def test_sector_view_finds_explicit_rating_after_carbon_neutral_topic() -> None:
    body = "탄소중립 정책을 점검한다.\n반도체 (중립)\n" + "본문 " * 200
    assert find_sector_view(body)[0] == "중립"


@pytest.mark.parametrize(
    "text",
    [
        "잔여 소송 문제가 동사에 미칠 부정적인 영향은 제한적이다.",
        "고부가 제품 비중 확대가 수익성 개선으로 이어질 것이다.",
        "수익성은 H&B채널 대형 콜라보 비중축소에 따른 원가 개선에 기인한다.",
        "북미 농산물 작황에 긍정적인 영향을 미친다.",
        "해외 자회사 매출 비중 확대\n본문을 살펴본다.",
    ],
)
def test_sector_view_rejects_business_mix_and_sentiment_words(text: str) -> None:
    assert find_sector_view(text + "\n" + "본문 " * 200)[0] is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("업종의견: 비중축소", "비중축소"),
        ("반도체 (Positive)", "비중확대"),
        ("업종의견: 부정적", "비중축소"),
        ("비중확대/유지제약/바이오", "비중확대"),
        ("게임 (비중확대/유지)신작은 미래다", "비중확대"),
        ("메모리 및 소부장 비중 확대 유효", "비중확대"),
        ("OverweightTop Picks 및 관심종목", "비중확대"),
        ("[로보틱스] Overweight[자동차/로보틱스]", "비중확대"),
        ("조선OverweightData Center Inside", "비중확대"),
        ("Overweight(Maintain)유틸리티", "비중확대"),
        ("I Underweight I 2026.9.14", "비중축소"),
    ],
)
def test_sector_view_preserves_explicit_rating_formats(text: str, expected: str) -> None:
    assert find_sector_view(text + "\n" + "본문 " * 200)[0] == expected


def test_top_picks_strips_korean_particles() -> None:
    """'최선호주로 하이브를 제시한다' 를 그대로 자르면 '로 하이브를' 이 들어간다."""
    body = "최선호주로 하이브를 제시한다\n" + "본문 " * 200
    _, picks = find_sector_view(body)
    assert picks == ["하이브"]


def test_watermark_only_body_is_not_usable() -> None:
    """body_chars 는 1,000자가 넘는데 내용이 없는 PDF 가 302건 중 7건 있었다.

    이걸 본문으로 치면 요약을 만들 때 모델이 없는 숫자를 지어낸다.
    """
    watermark = "DB Copyright (C) FnGuide Inc. (WR::HY0009::20260915)\n" * 30
    assert not has_usable_body(watermark)
    assert has_usable_body("반도체 업황이 개선되고 있다. " * 40)


def test_industry_report_omits_goal_price() -> None:
    """종목이 여러 개라 그중 하나를 실으면 거짓이 된다. item_code 를 비우는 것과 같다."""
    body = (
        "은행 업종 Overweight 유지. Top picks: KB금융\n"
        "KB금융(105560) 신한지주(055550) 하나금융지주(086790)\n"
        "목표주가 120,000원\n" + "본문 " * 200
    )
    row = to_row(
        channel="sunstudy1234",
        message_id=2,
        filename="산업_은행_8월_여수신_한화투자증권_260914.pdf",
        posted_at=datetime(2026, 9, 14, tzinfo=KST),
        pdf=PdfText(status="ok", text=body, chars=len(body), pages=20),
    )
    assert row["category"] == "industry"
    assert row["item_code"] is None
    assert row["goal_price"] is None
    assert row["opinion"] is None
    assert row["sector_opinion"] == "비중확대"
    assert row["top_picks"] == ["KB금융"]


def test_to_row_does_not_trust_stale_ok_status_or_char_count():
    row = to_row(channel="channel_one", message_id=1, filename="scan.pdf",
                 posted_at=datetime(2026, 9, 15, tzinfo=KST),
                 pdf=PdfText(status="ok", text="", chars=9999))
    assert row["body_status"] == "empty"
    assert row["body_chars"] == 0


def test_to_row_keeps_watermark_evidence_but_marks_it_unusable():
    watermark = "DB Copyright © FnGuide Inc. (WR::test)\n" * 100
    row = to_row(channel="channel_one", message_id=1, filename="scan.pdf",
                 posted_at=datetime(2026, 9, 15, tzinfo=KST),
                 pdf=PdfText(status="ok", text=watermark, chars=len(watermark)))
    assert row["body_status"] == "unusable"
    assert row["body_text"] == watermark
    assert row["body_chars"] == len(watermark)


def test_excluded_publisher_is_skipped_even_when_other_broker_is_cited():
    from app.services.analyst.telegram import exclusion_reason

    body = "기업리서치@KONNECT2026.9.3.\nR–Advisory\n과거 SK증권 자료 인용"
    assert exclusion_reason("report.pdf", body) == "수집 제외 출처: R-Advisory/KONNECT"


def test_excluded_filename_is_skipped_without_readable_body():
    from app.services.analyst.telegram import exclusion_reason

    assert exclusion_reason("딥노이드［315640］_20260908_Konnect_1129816.pdf", "")


def test_mention_of_excluded_publisher_does_not_exclude_a_broker_report():
    from app.services.analyst.telegram import exclusion_reason

    assert exclusion_reason("report.pdf", "SK증권 기업분석\n참고: R–Advisory by KONNECT") is None
