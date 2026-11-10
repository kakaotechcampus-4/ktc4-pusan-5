"""분류할 자료 고르기: 네이버 뉴스 종목당 상한과 하루 비용 상한.

네이버 뉴스는 종목 이름으로 검색해 들어와 하루 2,000건을 넘는다(2026-11-06 2,122건). 전부 분류하면
평일 하루 약 ₩2,900 이다. 그래서 날마다 종목당 상위 N 건만 분류하고, 하루 비용이 상한에 닿으면 멈춘다.
근거와 수치는 docs/CLASSIFICATION_TUNING.md 의 "5-5"(상한)·"5-6"(같은 소식 묶기) 에 있다.

- 상한은 네이버 뉴스에만 건다. 텔레그램 메시지·링크 기사·PDF 는 건수가 적고 시황·업종 글이 많아 전부 분류한다.
- 고르지 않은 기사도 원문은 DB 에 남는다(5-4: 수집량보다 LLM 에 넣는 양을 줄인다).
- 종목 이름이 하나도 나오지 않는 네이버 뉴스는 고르지 않는다(11-06 2,122건 중 142건).
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from app.services.classification.basis import Stock
from app.services.classification.candidates import promotional


@dataclass(frozen=True)
class NewsCandidate:
    """상한을 거는 네이버 뉴스 한 건. day 는 공개일(KST)이다. 상한은 날마다 따로 센다."""

    card_id: int
    day: date
    title: str
    body: str
    published_at: datetime | None


def normalize_title(title: str) -> str:
    """같은 기사를 여러 매체가 옮긴 경우를 하나로 보려고 괄호 머리말·기호·공백을 뺀다."""
    title = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", title or "")
    return re.sub(r"[^0-9A-Za-z가-힣]", "", title)


# 제목 낱말이 이만큼 겹치면 같은 소식으로 본다(겹친 낱말 수 / 짧은 쪽 낱말 수). 9일 시뮬레이션으로 정했다
# (docs/CLASSIFICATION_TUNING.md 5-6): 0.5·0.6 은 덜 묶여 같은 소식이 자리를 더 차지했다.
SAME_STORY_OVERLAP = 0.4
# 낱말 끝에서 떼는 조사 한 글자(삼성물산이 → 삼성물산). 세 글자 이상 낱말에만 뗀다
_PARTICLES = "은는이가을를에의와과도로"
# '가' 로 끝나지만 조사가 아닌 주가 용어. 떼면 다른 낱말이 된다(신고가 → 신고, 최고가 → 최고).
# 목표가는 넣지 않는다: 네이버 제목이 "…목표..." 처럼 잘려 들어와서, 떼야 같은 소식끼리 묶인다(5-6).
_PRICE_WORDS = frozenset({"신고가", "최고가", "최저가", "상한가", "하한가"})


def title_words(title: str, drop: Iterable[str] = ()) -> frozenset[str]:
    """같은 소식 비교용 제목 낱말. [머리말]과 drop(그 종목의 이름들)을 빼고, 두 글자 이상 낱말만 남긴다.

    종목 이름을 빼는 것은 그 종목 목록 안의 기사는 모두 그 이름을 가져서 겹침이 부풀기 때문이다.
    """
    title = re.sub(r"\[[^\]]*\]", " ", title or "")
    for name in sorted(drop, key=len, reverse=True):
        title = title.replace(name, " ")
    words = set()
    for word in re.findall(r"[0-9A-Za-z가-힣]+", title):
        if len(word) >= 3 and word[-1] in _PARTICLES and word not in _PRICE_WORDS:
            word = word[:-1]
        if len(word) >= 2:
            words.add(word)
    return frozenset(words)


def same_story(a: frozenset[str], b: frozenset[str]) -> bool:
    """두 제목 낱말이 SAME_STORY_OVERLAP 이상, 그리고 두 개 이상 겹치나. 낱말이 없는 제목은 같다고 보지 않는다.

    짧은 제목은 '검토' 같은 흔한 낱말 하나만 겹쳐도 비율이 0.5 가 된다("리콜 검토" / "노조 파업 검토").
    그래서 두 개 이상 겹쳐야 같은 소식으로 본다. 짧은 쪽 낱말이 하나뿐이면("[인사] LS그룹") 하나로 충분하다.
    """
    if not a or not b:
        return False
    shared, shorter = len(a & b), min(len(a), len(b))
    return shared >= min(2, shorter) and shared / shorter >= SAME_STORY_OVERLAP


def stock_names(stock: Stock) -> tuple[str, ...]:
    """기사에서 찾을 이름. 종목명·별칭·비상장 자회사(예: 삼성전자 → 삼성디스플레이)."""
    return tuple(n for n in (stock.name, *stock.aliases, *stock.subsidiaries) if n)


def rank_news(candidates: Iterable[NewsCandidate], stocks: Iterable[Stock], cap: int) -> dict[int, int]:
    """날마다·종목마다 상위 cap 건을 고른다. {카드 id: 그 카드가 받은 가장 높은 순위(0부터)}.

    종목 안의 순서: 제목에 이름이 있는 기사 → 본문에 이름이 많이 나온 기사 → 최신 → 카드 id 큰 것.
    단 제목에 홍보성 표현(수상·캠페인·사회공헌 등, candidates.NO_RELATION_PATTERN)이 있는 기사는 맨 뒤로
    보낸다. 빼지는 않는다. 그날 기사가 상한보다 적으면 홍보성 기사도 분류한다.
    종목마다 같은 소식은 하나만 센다: 정규화한 제목이 같거나, 이미 고른 제목과 낱말이 많이 겹치면
    (same_story) 건너뛰고 다음 소식에 자리를 준다. 한 기사가 여러 종목에서 뽑혀도 한 번만 분류한다.
    """
    if cap < 1:
        raise ValueError(f"종목당 상한은 1 이상이어야 한다: {cap}")
    names = {stock.code: stock_names(stock) for stock in stocks}
    lists: dict[tuple[date, str], list[tuple]] = defaultdict(list)
    for news in candidates:
        # 제목에 종목 이름이 있어 위로 올라오지만 주가 설명에는 쓸모가 적다. 자리를 차지하지 않게 내린다
        promo = promotional(news.title)
        for code, stock_name_list in names.items():
            in_title = any(n in news.title for n in stock_name_list)
            count = sum(news.body.count(n) for n in stock_name_list)
            if in_title or count:
                published = news.published_at.timestamp() if news.published_at else 0.0
                key = (promo, not in_title, -count, -published, -news.card_id)
                lists[(news.day, code)].append((key, news.title, news.card_id))

    best: dict[int, int] = {}
    for (_day, code), items in lists.items():
        seen: set[str] = set()
        picked_words: list[frozenset[str]] = []
        for _key, title, card_id in sorted(items):
            if len(picked_words) >= cap:
                break
            norm = normalize_title(title)
            if norm and norm in seen:
                continue
            words = title_words(title, names[code])
            if any(same_story(words, picked) for picked in picked_words):
                continue
            seen.add(norm)
            position = len(picked_words)
            picked_words.append(words)
            best[card_id] = min(best.get(card_id, position), position)
    return best


def order_for_classification(card_ids: Sequence[int], naver: Iterable[NewsCandidate],
                             stocks: Iterable[Stock], cap: int) -> tuple[list[int], int]:
    """(분류할 순서대로 고른 카드 id, 상한으로 뺀 네이버 뉴스 수).

    card_ids 는 분류할 후보(회차 없는 자료, 최근 순)다. naver 는 그 후보와 같은 날짜의 네이버 뉴스 전부다.
    이미 분류한 기사도 넣어야 그날 순위가 맞는다(하루 여러 번 돌아도 같은 기준으로 고른다).
    네이버 뉴스가 아닌 자료를 먼저, 네이버 뉴스는 순위가 높은 것부터 둔다. 하루 비용 상한에 닿아 중간에
    멈추면 앞쪽이 남는다.
    """
    naver = list(naver)
    naver_ids = {n.card_id for n in naver}
    rank = rank_news(naver, stocks, cap)
    others = [c for c in card_ids if c not in naver_ids]
    order = {c: i for i, c in enumerate(card_ids)}
    picked = sorted((c for c in card_ids if c in rank), key=lambda c: (rank[c], order[c]))
    dropped = sum(1 for c in card_ids if c in naver_ids and c not in rank)
    return others + picked, dropped


class DailyBudget:
    """오늘(KST) 분류에 쓴 비용이 상한에 닿으면 새 자료를 시작하지 않는다.

    spent 는 실행 전에 DB 에서 센 오늘 비용이다. 이번 실행에서 쓴 비용은 add 로 더한다.
    동시에 돌고 있는 자료는 끝까지 가므로 상한을 동시 실행 수 × 자료 하나 비용만큼 넘을 수 있다.
    """

    def __init__(self, limit: float | None, spent: float) -> None:
        self.limit = limit
        self.spent = spent

    def allows(self) -> bool:
        return self.limit is None or self.spent < self.limit

    def add(self, cost: float) -> None:
        self.spent += cost
