"""같은 이야기를 하는 뉴스 묶기 (CLASSIFICATION_TUNING 2-6). LLM·DB 를 쓰지 않는다.

제목이 같은 뉴스는 드물어 제목으로는 못 묶는다. 공백·기호를 뺀 글자 조각이 얼마나 겹치는지로 본다.

    시간순으로 보며, 시간 범위 안의 대표 중 가장 비슷한 기사의 묶음에 넣는다. 없으면 새 묶음의 대표가 된다.

- 대표는 가장 이른 기사다. 뒤에 기사가 더 들어와도 대표가 바뀌지 않고, 기준 시각 전에 공개된 기사로 남는다.
- 대표하고만 견준다. 서로 이어 묶으면 A~B, B~C 가 비슷할 때 다른 이야기인 A 와 C 까지 합쳐진다.
- 묶으면 대표만 분류하므로 대표에 없는 내용은 잃는다. lost_stocks 가 그 크기를 재고, 재 보기 전에는
  기준값을 정하지 않는다.
"""

import csv
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

SHINGLE_CHARS = 5
# 조각이 이보다 적은 기사는 몇 조각만 겹쳐도 비슷해 보이므로 묶지 않는다
MIN_SHINGLES = 50
# 기사의 이 비율 넘게 나오는 조각은 매체 꼬리말·종목 이름 같은 것이라 비교에서 뺀다
COMMON_SHARE = 0.05
_NOT_TEXT = re.compile(r"[^0-9A-Za-z가-힣]+")

METRICS = {
    # 두 기사 전체가 얼마나 같은가. 한쪽에만 있는 내용이 많으면 낮아진다
    "jaccard": lambda overlap, a, b: overlap / (a + b - overlap),
    # 짧은 기사가 긴 기사에 얼마나 들어 있는가. 긴 기사가 대표가 아니면 그 뒷부분을 잃을 수 있다
    "containment": lambda overlap, a, b: overlap / min(a, b),
}


@dataclass(frozen=True)
class Article:
    id: int
    title: str
    body: str
    available_at: datetime
    publisher: str | None = None

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.body}"


@dataclass(frozen=True)
class Member:
    article: Article
    similarity: float


@dataclass
class Group:
    leader: Article
    members: list[Member] = field(default_factory=list)  # 대표는 뺀다

    @property
    def articles(self) -> list[Article]:
        return [self.leader, *(m.article for m in self.members)]

    @property
    def article_count(self) -> int:
        return len(self.articles)

    @property
    def publisher_count(self) -> int:
        """매체 수. 한 매체가 고쳐 올린 기사는 기사 수만 늘린다."""
        return len({a.publisher for a in self.articles if a.publisher}) or 1


def shingles(text: str) -> frozenset[str]:
    cleaned = _NOT_TEXT.sub("", text)
    return frozenset(cleaned[i:i + SHINGLE_CHARS] for i in range(len(cleaned) - SHINGLE_CHARS + 1))


def fingerprints(articles: Iterable[Article],
                 common_share: float = COMMON_SHARE) -> dict[int, frozenset[str]]:
    """기사별 글자 조각. 너무 흔한 조각은 뺀다."""
    prints = {a.id: shingles(a.text) for a in articles}
    frequency = Counter(s for found in prints.values() for s in found)
    limit = max(common_share * len(prints), 2)
    common = {s for s, n in frequency.items() if n > limit}
    return {article_id: found - common for article_id, found in prints.items()}


def group_articles(articles: Iterable[Article], prints: Mapping[int, frozenset[str]], *,
                   threshold: float, window: timedelta, metric: str = "jaccard") -> list[Group]:
    measure = METRICS[metric]
    groups: list[Group] = []
    postings: dict[str, list[int]] = defaultdict(list)  # 조각 → 그 조각이 대표에 있는 묶음 번호
    for article in sorted(articles, key=lambda a: (a.available_at, a.id)):
        found = prints[article.id]
        best, best_similarity = None, 0.0
        if len(found) >= MIN_SHINGLES:
            for number, overlap in Counter(n for s in found for n in postings.get(s, ())).items():
                leader = groups[number].leader
                if article.available_at - leader.available_at > window:
                    continue
                similarity = measure(overlap, len(found), len(prints[leader.id]))
                if similarity >= threshold and similarity > best_similarity:
                    best, best_similarity = number, similarity
        if best is not None:
            groups[best].members.append(Member(article, best_similarity))
            continue
        groups.append(Group(article))
        if len(found) >= MIN_SHINGLES:
            for s in found:
                postings[s].append(len(groups) - 1)
    return groups


def lost_stocks(group: Group, names: Mapping[str, str]) -> set[str]:
    """묶인 기사에는 이름이 나오는데 대표에는 없는 종목. 대표만 분류하면 이 종목의 근거가 빠질 수 있다."""
    in_leader = {code for code, name in names.items() if name in group.leader.text}
    in_members = {code for code, name in names.items()
                  if any(name in m.article.text for m in group.members)}
    return in_members - in_leader


@dataclass(frozen=True)
class Summary:
    articles: int
    groups: int
    removed: int  # 분류하지 않아도 되는 기사 수
    chars: int
    removed_chars: int
    grouped: int  # 2건 이상 묶음 수
    largest: int
    sizes: dict[str, int]  # 묶음 크기 구간별 묶음 수
    stock_pairs: int  # (묶음, 이름이 나온 종목) 쌍
    lost_pairs: int  # 그중 대표에 이름이 없는 쌍


def summarize(groups: list[Group], names: Mapping[str, str]) -> Summary:
    sizes = Counter()
    for group in groups:
        n = group.article_count
        if n > 1:
            sizes["2" if n == 2 else "3-5" if n <= 5 else "6-10" if n <= 10 else "11+"] += 1
    lost_pairs = stock_pairs = 0
    for group in groups:
        in_leader = {code for code, name in names.items() if name in group.leader.text}
        lost = lost_stocks(group, names)
        lost_pairs += len(lost)
        stock_pairs += len(in_leader) + len(lost)
    chars = sum(len(a.text) for g in groups for a in g.articles)
    kept = sum(len(g.leader.text) for g in groups)
    articles = sum(g.article_count for g in groups)
    return Summary(
        articles=articles, groups=len(groups), removed=articles - len(groups), chars=chars,
        removed_chars=chars - kept, grouped=sum(sizes.values()),
        largest=max((g.article_count for g in groups), default=0), sizes=dict(sizes),
        stock_pairs=stock_pairs, lost_pairs=lost_pairs,
    )


REVIEW_COLUMNS = ["group", "article_count", "publisher_count", "similarity", "role", "card_id",
                  "publisher", "available_at", "title", "lost_stocks"]


def write_groups(groups: list[Group], names: Mapping[str, str], out: Path) -> int:
    """사람이 읽는 검토표. 2건 이상 묶음만, 큰 묶음부터. similarity 가 낮은 행이 잘못 묶였는지 본다."""
    rows = 0
    out.parent.mkdir(parents=True, exist_ok=True)  # eval_data 는 git 에 없어 새 작업 폴더에는 없다
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        multi = sorted((g for g in groups if g.members), key=lambda g: -g.article_count)
        for number, group in enumerate(multi, start=1):
            lost = ",".join(names[code] for code in sorted(lost_stocks(group, names)))
            entries = [(group.leader, None, "leader"),
                       *((m.article, m.similarity, "member") for m in group.members)]
            for article, similarity, role in entries:
                writer.writerow({
                    "group": number, "article_count": group.article_count,
                    "publisher_count": group.publisher_count,
                    "similarity": "" if similarity is None else f"{similarity:.3f}", "role": role,
                    "card_id": article.id, "publisher": article.publisher or "",
                    "available_at": article.available_at.isoformat(), "title": article.title,
                    "lost_stocks": lost if role == "leader" else "",
                })
                rows += 1
    return rows
