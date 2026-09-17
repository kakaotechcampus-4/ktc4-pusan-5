"""네이버 증권 리서치 어댑터.

    목록  GET m.stock.naver.com/api/research/{category}?page=1&pageSize=100
    상세  GET m.stock.naver.com/api/research/{category}/{researchId}
    원문  GET stock.pstatic.net/stock-research/.../*.pdf

인증이 없다. 확인한 것(2026-09-14 실측):
    - 카테고리 5종. `daily` 와 `market` 은 researchId 까지 같은 동일 데이터라 daily 만 받는다.
    - 상세 채움률(n=20): attachUrl·content·opinion 20/20, goalPrice 14/20.
    - 요약(content)은 HTML 이고 태그를 걷으면 평균 517자.
    - pageSize=100 까지 먹고 page=3000 이 2016년까지 간다. 백필 깊이는 제한이 아니다.
    - 종목코드·투자의견·목표주가는 `company` 에만 있다. 나머지는 제목과 PDF 뿐이다.

네이버가 싣는 증권사는 21곳뿐이다. 삼성·NH 는 0건, 한국투자는 2건이었다(3주 실측).
대형사 리포트는 여기 안 들어온다 — 다른 경로로 따로 받아야 한다.

## 왜 여기만 클래스인가

backend 의 `services/news/naver.py` 나 `dart_client.py` 는 모듈 함수이고 httpx 를
호출마다 새로 연다. 호출이 한 번이라 그래도 된다. 여기는 다르다 —
카테고리 5개 × 목록 페이지 + **건당 상세 1회 + PDF 1회**라, 일주일치 500건이면
HTTP 호출이 1,000회를 넘는다. 매번 AsyncClient 를 새로 열면 TCP 연결과 TLS
핸드셰이크를 그만큼 반복한다. 커넥션을 재사용하려고 클래스로 뒀다.
"""

import asyncio
import html
import logging
import re
from datetime import UTC, date, datetime
from typing import Any, Self

import httpx

from app.core.config import settings
from app.services.analyst.pdf import pdf_text_from_bytes
from app.services.analyst.schema import AnalystReportItem, PdfText

logger = logging.getLogger(__name__)

BASE_URL = "https://m.stock.naver.com/api/research"
CATEGORIES = ("company", "industry", "economy", "invest", "daily")

# 네이버 웹에서 오는 요청처럼 보이게 한다. 없으면 차단되는 경로가 있다.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Referer": "https://m.stock.naver.com/research",
}


class NaverResearchError(Exception):
    """네이버 리서치 호출 실패. 원인 예외는 __cause__ 에 남는다."""


# ---------------------------------------------------------------- 파싱 유틸

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t ]+")


def strip_html(raw: str | None) -> str | None:
    """네이버 요약은 <p><br><strong> 이 섞인 HTML 이다. 줄바꿈은 살리고 태그만 걷는다."""
    if not raw:
        return None
    text = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    text = _WS.sub(" ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or None


def to_int(raw: Any) -> int | None:
    """네이버는 숫자를 문자열로 준다. 빈 값·콤마·'-' 가 섞여 온다."""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "")
    if s in ("", "-", "0"):
        return None if s in ("", "-") else 0
    try:
        return int(float(s))
    except ValueError:
        return None


# 한국IR협의회가 AI 로 생성해 올리는 기업소개 자료. 제목이 "[AI] " 로 시작한다.
# 받지 않는다 — 애널리스트 리포트가 아니고, 실제로 데이터가 틀려 있다.
#   아이디스홀딩스(054800) 제목 = "[AI] 풍력 터빈용 피치·요 베어링 제조기업"
#   씨에스베어링(297090)   제목 = "[AI] 풍력 터빈용 피치·요 베어링 제조기업"  ← 같은 제목
#   에르코스(435570)       제목 = "[AI] 영상보안·모니터·프린터 지주회사"     ← 앞 종목 것
# 요약 본문은 종목과 맞는데 제목만 한 칸씩 밀려 있다. 네이버 API 원본이 그렇다(직접 확인).
# 투자의견·목표주가도 전부 비어 있어서 우리가 쓸 값이 없다.
_AI_TITLE = re.compile(r"^\s*\[\s*AI\s*\]")


def is_ai_generated(item: AnalystReportItem) -> bool:
    return bool(_AI_TITLE.match(item.title or ""))


# ------------------------------------------------ 산업 리포트: 업종의견 + Top picks
#
# 산업 리포트는 종목이 아니라 업종에 의견을 낸다. 네이버가 이 값을 안 주므로 PDF 에서 뽑는다.
# **본문 앞 절반만 본다** — 뒤쪽에는 모든 리포트에 붙는 컴플라이언스 부록("투자의견 비율",
# "투자의견 변동 내역 및 목표주가 괴리율")이 있고 거기엔 과거 의견이 잔뜩 적혀 있다.
# 실측: 한 리포트에서 "목표주가" 39회 중 36회가 부록이었다.
_SECTOR_OP = re.compile(
    r"(Overweight|OVERWEIGHT|비중\s?확대|Neutral|NEUTRAL|중\s?립"
    r"|Underweight|UNDERWEIGHT|비중\s?축소|Positive|긍정적|Negative|부정적)"
)
_TOPPICK = re.compile(
    r"(?:Top[\s\-]?picks?|탑\s?픽|최선호주|최선호\s?종목)\s*[:：]?\s*([^\n]{2,80})", re.IGNORECASE
)
_PICK_SPLIT = re.compile(r"[,·/]| 및 |과 |와 ")
# Top pick 자리에 딸려 들어오는 말들. 종목명이 아니다.
_NOT_A_PICK = {
    "유지", "및", "관심종목", "차선호주", "제시", "상향", "하향", "기타",
    "자동차", "2차전지", "top", "picks", "pick",
}


def _norm_sector(s: str) -> str:
    s = s.lower().replace(" ", "")
    if s in ("overweight", "비중확대", "positive", "긍정적"):
        return "비중확대"
    if s in ("neutral", "중립"):
        return "중립"
    if s in ("underweight", "비중축소", "negative", "부정적"):
        return "비중축소"
    return s


def extract_sector_view(body: str | None) -> tuple[str | None, list[str]]:
    """(업종의견, Top picks). 못 찾으면 (None, [])."""
    if not body:
        return None, []
    head = body[: min(len(body) // 2, 8000)]

    m = _SECTOR_OP.search(head)
    opinion = _norm_sector(m.group(1)) if m else None

    picks: list[str] = []
    m = _TOPPICK.search(head)
    if m:
        # 차선호주·관심종목은 Top pick 이 아니다. 거기서 끊는다.
        raw = re.split(r"\s{2,}|차선호|관심종목|제시|이다|입니다", m.group(1))[0]
        for tok in _PICK_SPLIT.split(raw):
            t = tok.strip(" ‘’'\"()[]·:")
            if (
                2 <= len(t) <= 14
                and re.search(r"[가-힣A-Za-z]", t)
                and t.lower() not in _NOT_A_PICK
                and not t.isdigit()
                and not re.search(r"[\]\[]", t)
            ):
                picks.append(t)
    return opinion, picks[:5]


def parse_list_row(category: str, row: dict[str, Any]) -> AnalystReportItem:
    return AnalystReportItem(
        source_id=str(row["researchId"]),
        category=category,
        title=(row.get("title") or "").strip(),
        broker=(row.get("brokerName") or "").strip(),
        write_date=date.fromisoformat(row["writeDate"]),
        item_code=row.get("itemCode") or None,
        item_name=row.get("itemName") or None,
        read_count=to_int(row.get("readCount")),
        end_url=row.get("endUrl"),
        raw=row,
    )


def merge_detail(item: AnalystReportItem, detail: dict[str, Any]) -> AnalystReportItem:
    """상세 응답을 목록 행에 덮어쓴다. 상세에만 있는 게 요약·목표주가·PDF 링크다."""
    content = detail.get("content")
    item.attach_url = detail.get("attachUrl") or None
    item.summary_html = content or None
    item.summary_text = strip_html(content)
    item.opinion = (detail.get("opinion") or "").strip() or None
    item.goal_price = to_int(detail.get("goalPrice"))
    # detail["prevGoalPrice"] 는 직전 목표주가가 아니라 현재가의 중복이다(모델 주석 참고).
    item.price_at_write = to_int(detail.get("priceAtWriteDate"))
    item.item_code = item.item_code or detail.get("itemCode") or None
    item.item_name = item.item_name or detail.get("itemName") or None
    item.raw = {"list": item.raw, "detail": detail}
    return item


def utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------- 클라이언트


class NaverResearchClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._own = client is None
        self._client = client or httpx.AsyncClient(
            timeout=settings.http_timeout_sec, headers=HEADERS, follow_redirects=True
        )

    async def aclose(self) -> None:
        if self._own:
            await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def fetch_list(
        self, category: str, page: int = 1, page_size: int = 100
    ) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
        """(행들, 호출 파라미터, HTTP 상태)."""
        params = {"page": page, "pageSize": page_size}
        try:
            r = await self._client.get(f"{BASE_URL}/{category}", params=params)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise NaverResearchError(f"목록 실패 {category} p{page}") from exc
        rows = r.json()
        return (rows if isinstance(rows, list) else []), params, r.status_code

    async def fetch_detail(self, category: str, research_id: str) -> dict[str, Any]:
        try:
            r = await self._client.get(f"{BASE_URL}/{category}/{research_id}")
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise NaverResearchError(f"상세 실패 {category}/{research_id}") from exc
        return r.json().get("researchContent") or {}

    async def fetch_pdf_text(self, url: str | None) -> PdfText:
        """attachUrl 로 PDF 를 받아 텍스트만 남긴다. 판정은 pdf.py 가 한다."""
        if not url:
            return PdfText(status="skipped", error="첨부 없음")
        try:
            r = await self._client.get(url)
            r.raise_for_status()
            blob = r.content
        # 일부러 전부 잡는다. PDF 하나가 500건짜리 배치를 죽이면 안 된다.
        # 사유는 body_error 로 DB 에 남으니 나중에 그 행만 다시 돌리면 된다.
        except Exception as exc:  # noqa: BLE001 — 네트워크·404·타임아웃·인코딩 등
            return PdfText(status="failed", error=f"{type(exc).__name__}: {exc}"[:500])
        # 동기 함수라 별도 스레드에서 돌린다. 안 그러면 이벤트 루프가 멈춘다.
        return await asyncio.to_thread(pdf_text_from_bytes, blob)

    async def collect_since(
        self,
        category: str,
        since: date,
        *,
        page_size: int = 100,
        max_pages: int = 20,
        known_ids: set[str] | None = None,
    ) -> list[AnalystReportItem]:
        """`since` 이후 목록을 모은다.

        최신순이라 write_date 가 since 보다 옛날이 되는 순간 멈춘다.
        `known_ids` 를 주면 이미 있는 건 상세를 안 부른다 — 증분 수집의 핵심이다.
        """
        items: list[AnalystReportItem] = []
        known = known_ids or set()

        for page in range(1, max_pages + 1):
            rows, _params, _status = await self.fetch_list(category, page, page_size)
            if not rows:
                break
            for row in rows:
                try:
                    item = parse_list_row(category, row)
                except (KeyError, ValueError) as exc:
                    logger.warning("목록 행 파싱 실패: %s (%s)", exc, row)
                    continue
                if item.write_date < since:
                    continue
                if item.source_id in known:
                    continue
                if is_ai_generated(item):
                    logger.debug("AI 생성 자료 제외: %s %s", item.broker, item.title)
                    continue
                items.append(item)
            if date.fromisoformat(rows[-1]["writeDate"]) < since:
                break
            await asyncio.sleep(0.2)  # 남의 서버다. 목록 호출 사이는 쉬어 간다.

        return items

    async def enrich(
        self, items: list[AnalystReportItem], *, with_pdf: bool = True, delay: float = 0.3
    ) -> list[tuple[AnalystReportItem, PdfText | None]]:
        """상세 + PDF 본문을 채운다. 항목당 2회 호출이라 반드시 간격을 둔다."""
        out: list[tuple[AnalystReportItem, PdfText | None]] = []
        for item in items:
            try:
                detail = await self.fetch_detail(item.category, item.source_id)
                merge_detail(item, detail)
            except NaverResearchError as exc:
                logger.warning("%s — 이 건은 건너뛴다", exc)
                out.append((item, None))
                await asyncio.sleep(delay)
                continue

            pdf = await self.fetch_pdf_text(item.attach_url) if with_pdf else None
            if item.category == "industry" and pdf and pdf.text:
                item.sector_opinion, item.top_picks = extract_sector_view(pdf.text)
            out.append((item, pdf))
            await asyncio.sleep(delay)
        return out
