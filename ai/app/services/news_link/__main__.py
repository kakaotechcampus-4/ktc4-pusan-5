"""터미널에서 링크 하나를 열어 눈으로 확인한다. DB 를 쓰지 않는다.

    uv run python -m app.services.news_link https://n.news.naver.com/article/001/000
    uv run python -m app.services.news_link <주소> --paragraphs   # 어느 규칙이 무엇을 지웠는지
    uv run python -m app.services.news_link <주소> --stock 삼성전자  # 이 종목의 원인 문장 (LLM 호출)
    uv run python -m app.services.news_link --rules               # 규칙 목록 (네트워크 없음)

정제 규칙을 손볼 때 이게 있어야 한다. 무엇이 지워졌는지 안 보이면 규칙을 고칠 수가 없다.
문장 선택도 같다. 모델이 고른 문장과 코드가 붙인 앞 문장이 구분돼 보여야, 프롬프트를 고칠지
앞 문장 규칙(selection.py)을 고칠지 안다.
(backend `services/news/__main__.py` 와 같은 자리다.)
"""

import argparse
import asyncio
import unicodedata

import httpx

from app.llm.client import endpoint
from app.services.news_link.clean import DROP_RULES, TRIM_RULES, clean_paragraphs
from app.services.news_link.extract import article_paragraphs, finish
from app.services.news_link.fetch import (
    DEFAULT_MAX_CHARS,
    DEFAULT_SENTENCES,
    DEFAULT_TIMEOUT_SEC,
    HEADERS,
    HTML_TYPES,
    decode_html,
    fetch_link,
)
from app.services.news_link.schema import LinkBody
from app.services.news_link.selection import select_sentences
from app.services.news_link.sentence import first_sentences


def pad(text: str, width: int) -> str:
    """터미널 칸 수를 맞춘다. 한글·전각 문자는 두 칸을 먹어서 f-string 의 `<n` 이 어긋난다."""
    used = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return text + " " * max(width - used, 1)


def show_rules() -> None:
    """규칙 목록.

    칸 이름을 '동작 / 범위' 에서 '지우는 것 / 검사 위치' 로 바꿨다. 앞의 것은
    "머리" 가 지우는 양인지 검사하는 자리인지 읽는 사람마다 달리 읽혔다.
    """
    print("지우는 것   문단 전체 = 그 문단을 통째로 지움 / 앞부분만 = 앞을 떼고 나머지 문장은 남김")
    print("검사 위치   기사 전체 = 어느 위치에서든 검사 / 본문 시작 전 = 첫 문장이 나오기 전까지만 검사")
    print()
    print(pad("규칙", 16) + pad("지우는 것", 12) + pad("검사 위치", 15) + "설명")
    print("-" * 78)
    rows = [(n, "문단 전체", "기사 전체" if s == "any" else "본문 시작 전", w)
            for n, w, s, _p in DROP_RULES]
    rows.append(("title_echo", "문단 전체", "본문 시작 전", "제목을 본문에 한 번 더 실은 것"))
    rows.append(("subhead", "문단 전체", "본문 시작 전", "종결부호 없는 짧은 줄 = 제목·부제"))
    rows += [(n, "앞부분만", "기사 전체", w) for n, w, _p in TRIM_RULES]
    for name, what, where, why in rows:
        print(pad(name, 16) + pad(what, 12) + pad(where, 15) + why)


async def show_paragraphs(url: str, sentences: int, max_chars: int) -> None:
    """정제 전 문단을 문단마다 보여준다. 어느 규칙이 걸렸는지 눈으로 본다."""
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SEC, headers=HEADERS) as client:
        response = await client.get(url, follow_redirects=True)

    print(f"=== {response.url}")
    # 여기서 안 막으면 401 페이지·PDF 를 파싱해놓고 "문단을 못 찾았다" 고 말한다.
    # 정제 규칙 탓이 아닌데 규칙을 고치러 가게 된다.
    raw_content_type = response.headers.get("content-type") or ""
    if response.status_code != 200:
        print(f"HTTP {response.status_code} — 기사 페이지가 아닙니다. 정제 규칙과 무관합니다.")
        return
    if raw_content_type.split(";")[0].strip().lower() not in HTML_TYPES:
        print(f"HTML 이 아닙니다 ({raw_content_type}). 정제 규칙과 무관합니다.")
        return

    html_text = decode_html(response.content, raw_content_type)
    title, paragraphs, min_paras = article_paragraphs(html_text)

    print(f"제목: {title}\n")
    if not paragraphs:
        print("본문 문단을 찾지 못했습니다. extract.py 의 ARTICLE_SELECTORS 를 확인하세요.")
        return
    kept, log = clean_paragraphs(paragraphs, title)
    # 규칙 두 종류를 갈라서 본다. 앞머리 규칙은 log 에 **지운 앞머리**가 남고,
    # 버리는 규칙은 **문단 전체**가 남는다. 섞어 놓으면 어느 쪽인지 알 수 없다.
    trim_names = {name for name, _why, _p in TRIM_RULES}
    dropped = {what: name for name, what in log if name not in trim_names}
    trims = [(what, name) for name, what in log if name in trim_names]
    for i, paragraph in enumerate(paragraphs[:14], 1):
        mark = dropped.get(paragraph)
        if mark:
            print(f"  {i:>2} − [{mark}] {paragraph[:100]}")
            continue
        # 지운 앞머리로 되짚는다. 남은 문단들 중에서 endswith 로 찾으면
        # 다른 문단이 우연히 접미사일 때 엉뚱한 것을 짚는다.
        hit = next(((what, name) for what, name in trims if paragraph.startswith(what)), None)
        if hit:
            head, name = hit
            print(f"  {i:>2} ✂ [{name}] {head}")
            print(f"       ✓ {paragraph[len(head) :].strip()[:96]}")
        else:
            print(f"  {i:>2} ✓ {paragraph[:100]}")

    body = finish(title, paragraphs, min_paras)
    print(f"\n정제 후 앞 {sentences}문장 ({len(paragraphs)}문단 → {len(kept)}문단):")
    excerpt = first_sentences(body, sentences, max_chars) if body else ""
    print("  " + (excerpt.replace("\n", "\n  ") if excerpt else "(남는 본문이 없습니다)"))


async def show_link(url: str, sentences: int, max_chars: int, stocks: list[str]) -> None:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SEC, headers=HEADERS) as client:
        body = await fetch_link(client, url, sentences=sentences, max_chars=max_chars)
    print(f"status   {body.status}{f' ({body.error})' if body.error else ''}")
    print(f"도메인   {body.domain}")
    print(f"최종주소 {body.final_url}")
    print(f"제목     {body.title}")
    whole = f" (본문 {len(body.sentences)}문장 중 앞부분)" if body.sentences else ""
    print(f"발췌     {body.chars}자{whole}")
    if body.excerpt:
        print("  " + body.excerpt.replace("\n", "\n  "))
    for stock in stocks:
        await show_selection(stock, body)


async def show_selection(stock: str, body: LinkBody) -> None:
    """종목 하나로 문장 선택을 돌려 결과를 찍는다.

    코드가 붙인 앞 문장에는 "(앞 문장)" 을 달아 모델이 고른 문장과 구분한다.
    """
    picked = await select_sentences(stock, body)
    usage = picked.usage
    tokens = (f" · 입력 {usage.get('prompt_tokens', 0)} / 출력 {usage.get('completion_tokens', 0)} 토큰"
              if usage else "")
    print(f"\n[{stock}] {picked.status}{tokens}")
    if picked.status == "selected":
        for i in picked.indices:
            mark = "" if i in picked.model_indices else "(앞 문장) "
            print(f"  [{i:>2}] {mark}{body.sentences[i - 1]}")
    elif picked.status in ("fallback", "error"):
        reason = picked.error or f"응답이 규칙을 어김: {picked.raw[:80]!r}"
        print(f"  앞 {len(picked.indices)}문장으로 대체 ({reason})")
    elif picked.status == "none":
        print("  이 기사는 이 종목을 다루지 않는다고 판단했습니다")
    else:
        print("  고를 본문이 없습니다")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?")
    parser.add_argument("--sentences", type=int, default=DEFAULT_SENTENCES)
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--paragraphs", action="store_true", help="문단마다 걸린 규칙을 보여준다")
    parser.add_argument("--stock", action="append", default=[],
                        help="이 종목의 원인 문장을 골라 본다 (LLM 호출). 여러 번 줄 수 있다")
    parser.add_argument("--rules", action="store_true", help="규칙 목록 (네트워크 없음)")
    args = parser.parse_args()

    if args.rules:
        show_rules()
        return
    if not args.url:
        parser.error("url 을 주거나 --rules 를 쓰세요")
    if args.paragraphs and args.stock:
        parser.error("--stock 은 --paragraphs 없이 쓰세요")
    if args.stock:
        try:
            endpoint()  # 키·주소가 빠졌으면 링크를 열기 전에 멈춘다
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from None
    if args.paragraphs:
        asyncio.run(show_paragraphs(args.url, args.sentences, args.max_chars))
    else:
        asyncio.run(show_link(args.url, args.sentences, args.max_chars, args.stock))


if __name__ == "__main__":
    main()
