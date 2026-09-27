"""텔레그램 채널에 올라오는 증권사 리포트 PDF 어댑터.

네이버가 싣지 않는 리포트가 여기 있다. 네이버에 들어오는 증권사는 21곳뿐이고
삼성증권·NH투자증권은 0건이다(3주 실측). 대형사 리포트는 텔레그램 재배포 채널에서만 보인다.

## 네이버와 다른 점

네이버는 목록 API 가 종목코드·투자의견·목표주가를 구조화해서 준다. 텔레그램은
**PDF 파일 하나가 전부다.** 파일명과 본문에서 직접 뽑아야 한다.

같은 리포트가 네이버에도 있는 건으로 채점한 규칙별 정확도:

    broker      97%    증권사 닫힌 목록에서 본문 전체 최다 등장
    item_code   82%    틀린 건 0. 못 찾은 것뿐이다
    goal_price  100%   40건 대조. 부록 컷오프 + 'A에서 B로' 처리가 있어야 나온다
    opinion     100%   40건 대조. 부록 컷오프 + 앵커에서 최근접

`broker` 는 **본문 전체**를 봐야 한다. 증권사명은 99%가 본문에 있는데 앞 4,000자에는
10건뿐이었다 — 대부분 문서 끝 컴플라이언스 고지에 적혀 있다.

## 채널명을 발행기관으로 쓰지 않는다

재배포 채널은 발행처가 아니다. 못 찾으면 `broker` 를 NULL 로 둔다. 실제로 선진짱
55건 중 7건이 증권사가 아니었다 — 기업 IR 자료 4건(발행처가 회사 본인),
스터닝밸류 리서치 2건, 쟁글 1건(둘 다 증권사가 아닌 리서치 하우스).
채널명을 넣었으면 7건 전부 거짓 출처가 됐다.
"""

import logging
import re
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.services.analyst.schema import PdfText

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 09-07~09-15 전 채널 전수 조사에서 PDF 를 실제로 많이 올린 채널.
# 나머지 채널은 같은 기간 합쳐서 100건이 안 되고 파일명 규격도 제각각이다.
#   sunstudy1234  9일치 400건 1.4GB
#   DOC_POOL      9일치 76건 328MB — 이름으로 못 연다(parse_channel 주석 참고).
#                 받으려면 실행할 때 `--channel DOC_POOL=<채널id>:<access_hash>` 로 준다.
# 채널 간 PDF 중복률은 10.5% 였다. 90%는 한 채널에만 있다 —
# "어차피 다 중복"이 아니라서 여러 채널을 받는 의미가 있다.
DEFAULT_CHANNELS = ("sunstudy1234",)

# 본문에서 찾을 발행기관. 닫힌 목록이라 오탐이 안 난다.
# 증권사가 아닌 리서치 하우스도 넣는다 — 실제로 섞여 들어온다.
PUBLISHERS = (
    "한국IR협의회", "미래에셋증권", "한국투자증권", "삼성증권", "NH투자증권", "KB증권",
    "신한투자증권", "하나증권", "키움증권", "메리츠증권", "대신증권", "유안타증권",
    "유진투자증권", "IBK투자증권", "한화투자증권", "교보증권", "DS투자증권", "다올투자증권",
    "현대차증권", "iM증권", "SK증권", "LS증권", "상상인증권", "BNK투자증권", "신영증권",
    "흥국증권", "부국증권", "하이투자증권", "스터닝밸류 리서치", "쟁글",
    # 아래는 미상 74건을 훑다가 본문에서 실제로 확인한 것들이다. 파일명 토큰만 보고
    # 추측한 건 넣지 않았다 — dyneasset·IRKUDOS·Aris 는 근거가 없어 미상으로 둔다.
    "DB증권", "리딩투자증권", "민트투자자문",
)

# 재배포 파일명에는 증권사가 영문으로 박힌다:
#   현대지에프홀딩스［005440］_20260914_Hungkuk_1131056.pdf
FILENAME_PUBLISHER = {
    "NH": "NH투자증권", "KB": "KB증권", "Hana": "하나증권", "Shinhan": "신한투자증권",
    "Samsung": "삼성증권", "Kiwoom": "키움증권", "Daishin": "대신증권", "Eugene": "유진투자증권",
    "Mirae": "미래에셋증권", "Meritz": "메리츠증권", "Hyundai+Motor": "현대차증권",
    "Sangsangin": "상상인증권", "Yuanta": "유안타증권", "IBK": "IBK투자증권",
    "Kyobo": "교보증권", "Hanwha": "한화투자증권", "SK": "SK증권", "DS": "DS투자증권",
    "Daol": "다올투자증권", "LS": "LS증권", "iM": "iM증권", "Korea+Investment": "한국투자증권",
    "Hungkuk": "흥국증권", "Hi": "하이투자증권", "BNK": "BNK투자증권", "Shinyoung": "신영증권",
    "Bookook": "부국증권", "Stunning+Value+Research": "스터닝밸류 리서치",
    # Mirae 는 있었는데 Mirae+Asset 이 없어서 미래에셋 3건을 놓쳤다.
    "Mirae+Asset": "미래에셋증권", "DB": "DB증권", "Leading": "리딩투자증권",
    "Mint+Investment+Advisors": "민트투자자문",
}
# 파일명 토큰은 대소문자가 제각각이다(Daol / DAOL). 소문자로 맞춰 한 번 더 찾는다.
_FILENAME_PUBLISHER_CI = {k.lower(): v for k, v in FILENAME_PUBLISHER.items()}

# 파일명에서 발행기관·종목코드·발행일이 앉는 자리
_FN_PUBLISHER_EN = re.compile(r"_\d{8}_([A-Za-z+]+)_\d+\.pdf$", re.IGNORECASE)
# 채널마다 파일명 규격이 다르다. 날짜가 6자리(260915)일 수도 8자리(20260915)일 수도 있다.
#   선진짱   반도체_전략_대신증권_260915.pdf
#   DOC_POOL 파크시스템스_수주_호조_..._메리츠증권_20260915.pdf
_FN_PUBLISHER_KO = re.compile(r"_([가-힣A-Za-z]+(?:증권|협의회))_\d{6,8}\.pdf$")
# 파일명의 종목코드. 세 가지 표기가 실제로 온다.
#     아모레퍼시픽［090430］_20260914_NH_1131018      전각 괄호
#     네오오토 (212560);변속기에서 감속기로            반각 괄호 + 세미콜론
#     로킷헬스케어_376900;재생은 로킷이 잘 합니다        밑줄 + 세미콜론
# `_코드` 뒤에 세미콜론을 **요구한다.** 안 그러면 파일명의 날짜를 집는다 —
#     파두_2Q26 IR Book_KOR_260813_D-2   ← 260813 은 2026-08-13 이다
# 날짜인지 코드인지는 값으로 못 가른다(030520 한컴, 090430 아모레퍼시픽도
# YYMMDD 로 파싱된다). 뒤에 오는 구분자가 답이다.
_FN_CODE = re.compile(r"［(\d{6})］|[(（](\d{6})[)）]|_(\d{6})\s*;")

# 재배포 채널이 증권사 분류를 제목 접두사로 붙인다. 내가 만든 규칙이 아니라
# 출처가 붙인 라벨이라 네이버 category 와 같은 권위를 갖는다.
#     기업_LG에너지솔루션_드디어_서프라이즈_미래에셋증권_260915   → company
#     산업_은행_8월_여수신_조달_포트폴리오의_악화_한화투자증권      → industry
#     경제_같은_환율,_다른_충격_Eco_20260914_Hanwha            → economy
_TITLE_KIND = {"기업": "company", "산업": "industry", "경제": "economy"}
_TITLE_PREFIX = re.compile(r"^(기업|산업|경제)[_\s]")
# 날짜가 뒤에만 붙는 게 아니라 **앞에** 붙는 파일도 있다.
#   오리온［271560］_20260914_Shinhan_1131089.pdf   가운데
#   반도체_전략_대신증권_260915.pdf                  끝
#   260909_메카로(라이징스타).pdf                    앞   ← 이걸 놓치고 있었다
# 앞쪽을 안 보면 텔레그램에 올라온 날로 떨어진다. 네이버에도 있는 48건과 대조했더니
# 어긋난 6건 중 5건이 이 경우였다.
_FN_DATE = re.compile(r"^(\d{8})_|^(\d{6})_|_(\d{8})_|_(\d{8})\.pdf$|_(\d{6})\.pdf$")
_BODY_CODE = re.compile(r"[(（\[]\s*(\d{6})\s*[)）\]]")

# '중립적'·'중립화' 의 '중립' 을 등급으로 집지 않게 뒤 글자를 막는다. 농심 리포트가
# "환율에 중립적 포지션 … BUY (유지)목표주가 540,000원" 이라 중립을 집었다. 정답은 매수다.
_OPINION = re.compile(
    r"(Strong\s*Buy|STRONG\s*BUY|BUY|Buy|매\s?수|중\s?립(?![적화])|Hold|HOLD|Neutral|NEUTRAL"
    r"|Outperform|Marketperform|비중\s?확대|비중\s?축소|매\s?도|Sell|SELL"
    r"|NOT\s*RATED|Not\s*Rated|Trading\s*Buy"
    r"|(?<![A-Za-z])N\s?\.\s?R\.?(?![A-Za-z])|(?<![A-Za-z])NR(?![A-Za-z]))"
)
# 리포트 끝에는 "투자의견 비율 매수 87% 중립 12% 매도 0%" 공시가 붙는다.
# 본문 전체를 뒤지면 거기 걸려서, 이 표식이 있는 구간은 건너뛴다.
_OPINION_RATIO = re.compile(r"(매수|중립|매도)\s*[\d.]+\s*%")
_GOAL_ANCHOR = re.compile(r"목표\s*주가|목표가|TP\b")

# 여기서부터는 과거 목표주가·과거 투자의견이다. 리포트 끝 부록에 변동 이력이 표로 붙는다.
# 목표주가와 투자의견 **둘 다** 이 컷오프를 쓴다. ISC 리포트는 본문에 현재 의견이 없고
# 끝의 '투자의견 및 목표주가 변동추이' 표에만 Buy 가 있는데, 컷오프가 없으면
# 그 과거 등급을 현재 의견으로 싣는다(네이버 정답은 '없음').
_APPENDIX = re.compile(
    r"투자의견\s*및\s*목표주가\s*변동|목표주가\s*변동\s*추이|투자의견\s*변동\s*내역"
    r"|목표주가\s*추이|괴리율|Compliance\s*Notice"
)
# '목표주가를 58만원에서 45만원으로 조정' — 뒤 숫자가 새 목표주가다. 일반형보다 먼저 본다.
_GOAL_CHANGE = re.compile(
    r"목표\s*주가\S{0,3}\s*"
    r"(?:[\d,]{4,12}\s*원?|\d{1,4}\s*만\s*원?)\s*에서\s*"
    r"([\d,]{4,12}|\d{1,4}\s*만)\s*원?\s*(?:으)?로"
)
# 표기 변형 네 가지를 못 잡아 47.5% 에 머물렀던 자리다.
#     목표주가(12M) 155,000원     (12M) 안의 숫자에서 매칭이 끊긴다
#     TP 37,000원(유지)           TP 가 없었다
#     매수/TP 14만원              한글 단위
#     6개월 목표주가 370,000유지   '원' 없이 다음 글자가 붙는다
# '직전'·'기존'·'종전' 이 바로 앞에 붙은 값은 건너뛴다. 그게 현재 목표주가가 아니다.
_GOAL_PRICE = re.compile(
    r"(?<!직전\s)(?<!직전)(?<!기존\s)(?<!기존)(?<!종전\s)(?<!종전)"
    r"(?:목표\s*주가|목표가|TP)"
    r"(?:\s*\([^)\n]{0,12}\))?"
    r"[^\n\d]{0,20}?"
    r"(?:([\d,]{4,12})\s*원?|(\d{1,4})\s*만\s*원)",
    re.IGNORECASE,
)
# PDF 표의 줄바꿈이 사라지면 "목표주가 N/A현재주가 9,350원" 이 한 줄이 된다.
# 금액까지의 구간에 미제시 표기나 다른 가격 항목이 있으면 그 숫자는 목표가가 아니다.
# 투자의견 '없음' 자체는 배제하지 않는다. 의견 없이 목표가만 제시하는 자료도 있다.
_GOAL_VALUE_BARRIER = re.compile(
    r"N\s*/\s*A|Not\s*Rated|N\s*[/.]\s*R\.?|미\s*제시"
    r"|제시\s*(?:하지\s*않|안)|없음|(?:현재|종|기준)\s*(?:주가|가격|가)",
    re.IGNORECASE,
)

# 한국IR협의회가 AI 로 만든 자료. 네이버 쪽과 같은 이유로 뺀다 — 투자의견과 목표주가가
# 비어 있고 제목이 종목과 맞지 않는다. 네이버는 제목의 '[AI] ' 로 거르는데 재배포
# 파일명에는 그게 안 남는다. 본문의 생성 고지로 잡으면 파일명이 바뀌어도 걸린다.
# 실제로 파일 10개가 이름 2개씩으로 들어와 20행이 될 뻔했다.
_AI_DECLARED = re.compile(
    r"AI\s*Report|인공지능\s*\(?\s*AI\s*\)?\s*기술을\s*사용하여\s*생성", re.IGNORECASE
)

# 산업 리포트의 업종의견·Top picks. 본문 **앞 절반**만 본다.
_SECTOR = re.compile(
    r"(Overweight|OVERWEIGHT|비중\s?확대|Neutral|NEUTRAL|중\s?립"
    r"|Underweight|UNDERWEIGHT|비중\s?축소|Positive|긍정적|Negative|부정적)"
)
_SECTOR_RATING_LABEL = re.compile(
    r"(?:(?:업종|산업|투자)?\s*(?:의견|등급|판단)|업종|산업)"
    r"\s*[:：]?\s*[\"'‘“(（\[]?\s*$"
)
_TOP_PICK = re.compile(
    r"(?:Top[\s\-]?picks?|탑\s?픽|최선호주|최선호\s?종목)\s*[:：]?\s*([^\n]{2,80})",
    re.IGNORECASE,
)
_PICK_SPLIT = re.compile(r"[,·/]| 및 |과 |와 ")
# "최선호주로 하이브를 제시한다" 처럼 앵커 뒤에 조사가 붙는다. 그대로 자르면
# '로 하이브를' 같은 문장 조각이 종목명 자리에 들어간다(실제로 3건 나왔다).
_PICK_LEAD = re.compile(r"^(?:로|으로|는|은|이|가|를|을|에|와|과|및|기존|기준)\s*")
_PICK_TAIL = re.compile(r"(?:를|을|는|은|이|가|와|과|이며|이고|입니다|이다)$")
_NOT_A_PICK = {
    "유지", "및", "관심종목", "차선호주", "제시", "상향", "하향", "기타",
    "자동차", "2차전지", "top", "picks", "pick",
}

# 이미지로 된 PDF 인데 **워터마크 레이어에만 텍스트가 있는** 경우가 있다.
# pdftotext 가 그 워터마크를 뽑아서 body_chars 는 1,000자가 넘는데 내용은 0이다.
#     대한항공 Mirae+Asset (body_chars=1,189, 실제 내용 16자)
#         DB Copyright (C) FnGuide Inc. (WR::HY****09::...)   ← 이게 반복
# body_chars 만 보고 본문 확보율을 90.7% 로 봤는데 실제로는 86.1% 였다. 302건 중 7건이다.
_BOILERPLATE = re.compile(
    r"DB\s*Copyright\s*©?\s*FnGuide[^\n]*"
    r"|WR::[^)\n]*\)"
    r"|Copyright\s*©[^\n]*"
    r"|본\s*조사분석자료는[^\n]*"
    r"|무단\s*전재[^\n]*",
    re.IGNORECASE,
)
# 내용이 이보다 적으면 쓸 수 없는 본문으로 본다. 정상 리포트는 평균 32,000자다.
MIN_CONTENT_CHARS = 300


def normalize_opinion(raw: str | None) -> str:
    """표기 변형을 네이버가 쓰는 말로 맞춘다. N.R / NR / Not Rated 는 의견 없음이다."""
    if not raw:
        return "없음"
    s = raw.lower().replace(" ", "").replace(".", "")
    if s in ("매수", "buy", "strongbuy", "outperform", "비중확대", "tradingbuy"):
        return "매수"
    if s in ("중립", "hold", "neutral", "marketperform"):
        return "중립"
    if s in ("매도", "sell", "비중축소"):
        return "매도"
    return "없음"


def find_publisher(filename: str, body: str) -> str | None:
    """본문 → 파일명 순으로 발행기관을 찾는다. 못 찾으면 None.

    본문 전체에서 가장 많이 나온 이름을 쓴다. 리포트 하나에 경쟁사 이름이 스쳐도
    자기 이름이 훨씬 자주 나오기 때문이다(머리말·꼬리말·고지에 반복된다).
    """
    hits = {name: body.count(name) for name in PUBLISHERS if name in body}
    if hits:
        return max(hits, key=lambda name: (hits[name], len(name)))

    m = _FN_PUBLISHER_KO.search(filename)
    if m and m.group(1) in PUBLISHERS:
        return m.group(1)
    m = _FN_PUBLISHER_EN.search(filename)
    if not m:
        return None
    token = m.group(1)
    return FILENAME_PUBLISHER.get(token) or _FILENAME_PUBLISHER_CI.get(token.lower())


def find_opinion(body: str) -> str:
    """목표주가 앵커 ±400자 안에서 앵커에 **가장 가까운** 등급을 쓴다.

    같은 리포트를 네이버로도 가진 40건으로 채점해 100% 다. 두 가지가 필요했다.

    부록 컷오프. 본문 전체를 뒤지면 끝의 '투자의견 비율' 공시와 '변동추이' 표에 걸린다.
    ISC 리포트는 본문에 현재 의견이 없고 그 표에만 Buy 가 있다(정답은 '없음').

    최근접 선택. 등급은 목표주가 바로 앞에 붙는다("BUY (유지)목표주가(12M) 540,000원").
    앞에서부터 찾으면 400자 앞의 다른 단어를 먼저 집는다.

    못 찾으면 '없음'이 정답이다 — 의견을 안 내는 리포트가 실제로 있다(전략·경제 자료).
    """
    cut = _APPENDIX.search(body)
    body = body[: cut.start()] if cut else body
    for anchor in _GOAL_ANCHOR.finditer(body):
        start = max(0, anchor.start() - 400)
        window = body[start : anchor.start() + 400]
        if _OPINION_RATIO.search(window):
            continue
        found = [
            (abs((start + m.start()) - anchor.start()), m.group(1))
            for m in _OPINION.finditer(window)
        ]
        if found:
            return normalize_opinion(min(found)[1])
    return "없음"


def _to_won(token: str) -> int | None:
    """'340,000' 또는 '14만' 을 원 단위 정수로."""
    token = token.strip()
    try:
        if token.endswith("만"):
            return int(token[:-1].strip().replace(",", "")) * 10_000
        return int(token.replace(",", ""))
    except ValueError:
        return None


def find_goal_price(body: str) -> int | None:
    """부록 앞 6,000자에서 찾는다. 네이버 목표주가를 정답으로 40건 채점해 100% 다."""
    cut = _APPENDIX.search(body)
    segment = (body[: cut.start()] if cut else body)[:6000]

    m = _GOAL_CHANGE.search(segment)  # 'A에서 B로 조정' 은 B 가 답이다. 먼저 본다
    if m:
        value = _to_won(m.group(1))
        if value and 1_000 <= value <= 100_000_000:
            return value

    for m in _GOAL_PRICE.finditer(segment):
        won, man = m.group(1), m.group(2)
        value_start = m.start(2) if man else m.start(1)
        if _GOAL_VALUE_BARRIER.search(segment[m.start() : value_start]):
            continue
        value = int(man) * 10_000 if man else _to_won(won or "")
        if value and 1_000 <= value <= 100_000_000:
            return value
    return None


def is_ai_generated(body: str) -> bool:
    """한국IR협의회가 AI 로 만든 자료면 True. 수집에서 뺀다.

    네이버는 제목의 '[AI] ' 로 거르는데 재배포 파일명에는 그게 안 남는다.
    본문의 생성 고지로 잡으면 파일명이 어떻게 바뀌어도 걸린다.
    """
    return bool(_AI_DECLARED.search((body or "")[:1500]))


def exclusion_reason(filename: str, body: str) -> str | None:
    """수집 제외 출처는 파일명 토큰/표지로 식별한다. 본문의 단순 인용은 제외하지 않는다."""
    excluded_filename = re.search(r"(?:^|_)konnect(?:_|\.pdf$)", filename, re.IGNORECASE)
    excluded_cover = re.match(r"\s*기업\s*리서치\s*@\s*KONNECT", body, re.IGNORECASE)
    if excluded_filename or excluded_cover:
        return "수집 제외 출처: R-Advisory/KONNECT"
    if is_ai_generated(body):
        return "AI 생성 자료"
    return None


def classify(filename: str, body: str) -> tuple[str, str | None]:
    """(종류, 종목코드). 종류는 'company' | 'industry' | None.

        파일명에 ［코드］            종목분석 규격이다     → 코드를 넣는다
        본문에 서로 다른 코드 1개    단일 종목이다        → 넣는다
        본문에 코드 여러 개          산업·전략 리포트다   → 코드를 비운다
        코드 없음                   경제·시황·IR        → 둘 다 비운다

    창을 넓히는 문제가 아니다. 본문 전체를 뒤지면 채움률이 44% → 56% 로 오르는데
    **새로 잡힌 8건이 전부 산업 리포트였다.** 종목 9개짜리 방산 리포트에서 맨 앞
    012450(한화에어로스페이스)을 넣으면, 그 종목의 리포트를 찾을 때 업종 리포트가
    종목 리포트인 척 끼어든다. 그래서 창 크기가 아니라 코드 **개수**로 가른다.
    """
    m = _FN_CODE.search(filename or "")
    if m:
        return "company", next(g for g in m.groups() if g)
    found = set(_BODY_CODE.findall(body or ""))
    if len(found) == 1:
        return "company", next(iter(found))
    return ("industry", None) if found else (None, None)


def find_category(title: str, filename: str, body: str) -> str:
    """리포트 **종류**. 출처가 아니다 — 출처는 source 가 말한다.

    네이버가 카테고리를 주는 자리에 텔레그램은 아무것도 안 준다. 두 신호로 채운다.

    제목 접두사. 재배포 채널이 '기업_' '산업_' '경제_' 를 붙인다. 출처가 붙인
    라벨이라 제일 세다. 이걸 안 쓰고 판정에 맡겼더니 '산업_은행…' 을 economy 로,
    '기업_LG에너지솔루션' 을 market 으로 보냈다. 본문에 종목코드가 없어서
    구조 신호가 안 잡히는 건들이다.

    종목코드 개수. 1개면 company, 여러 개면 industry로 추정한다.
    비교기업을 함께 싣는 기업 자료나 코드가 없는 IR에서는 오분류할 수 있다.

    둘 다 없으면 market 으로 둔다. 경제분석과 시황·투자전략은 본문을 읽어야 갈리는데
    규칙으로는 안 된다. 302건을 LLM 으로 채운 결과와 대조하면 12건(4%)이 여기서
    economy 여야 하는데 market 으로 떨어진다.

        미국 8월 CPI; 이게 다 트럼프 때문이다_260914
        엔화 급강세 & 엔캐리 청산 우려_260907
        부채 전쟁(Debt War)_Bond_20260908_NH_1129589

    키워드 규칙을 지어내면 더 나빠진다. 네이버 229건으로 채점했을 때 규칙 62% 대
    LLM 69% 였고, 틀린 쪽을 보면 같은 'Weekly' 가 증권사에 따라 다르게 분류돼 있었다.
    제목·본문으로 복원이 안 되는 구분이다. LLM 판정은 별도 단계로 뺀다.
    """
    m = _TITLE_PREFIX.match(title or "")
    if m:
        return _TITLE_KIND[m.group(1)]
    kind, _ = classify(filename, body)
    return kind or "market"


def content_chars(body: str) -> int:
    """워터마크·저작권 문구를 걷고, 한글이 들어간 줄만 남겨 센다."""
    text = _BOILERPLATE.sub(" ", body or "")
    kept = [line for line in text.split("\n") if re.search(r"[가-힣]{2,}", line)]
    return len(re.sub(r"\s+", "", " ".join(kept)))


def has_usable_body(body: str) -> bool:
    """body_chars 가 커도 내용이 없을 수 있다. 워터마크만 뽑힌 PDF 가 302건 중 7건이다."""
    return content_chars(body) >= MIN_CONTENT_CHARS


def _explicit_sector_rating(head: str, match: re.Match) -> bool:
    """본문의 긍정적 영향·매출 비중 확대와 실제 업종 등급을 구분한다."""
    before, after = head[:match.start()], head[match.end():]
    if _SECTOR_RATING_LABEL.search(before[-40:]):
        return True
    if re.match(
        r"\s*(?:[\"'’”]\s*)?(?:의견|등급|(?:을|를)?\s*(?:유지|유효)"
        r"|[/／]\s*유지|[(（]\s*(?:유지|Maintain)\s*[)）])", after, re.IGNORECASE,
    ):
        return True
    # Overweight/Underweight는 등급 전용 어휘다. PDF 표지에서 줄바꿈이 사라져
    # 'OverweightTop Picks', '조선OverweightData Center'가 되어도 보존한다.
    if (
        match.group(1).lower() in ("overweight", "underweight")
        and not re.search(r"[A-Za-z]$", before) and not re.match(r"[a-z]", after)
    ):
        return True
    # 보고서 표지의 '반도체 (중립)'은 등급이다. 부록의 'Hold(중립) 3.3%'는 아니다.
    if re.search(r"[(（\[]\s*$", before) and re.match(r"\s*[)）\]]", after):
        return not (
            re.search(r"(?:Hold|보유)\s*[(（\[]\s*$", before, re.IGNORECASE)
            or re.match(r"\s*[)）\]]\s*[\d.]+\s*%", after)
        )
    # 영문/한글 등급만 단독 행에 있는 표기도 보존한다.
    return not before.rsplit("\n", 1)[-1].strip() and not after.split("\n", 1)[0].strip()


def find_sector_view(body: str) -> tuple[str | None, list[str]]:
    """산업 리포트의 업종의견과 Top picks. 본문 **앞 절반**만 본다.

    뒤쪽에는 모든 리포트에 붙는 컴플라이언스 부록이 있어서 전체를 뒤지면 과거 의견이
    걸린다. 한 리포트에서 '목표주가' 가 39번 나오는데 36번이 부록이었다.
    """
    if not body:
        return None, []
    head = body[: min(len(body) // 2, 8000)]

    opinion = None
    for m in _SECTOR.finditer(head):
        # 같은 등급 분포표의 Hold(중립), Sell(비중축소)를 의견으로 선택하지 않는다.
        if re.search(r"(?:Hold|Sell|Buy)\s*[(（]\s*$", head[:m.start()], re.IGNORECASE):
            continue
        s = m.group(1).lower().replace(" ", "")
        if not _explicit_sector_rating(head, m):
            continue
        opinion = (
            "비중확대" if s in ("overweight", "비중확대", "positive", "긍정적")
            else "중립" if s in ("neutral", "중립")
            else "비중축소" if s in ("underweight", "비중축소", "negative", "부정적")
            else None
        )
        break

    picks: list[str] = []
    m = _TOP_PICK.search(head)
    if m:
        # 종목 나열이 끝나고 서술어가 시작되는 지점에서 끊는다.
        # "…한국금융지주를 유지하며" 처럼 마지막 종목에 서술어가 붙어 들어온다.
        raw = re.split(r"\s{2,}|차선호|관심종목|제시|유지|추천|선호|이다|입니다", m.group(1))[0]
        for token in _PICK_SPLIT.split(raw):
            name = token.strip(" ‘’'\"()[]·:")
            while True:  # "로 기존 KB금융" 처럼 앞머리가 겹쳐 붙는다
                stripped = _PICK_LEAD.sub("", name).strip()
                if stripped == name:
                    break
                name = stripped
            name = _PICK_TAIL.sub("", name).strip()
            # 상장사 이름에는 공백이 없다(삼성SDI·LG에너지솔루션·한화에어로스페이스).
            # 공백이 있으면 "단기 실적 모멘텀" 같은 문장 조각이다.
            if (
                2 <= len(name) <= 14
                and " " not in name
                and re.search(r"[가-힣A-Za-z]", name)
                and name.lower() not in _NOT_A_PICK
                and not name.isdigit()
                and not re.search(r"[\]\[]", name)
            ):
                picks.append(name)
    return opinion, picks[:5]


def find_write_date(filename: str, posted_at: datetime) -> date:
    """발행일. 파일명에 날짜가 있으면 그걸 쓰고, 없으면 텔레그램에 올라온 날로 대신한다.

    올린 날은 발행일과 다를 수 있다(장 마감 후 올리거나 며칠 지난 걸 다시 올린다).
    파일명 날짜가 더 정확해서 그쪽을 먼저 본다.
    """
    m = _FN_DATE.search(filename or "")
    if m:
        raw = next(g for g in m.groups() if g)
        try:
            if len(raw) == 8:
                return date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
            return date(2000 + int(raw[:2]), int(raw[2:4]), int(raw[4:]))
        except ValueError:
            pass
    return posted_at.astimezone(KST).date()


def body_status(text: str | None, extracted_status: str) -> str:
    """추출된 글자가 없어도 ok가 되거나 워터마크만으로 성공 처리하지 않는다."""
    if extracted_status not in ("ok", "empty", "unusable"):
        return extracted_status
    if not (text or "").strip():
        return "empty"
    return "ok" if has_usable_body(text or "") else "unusable"


def to_row(
    *,
    channel: str,
    message_id: int,
    filename: str,
    posted_at: datetime,
    pdf: PdfText,
) -> dict[str, Any]:
    """analyst_reports 한 행. 네이버 쪽 _to_row 와 같은 테이블에 들어간다.

    source_category 에 채널명을, source_id 에 메시지 번호를 넣는다. 메시지 번호는
    채널 안에서만 유일해서 채널까지 봐야 한 건이 정해진다. 네이버가 researchId 를
    API 카테고리 안에서만 유일하게 매기는 것과 같은 모양이다.

    목표주가와 투자의견은 **종목 리포트에만** 넣는다. 산업 리포트는 종목이 여러 개라
    그중 하나의 목표주가를 실으면 거짓이 된다. item_code 를 비우는 것과 같은 이유다.
    대신 업종의견과 Top picks 를 넣는다. 네이버 쪽과 맞춘 것이다.
    """
    body = pdf.text or ""
    title = (filename or "").removesuffix(".pdf")[:200]
    kind, item_code = classify(filename, body)
    is_company = kind == "company"
    sector_opinion, top_picks = find_sector_view(body) if not is_company else (None, [])
    return {
        "source": "telegram",
        "source_id": str(message_id),
        "source_category": channel,
        "category": find_category(title, filename, body),
        "item_code": item_code,
        "item_name": None,
        "broker": find_publisher(filename, body),
        "title": title,
        "write_date": find_write_date(filename, posted_at),
        "read_count": None,
        "opinion": find_opinion(body) if body and is_company else None,
        "goal_price": find_goal_price(body) if body and is_company else None,
        # 작성 시점 주가는 뽑지 않는다. 표본에서 34% 밖에 안 맞았다 — KRX 에서 계산한다.
        "price_at_write": None,
        "upside_pct": None,
        "sector_opinion": sector_opinion,
        "top_picks": top_picks or None,
        # 네이버가 주는 확정 요약에 해당하는 게 없다. 본문만 있다.
        "summary_html": None,
        "summary_text": None,
        "summary_chars": None,
        "end_url": f"https://t.me/{channel}/{message_id}",
        "attach_url": None,
        "pdf_sha256": pdf.sha256,
        "pdf_bytes": pdf.size_bytes,
        "pdf_pages": pdf.pages,
        "body_text": pdf.text,
        "body_chars": len(body),
        "body_status": body_status(pdf.text, pdf.status),
        "body_extractor": pdf.extractor,
        "body_error": pdf.error,
        "body_fetched_at": datetime.now(UTC),
    }


# ---------------------------------------------------------------- 텔레그램 접속


def make_client():
    """StringSession 으로 붙는다. 세션 파일을 쓰지 않는 이유는 config.py 주석 참고."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    from app.core.config import settings

    settings.require_telegram()
    return TelegramClient(
        StringSession(settings.telegram_session),
        settings.telegram_api_id,
        settings.telegram_api_hash,
        sequential_updates=True,
    )


def pdf_filename(message: Any) -> str | None:
    """첨부가 PDF 면 파일명, 아니면 None."""
    document = getattr(message, "document", None)
    if document is None:
        return None
    for attribute in getattr(document, "attributes", ()):
        name = getattr(attribute, "file_name", None)
        if name and name.lower().endswith(".pdf"):
            return name
    return None


def parse_channel(spec: str) -> tuple[str, Any]:
    """채널 지정을 (이름, Telethon 이 받는 형태) 로 바꾼다.

        sunstudy1234                          이름으로 연다. 보통은 이걸로 된다
        DOC_POOL=1234567890:1234567890123456789   id 로 열고 이름은 DOC_POOL 로 적는다

    이름으로 여는 게 안 되는 채널이 있다. username 해석(`contacts.resolveUsername`)은
    응답에 **채널 객체**를 담아 오는데, 텔레그램이 최근 만든 채널 종류
    (`Constructor ID 1c32b11c`)를 Telethon 1.45 가 모른다. 현재 고정한 1.45 환경에서 확인한 문제다. `채널id:access_hash` 로 주면 그 해석 단계를 건너뛰고,
    메시지 응답은 정상으로 읽히는 걸 확인했다.

    ⚠️ access_hash 는 **계정마다 다른 값이다.** 내 계정에서 얻은 값이 팀원 계정에서는
       안 통한다. 그래서 소스에 상수로 박지 않고 실행할 때 넘기게 뒀다.

    이름은 `source_category`, 메시지 번호는 `source_id`에 저장한다. access_hash 를
    거기 넣으면 값이 바뀔 때 같은 리포트가 다른 행으로 또 들어간다.
    """
    label, _, peer_spec = spec.partition("=")
    if not peer_spec:
        label, peer_spec = spec, spec
    if ":" not in peer_spec:
        return label, peer_spec

    from telethon.tl.types import InputPeerChannel

    raw_id, _, raw_hash = peer_spec.partition(":")
    if label == peer_spec:  # 이름을 안 줬으면 채널 id 를 이름으로 쓴다
        label = raw_id
    return label, InputPeerChannel(channel_id=int(raw_id), access_hash=int(raw_hash))


async def connect_authorized(client: Any) -> None:
    """배치는 로그인 입력을 기다리지 않는다. 로그인은 별도 준비 명령에서만 한다."""
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("텔레그램 세션이 만료됐거나 로그인되지 않았습니다. "
                           "telegram_setup --login으로 세션을 준비하세요.")


async def check_channels(client: Any, specs: tuple[str, ...]) -> list[tuple[str, Any]]:
    """같은 계정의 채널을 해석하고 PDF 목록 읽기를 확인한다. 가입/DB 쓰기는 하지 않는다."""
    from telethon.errors.common import TypeNotFoundError
    from telethon.tl.types import InputMessagesFilterDocument

    resolved = []
    for spec in specs:
        label, peer = parse_channel(spec)
        try:
            try:
                peer = await client.get_input_entity(peer)
            except (TypeNotFoundError, ValueError):
                # StringSession에는 채널 캐시가 저장되지 않는다. 이 계정의 대화 목록에서
                # InputPeer를 얻으면 다른 사람의 access_hash를 복사할 필요가 없다.
                if not isinstance(peer, str):
                    raise
                found = None
                async for dialog in client.iter_dialogs():
                    if (getattr(dialog.entity, "username", None) or "").lower() == peer.lower():
                        found = dialog.input_entity
                        break
                if found is None:
                    raise ValueError("채널을 찾을 수 없음") from None
                peer = found
            await client.get_messages(peer, limit=1, filter=InputMessagesFilterDocument())
        except Exception as exc:  # noqa: BLE001 — 오류는 집계하되 계정 정보는 출력하지 않는다
            # 예외 원문에는 프로토콜 바이트/access_hash가 포함될 수 있어 타입만 노출한다.
            raise RuntimeError(
                f"{label}: 채널 접근 확인 실패 ({type(exc).__name__}). "
                "해당 계정의 가입·접근 권한과 채널 설정을 확인하세요. "
                "TypeNotFoundError는 Telethon 호환성 문제일 수 있습니다."
            ) from None
        resolved.append((label, peer))
    return resolved


async def iter_pdf_messages(client: Any, channel: Any, since: date):
    """채널을 최신부터 훑어 `since` 이후의 PDF 메시지를 내놓는다.

    (메시지, 파일명) 을 준다. since 보다 옛날 글이 나오면 멈춘다 — 최신순이라
    그 뒤로는 전부 옛날이다.

    **문서가 붙은 메시지만 서버에 요청한다**(InputMessagesFilterDocument).
    전체를 받으면 링크 미리보기(Instant View)가 붙은 뉴스 메시지에서 Telethon 이
    `TypeNotFoundError: Could not find a matching Constructor ID ... 263d7c26` 로 죽는다.
    텔레그램이 추가한 객체를 라이브러리가 모르는 것이라 버전을 올려도 안 고쳐진다
    (1.44 와 1.45 둘 다 같은 자리에서 터졌다). 메시지 하나가 배치 전체를 죽인다.
    어차피 PDF 만 필요하니 서버에서 걸러 받는 게 빠르기도 하다.

    문서 응답도 해석하지 못하면 오류를 올려 부분 수집을 성공으로 표시하지 않는다.
    """
    from telethon.errors.common import TypeNotFoundError
    from telethon.tl.types import InputMessagesFilterDocument

    try:
        async for message in client.iter_messages(
            channel, filter=InputMessagesFilterDocument,
        ):
            if message.date.astimezone(KST).date() < since:
                return
            name = pdf_filename(message)
            if name:
                yield message, name
    except TypeNotFoundError:
        raise RuntimeError(
            "텔레그램 응답을 해석하지 못해 수집을 중단했습니다 (TypeNotFoundError). "
            "부분 수집을 성공으로 처리하지 않습니다."
        ) from None


async def download_pdf(client: Any, message: Any, tmpdir: Path) -> bytes:
    """PDF 를 임시 폴더에 받아 바이트로 읽는다. 파일은 호출부가 지운다."""
    path = tmpdir / "report.pdf"
    await client.download_media(message, file=str(path))
    return path.read_bytes()
