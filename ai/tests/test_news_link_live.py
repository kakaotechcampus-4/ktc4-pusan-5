"""텔레그램 채널이 실제로 올린 뉴스 링크를 진짜로 열어 본다.

**기본 실행에서 빠진다.** 남의 사이트를 실제로 두드리므로 마커를 줘야 돈다.

    uv run pytest -m network -s      # -s 를 줘야 결과가 보인다

## 왜 따로 있나

다른 테스트는 `MockTransport` 로 **우리가 만든 HTML** 을 읽는다. 그건 우리가 아는
모양만 담는다. 실제 매체는 기사 영역 선택자도, 바이라인 형식도, 인코딩도 제각각이라
진짜로 열어봐야 `clean.py` 의 규칙이 통하는지 알 수 있다.

예를 들어 연합뉴스는 `(서울=연합뉴스) OOO 기자 = ` 바로 뒤에 첫 문장이 붙는다.
문단을 통째로 버리면 리드 문장이 같이 날아가서 `byline_paren` 이 앞머리만 뗀다.
이 규칙이 계속 통하는지는 연합뉴스를 실제로 열어봐야만 안다.

## 링크를 고른 기준

`CHANNELS.md` 의 **A등급**(증권사 리서치 공식 채널)이 2026-09 에 올린 것들이다.
한국어·영어·중국어와 네이버 블로그가 섞이도록, 그리고 **안 열리는 것 하나**가
들어가도록 골랐다. 한 매체만 보면 규칙이 통하는지 알 수 없다.

사이트가 기사를 내리거나 구조를 바꾸면 이 테스트는 깨진다. 그때는 규칙이 아니라
**URL 을 갈아 끼우면 된다.** 규칙을 고치기 전에 눈으로 먼저 볼 것:

    uv run python -m app.services.news_link <주소> --paragraphs
"""

import asyncio

import pytest

from app.services.news_link import fetch_link_bodies
from app.services.news_link.sentence import split_sentences

pytestmark = pytest.mark.network

# (채널, 주소). 채널은 CHANNELS.md 의 A등급이다.
ARTICLES = [
    ("globalmktinsight", "https://www.yna.co.kr/view/AKR20260917177300002"),
    ("skitteam", "https://www.ytn.co.kr/_ln/0104_202609170958228832"),
    ("merITz_tech", "https://n.news.naver.com/mnews/article/374/0000533568"),
    ("KISGregKim", "https://zdnet.co.kr/view/?no=20260918130309"),
    ("egzion", "https://m.blog.naver.com/egzion/224413431430"),
    ("merITz_tech", "https://www.cnbc.com/2026/09/17/nvidia-huang-ai-chip-guidance.html"),
    ("skitteam", "https://wccftech.com/amd-notifies-partners-of-10-price-hike/amp/"),
    (
        "skitteam",
        (
            "https://www.techpowerup.com/352788/"
            "amd-plans-10-price-hike-across-gpus-chipsets-and-possibly-cpus"
        ),
    ),
    ("merITz_tech", "https://udn.com/news/story/7252/9760106"),
    # 본문을 못 읽는 쪽도 하나 넣는다. 절반은 원래 안 열리므로(fetch.py 맨 위 실측),
    # "못 읽어도 도메인은 남는다" 를 지키는지가 오히려 중요하다.
    (
        "skitteam",
        (
            "https://counterpointresearch.com/ko/insights/"
            "samsung-apple-global-smartphone-share-2026-h1"
        ),
    ),
]

# 발췌에 남아 있으면 안 되는 것들. 전부 실제 기사에서 나왔던 표현이다.
# 앞 3문장만 싣는데 이런 것이 한 칸을 차지하면 근거가 그만큼 줄어든다.
JUNK = [
    "무단 전재",
    "저작권자",
    "재배포 금지",
    "Copyright",
    "All rights reserved",
    "기자 =",  # 연합뉴스·뉴스핌 바이라인
    "특파원 =",
    "구독하기",
    "Subscribe to",
    "per month",  # ft.com 유료 구독 광고
]


@pytest.fixture(scope="module")
def bodies():
    """10건을 한 번만 연다. 테스트마다 열면 남의 서버를 그만큼 더 두드린다."""
    return asyncio.run(fetch_link_bodies([url for _, url in ARTICLES]))


def test_results_are_printed_for_human_review(bodies) -> None:
    """단언보다 **보이는 것**이 목적이다. `-s` 로 돌리면 발췌가 그대로 찍힌다.

    정제 규칙을 손볼 때 이 출력을 전후로 비교한다. 숫자만 보는 단언으로는
    "발췌가 기사 서두가 맞는가" 를 사람이 판단할 수 없다.
    """
    by_url = {b.url: b for b in bodies}
    print()
    for channel, url in ARTICLES:
        body = by_url[url]
        print("=" * 78)
        print(f"{channel:<18} {body.domain}  [{body.status}] {body.chars}자")
        print(f"  제목  {body.title}")
        if body.excerpt:
            print("  발췌  " + body.excerpt.replace("\n", "\n        "))
        else:
            print(f"  발췌  (없음 — {body.error or body.content_type or body.http_status})")

    assert len(by_url) == len(ARTICLES), "중복 없는 주소를 줬으니 전부 돌아와야 한다"


def test_domain_survives_even_when_body_is_unreadable(bodies) -> None:
    """이게 이 기능의 1번 값어치다. 모델은 `buly.kr/xxx` 만 보고는 출처를 모른다."""
    for body in bodies:
        assert body.domain, f"{body.url} — status={body.status} 인데 도메인도 없다"
        assert body.final_url


def test_excerpt_respects_length_and_sentence_limits(bodies) -> None:
    """400자·3문장. 문장 세는 규칙은 자르는 쪽과 **같은 함수**를 쓴다."""
    for body in (b for b in bodies if b.status == "ok"):
        assert body.excerpt
        assert len(body.excerpt) <= 400, f"{body.domain} — {len(body.excerpt)}자"
        sentences = split_sentences(body.excerpt)
        assert len(sentences) <= 3, f"{body.domain} — {len(sentences)}문장"
        assert body.chars == len(body.excerpt)


def test_excerpt_has_no_non_article_text(bodies) -> None:
    """정제 규칙이 실제 매체에서도 통하는지 보는 것이 이 파일의 핵심이다."""
    for body in (b for b in bodies if b.status == "ok"):
        for junk in JUNK:
            assert junk not in body.excerpt, f"{body.domain} 발췌에 '{junk}' 가 남았다"
        assert body.excerpt == body.excerpt.strip()


def test_most_articles_still_open(bodies) -> None:
    """느슨하게 잡는다. 매체가 봇을 막기 시작하면 줄어드는 게 정상이고 그건
    정제 규칙의 잘못이 아니다. **전부 막히는 것**만 잡아낸다.
    """
    opened = [b for b in bodies if b.status == "ok"]
    assert len(opened) >= 5, (
        f"10건 중 {len(opened)}건만 열렸다. 기사가 내려갔거나 사이트 구조가 바뀐 것일 수 있다. "
        "정제 규칙을 고치기 전에 --paragraphs 로 먼저 확인할 것"
    )
