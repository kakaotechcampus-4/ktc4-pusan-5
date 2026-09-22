"""뉴스 링크를 열어 본문 앞부분을 가져온다.

텔레그램 메시지는 "제목 + 단축 URL" 만 있고 내용이 링크 안에 있는 경우가 많다.
프로토타입 실측으로 메시지 129건에 링크 176개였고 그중 **123개가 단축 URL**
(buly.kr 87 / tinyurl 21 / vo.la 15)이었다. 모델은 `buly.kr/xxx` 를 열 수 없고
도메인조차 못 봐서, 그대로 프롬프트에 실으면 토큰만 먹는다.

여기서 딱 두 가지만 한다.

    (1) 단축 URL 을 따라가 **최종 주소와 도메인**을 알아낸다. 본문을 못 읽는 PDF 라도
        "buly.kr" 이 "file.hanaw.com" 이 되면 모델이 출처는 알아본다.
    (2) 본문 앞 몇 문장을 **잘라낸다.** 요약하지 않는다 (clean.py 참고).

**LLM 이 부르는 tool 이 아니다.** 에이전트가 링크를 만날 때마다 tool 을 부르면
호출마다 컨텍스트가 통째로 다시 올라간다. 프로토타입에서 그렇게 돌렸더니 런당
tool 호출 8~11회에 2분·$0.72 였다. 수집할 때 코드로 미리 열어두면 LLM 호출이 0 이다.

실패해도 예외를 올리지 않는다. 링크 하나 때문에 수집이 멈추면 사이트 한 곳이 죽은 날
그날치를 통째로 못 모은다. 실패는 `LinkBody.status` 에 남긴다.
(backend `services/news/content.py` 와 같은 태도다.)

2026-09-18 프로토타입 실측(링크 56건): 본문 확보 15 / PDF 16 / 본문 못 찾음 16 / 401·403 8.
절반이 안 열리지만 안 열려도 최종 도메인은 남는다.
"""

import asyncio
import logging
import re
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from app.services.news_link.extract import extract_body
from app.services.news_link.schema import LinkBody
from app.services.news_link.sentence import first_sentences

logger = logging.getLogger(__name__)

# 브라우저처럼 보이게 한다. 국내 매체 일부는 낯선 UA 를 막는다.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "ko,en;q=0.8"}

DEFAULT_SENTENCES = 3
DEFAULT_MAX_CHARS = 400
# 남의 서버다. 한 번에 많이 두드리지 않는다.
DEFAULT_CONCURRENCY = 5
# PDF(50MB)와 달리 기사 HTML 이 3MB 를 넘으면 기사 페이지가 아니다.
MAX_HTML_BYTES = 3_000_000
# 링크는 건당 1회 호출이라 짧게 잡는다. 안 열리는 사이트를 오래 기다리면
# 그만큼 수집 전체가 늦어진다. PDF 를 받는 analyst 쪽(30초)과 값이 다른 이유다.
DEFAULT_TIMEOUT_SEC = 12.0

HTML_TYPES = ("text/html", "application/xhtml+xml")
_META_CHARSET_RE = re.compile(rb"""charset\s*=\s*["']?\s*([\w\-]+)""", re.IGNORECASE)


def utcnow() -> datetime:
    return datetime.now(UTC)


def is_fetchable(url: str) -> bool:
    """열어볼 만한 주소인가.

    텔레그램은 본문에 적힌 "PLTR.US", "Pony.ai", "1211.HK" 같은 티커 문자열도
    자동으로 링크로 만든다. 실제로 열면 엉뚱한 사이트가 나온다
    (PLTR.US → prayerletters.com). 호스트에 대문자가 있고 경로가 비어 있으면
    사람이 적어 넣은 주소가 아니라고 본다.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    host_has_upper = parsed.netloc != parsed.netloc.lower()
    path_is_bare = parsed.path in ("", "/")
    looks_like_ticker = host_has_upper and path_is_bare
    return not looks_like_ticker


def decode_html(content: bytes, content_type: str) -> str:
    """바이트를 글자로. **국내 매체에는 아직 EUC-KR 이 있다.**

    httpx 는 헤더에 charset 이 없으면 utf-8 로 읽는다(requests 의 apparent_encoding
    같은 추정이 없다). 그대로 두면 EUC-KR 기사가 통째로 깨져서 정제 규칙도 문장
    분리도 전부 헛돈다. 그래서 헤더 → <meta charset> → utf-8 순으로 찾는다.
    """
    encoding = None
    if "charset=" in content_type.lower():
        encoding = content_type.lower().split("charset=")[1].split(";")[0].strip(" \"'")
    if not encoding:
        found = _META_CHARSET_RE.search(content[:4096])
        if found:
            encoding = found.group(1).decode("ascii", "ignore")
    try:
        return content.decode(encoding or "utf-8", errors="replace")
    except LookupError:  # 사이트가 없는 인코딩 이름을 적어두는 경우가 있다
        return content.decode("utf-8", errors="replace")


async def fetch_link(
    client: httpx.AsyncClient,
    url: str,
    *,
    sentences: int = DEFAULT_SENTENCES,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> LinkBody:
    """링크 하나를 연다. 예외를 밖으로 던지지 않는다."""
    body = LinkBody(url=url, fetched_at=utcnow())
    try:
        # 스트림으로 연다. 응답 헤더만 보고 PDF·거대 페이지를 끝까지 받지 않고 끊는다.
        # UA 는 요청마다 준다 — 호출 측이 넘긴 client 가 UA 를 안 달고 있어도
        # 같은 조건으로 열리게 하려는 것이다.
        async with client.stream("GET", url, headers=HEADERS, follow_redirects=True) as response:
            body.final_url = str(response.url)
            body.domain = urlparse(str(response.url)).netloc
            if response.status_code != 200:
                body.status = "http_error"
                body.http_status = response.status_code
                return body

            # 헤더는 한 번만 읽는다. 원본(charset 포함)은 decode_html 이 쓰고,
            # 앞부분만 떼어낸 쪽은 종류 판정에 쓴다.
            raw_content_type = response.headers.get("content-type") or ""
            content_type = raw_content_type.split(";")[0].strip()
            if content_type.lower() not in HTML_TYPES:
                # 증권사 리서치는 대부분 PDF 로 떨어진다. 본문은 못 읽지만 최종
                # 도메인이 남는 것만으로도 단축 URL 보다 낫다. PDF 본문이 필요해지면
                # services/analyst/pdf.py 가 이미 바이트 → 텍스트를 한다.
                body.status = "pdf" if "pdf" in content_type.lower() else "not_html"
                body.content_type = content_type or None
                return body

            length = response.headers.get("content-length")
            if length and length.isdigit() and int(length) > MAX_HTML_BYTES:
                body.status = "too_large"
                return body

            content = await response.aread()
            if len(content) > MAX_HTML_BYTES:  # content-length 를 안 주는 서버가 있다
                body.status = "too_large"
                return body

        html_text = decode_html(content, raw_content_type)
        # bs4 파싱은 CPU 를 오래 쥔다. 다른 링크의 응답을 기다리게 하지 않는다.
        title, article = await asyncio.to_thread(extract_body, html_text)
        body.title = title or None
        if not article:
            body.status = "no_body"
            return body
        excerpt = first_sentences(article, sentences, max_chars)
        body.excerpt = excerpt or None
        body.chars = len(excerpt)
        body.status = "ok" if excerpt else "no_body"
    except Exception as exc:  # noqa: BLE001 — 네트워크·인코딩·파싱 전부. 링크 하나에 수집이 멈추면 안 된다
        body.status = "error"
        body.error = f"{type(exc).__name__}: {str(exc)[:70]}"
        # 본문을 못 읽어도 **어디로 가는 주소인지는 건질 수 있다.** 리다이렉트는
        # 성공하고 목적지에서 응답이 끊기는 경우가 있다(globenewswire 가 그랬다).
        if body.final_url is None:
            request = getattr(exc, "request", None)
            failed_url = str(getattr(request, "url", "") or "")
            if failed_url and failed_url != url:
                body.final_url = failed_url
                body.domain = urlparse(failed_url).netloc
    return body


async def fetch_link_bodies(
    urls: list[str],
    *,
    sentences: int = DEFAULT_SENTENCES,
    max_chars: int = DEFAULT_MAX_CHARS,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    client: httpx.AsyncClient | None = None,
) -> list[LinkBody]:
    """링크 여러 개를 연다. 결과는 준 순서 그대로다.

    열어볼 값어치가 없는 주소(티커 문자열이 링크로 잡힌 것)는 빼고 돌려준다.
    중복 URL 은 한 번만 열고 같은 결과를 나눠 쓴다 — 한 채널에서 같은 기사를
    여러 번 올리는 일이 흔하다.

    `client` 를 받는 것은 호출 측이 커넥션을 재사용하게 하려는 것이다.
    수집기는 수백 개 링크를 연달아 여는데 매번 AsyncClient 를 새로 열면
    TCP·TLS 핸드셰이크를 그만큼 반복한다.

    **`client` 를 주면 `timeout` 은 쓰이지 않는다.** 타임아웃은 AsyncClient 에
    붙는 값이라, 이미 만들어진 client 를 받으면 그쪽 설정이 이긴다. 수집기에서
    타임아웃을 바꾸려면 client 를 만들 때 넣어야 한다.
    """
    targets = [url for url in urls if is_fetchable(url)]
    dropped = len(urls) - len(targets)
    if dropped:
        logger.debug("링크 %d건은 주소가 아니라고 보고 건너뜀", dropped)
    unique = list(dict.fromkeys(targets))
    if not unique:
        return []

    semaphore = asyncio.Semaphore(concurrency)

    async def one(session: httpx.AsyncClient, url: str) -> LinkBody:
        async with semaphore:
            return await fetch_link(session, url, sentences=sentences, max_chars=max_chars)

    if client is not None:
        results = await asyncio.gather(*(one(client, url) for url in unique))
    else:
        async with httpx.AsyncClient(timeout=timeout, headers=HEADERS) as session:
            results = await asyncio.gather(*(one(session, url) for url in unique))

    by_url = dict(zip(unique, results, strict=True))
    return [by_url[url] for url in targets]
