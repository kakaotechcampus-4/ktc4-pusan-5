"""기사 HTML → (제목, 정제된 본문).

**문단 단위로 모은다.** 기사 영역을 통째로 get_text 하면 바이라인·음성재생 UI
문구·공유 버튼 텍스트가 앞에 붙어서 첫 문장이 그 쓰레기가 된다.

`article_paragraphs` 와 `extract_body` 를 나눠 둔 것은 **정제 전 문단**을 봐야 하는
쪽이 있기 때문이다. 정제된 결과만 돌려주면 "무엇이 지워졌는지" 를 보여줄 수가 없고,
그게 안 보이면 clean.py 의 규칙을 손볼 수 없다.

backend 는 같은 일을 trafilatura 로 한다. 여기서 bs4 를 쓰는 것은 기사 영역
선택자를 우리가 직접 쥐고 있어야 하기 때문이다 — 텔레그램에 올라오는 링크는 국내
매체·증권사 블로그·외신이 섞여서, 실패하면 어느 선택자를 고쳐야 하는지 보여야 한다.
"""

import re

from bs4 import BeautifulSoup

from app.services.news_link.clean import clean_paragraphs

ARTICLE_SELECTORS = [
    "#dic_area", "#newsct_article",  # 네이버 뉴스
    "div.se-main-container",  # 네이버 블로그 (스마트에디터)
    "#articleBodyContents", "div#harmonyContainer",
    "[itemprop=articleBody]", "div.article-body", "div.article_body",
    "div.news_end", "#CmAdContent", "div.paragraph",  # YTN
    "article",
]
PARA_SELECTORS = "p, div.se-text-paragraph"

# 문단으로 셀 만큼 긴가. **내용 판단은 여기서 하지 않는다.** 광고·저작권·바이라인
# 같은 "기사가 아닌 것" 은 clean.py 가 전담한다. 두 군데서 나눠 판단하면 규칙이
# 갈라져, 어느 쪽을 고쳐야 하는지 모르게 된다.
MIN_PARA_CHARS = 25


def _squash(text: str) -> str:
    return re.sub(r"[ \t\xa0]+", " ", text).strip()


def _keep_para(text: str) -> bool:
    return len(text) >= MIN_PARA_CHARS


def _common_ancestor(nodes: list) -> object | None:
    """노드들을 모두 품는 가장 가까운 조상. 하나도 없으면 None."""
    if not nodes:
        return None
    chain = [nodes[0], *nodes[0].parents]
    for node in nodes[1:]:
        other = {id(parent) for parent in [node, *node.parents]}
        chain = [parent for parent in chain if id(parent) in other]
        if not chain:
            return None
    return chain[0]


def article_paragraphs(html_text: str) -> tuple[str, list[str], int]:
    """**정제 전** 문단 목록. (제목, 문단들, 최소문단수) 를 돌려준다."""
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(
        ["script", "style", "nav", "header", "footer", "aside",
         "iframe", "figcaption", "form", "noscript", "button"]
    ):
        tag.decompose()
    for br in soup.find_all("br"):  # <br> 로만 나뉜 본문이 붙어버리지 않게
        br.replace_with("\n")

    title = ""
    og_title = soup.select_one('meta[property="og:title"]')
    if og_title and og_title.get("content"):
        title = og_title["content"]
    elif soup.title and soup.title.string:
        title = soup.title.string
    title = re.sub(r"\s+", " ", title or "").strip()[:120]

    node = None
    for selector in ARTICLE_SELECTORS:
        found = soup.select_one(selector)
        if found and len(found.get_text(" ", strip=True)) > 150:
            node = found
            break

    if node is not None:
        paras = [
            _squash(p.get_text(" ", strip=True))
            for p in node.select(PARA_SELECTORS)
            if not p.find("p")
        ]
        paras = [t for t in paras if _keep_para(t)]
        if not paras:
            # 네이버 뉴스(#dic_area)·TechPowerUp 은 본문을 <p> 없이 <br> 로만
            # 나눈다. 기사 영역이 확실할 때만 쓰는 되돌림이라 잡음이 적다.
            paras = [
                t for t in (_squash(x) for x in node.get_text("\n").split("\n")) if _keep_para(t)
            ]
        return title, paras, 1

    # 아는 기사 영역이 없다. <p> 를 **부모별로 묶어** 두꺼운 덩어리만 쓴다.
    # 페이지 전체에서 <p> 를 긁으면 푸터의 회사 소개가 첫 문장이 된다
    # (counterpointresearch.com 에서 실제로 그랬다).
    groups: dict[int, dict] = {}
    for p in soup.select(PARA_SELECTORS):
        if p.find("p"):
            continue  # 중첩 문단은 안쪽 것만 센다
        text = _squash(p.get_text(" ", strip=True))
        if not _keep_para(text):
            continue
        group = groups.setdefault(id(p.parent), {"node": p.parent, "paras": []})
        group["paras"].append(text)
    if not groups:
        return title, [], 1

    def weight(group: dict) -> int:
        return sum(len(t) for t in group["paras"])

    best = max(groups.values(), key=weight)
    # 한 기사인데 문단이 형제 컨테이너로 쪼개져 있는 AMP 페이지가 있다. 가장 두꺼운
    # 덩어리만 쓰면 리드 문단을 건너뛰고 기사 중간부터 자르게 되는데, "본문 앞 3문장"
    # 이라고 넘긴 것이 실은 중간이면 모델이 잘못 읽는다. 그래서 의미 있는 덩어리들의
    # 공통 조상을 잡아 문서 순서대로 다시 모은다.
    significant = [g["node"] for g in groups.values() if weight(g) >= weight(best) * 0.15]
    ancestor = _common_ancestor(significant)
    if ancestor is not None and ancestor.name not in ("body", "html", "[document]"):
        merged = [
            _squash(p.get_text(" ", strip=True))
            for p in ancestor.select(PARA_SELECTORS)
            if not p.find("p")
        ]
        merged = [t for t in merged if _keep_para(t)]
        # 조상이 너무 넓으면(관련기사·추천글까지 들어오면) 되돌린다
        if merged and sum(len(t) for t in merged) <= weight(best) * 3:
            return title, merged, 2
    return title, best["paras"], 2


def finish(title: str, paragraphs: list[str], min_paras: int = 1) -> str:
    """문단을 정제해 본문 문자열로 만든다. 모든 경로가 여기로 나간다.

    min_paras=2 는 되돌림 경로에서만 쓴다. 기사 영역을 못 찾아 페이지 전체에서
    <p> 를 주운 상황이라, 문단 하나는 본문이 아니라 회사 소개일 확률이 높다.
    없는 것이 틀린 것보다 낫다 — 모델은 발췌를 기사 서두로 읽는다.
    """
    kept, _log = clean_paragraphs(paragraphs, title)
    return "\n".join(kept) if len(kept) >= min_paras else ""


def extract_body(html_text: str) -> tuple[str, str]:
    """기사 HTML 에서 (제목, 정제된 본문) 을 뽑는다. 못 찾으면 본문은 빈 문자열."""
    title, paragraphs, min_paras = article_paragraphs(html_text)
    return title, finish(title, paragraphs, min_paras)
