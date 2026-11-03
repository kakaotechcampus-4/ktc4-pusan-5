"""같은 이야기 묶기. LLM·DB 를 쓰지 않는다."""

import argparse
import csv
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.core.scope import KST
from app.services.classification import __main__ as cli
from app.services.classification.basis import load_basis
from app.services.classification.dedupe import (
    Article,
    fingerprints,
    group_articles,
    lost_stocks,
    shingles,
    summarize,
    write_groups,
)

START = datetime(2026, 11, 1, 9, 0, tzinfo=KST)
WINDOW = timedelta(hours=48)
STORY = ("삼성전자 경영진이 일본 요코하마에 새로 짓는 반도체 패키징 연구 거점을 찾아 현지 협력사와 "
         "차세대 메모리 공정 기술을 논의했다고 회사가 밝혔다. 이번 방문은 일본 소재 장비 업체와의 "
         "공동 연구를 넓히려는 목적이며 내년부터 시제품 검증에 들어갈 계획이라고 설명했다.")
OTHER = ("현대차가 미국 조지아 공장의 전기차 생산량을 늘리기로 하면서 국내 부품사의 납품 물량이 "
         "함께 늘어날 전망이다. 회사는 관세 부담을 줄이려고 현지 생산 비중을 높이겠다고 밝혔고 "
         "증권가는 하반기 영업이익이 시장 기대를 웃돌 것으로 내다봤다.")
NAMES = {"005930": "삼성전자", "000660": "SK하이닉스", "005380": "현대차"}


def article(article_id: int, body: str, *, hours: float = 0, title: str = "제목",
            publisher: str | None = None) -> Article:
    return Article(article_id, title, body, START + timedelta(hours=hours), publisher)


def group(articles: list[Article], *, threshold: float = 0.5, metric: str = "jaccard",
          window: timedelta = WINDOW):
    # 표본이 작아 흔한 조각을 빼면 다 사라진다. 흔한 조각 처리는 따로 본다
    return group_articles(articles, fingerprints(articles, common_share=1.0), threshold=threshold,
                          window=window, metric=metric)


def test_same_wire_story_is_grouped_and_other_story_is_not():
    groups = group([article(1, STORY), article(2, "[속보] " + STORY + " 기자 홍길동", hours=1),
                    article(3, OTHER, hours=2)])
    assert [[a.id for a in g.articles] for g in groups] == [[1, 2], [3]]


def test_leader_is_the_earliest_whatever_the_input_order():
    groups = group([article(1, STORY, hours=5), article(2, STORY, hours=1), article(3, STORY, hours=3)])
    assert groups[0].leader.id == 2
    assert {a.id for a in groups[0].articles} == {1, 2, 3}


def test_counts_articles_and_publishers_separately():
    """한 매체가 고쳐 올린 기사까지 '여러 매체가 보도' 로 세지 않는다."""
    groups = group([article(1, STORY, publisher="a.com"), article(2, STORY, hours=1, publisher="a.com"),
                    article(3, STORY, hours=2, publisher="b.com")])
    assert groups[0].article_count == 3
    assert groups[0].publisher_count == 2


def test_story_outside_the_window_starts_a_new_group():
    groups = group([article(1, STORY), article(2, STORY, hours=49)])
    assert len(groups) == 2


def test_groups_do_not_chain_through_a_middle_article():
    half = len(STORY) // 2
    first, middle, last = STORY, STORY[half:] + OTHER[:half], OTHER
    groups = group([article(1, first), article(2, middle, hours=1), article(3, last, hours=2)],
                   threshold=0.3)
    assert not any({1, 3} <= {a.id for a in g.articles} for g in groups)


def test_shared_footer_does_not_make_different_stories_the_same():
    footer = "무단전재 및 재배포 금지 저작권자 경제신문 구독 문의는 고객센터로 연락 바랍니다 " * 6
    others = [article(100 + n, f"관련 없는 기사 번호 {n} " * 20 + footer, hours=n) for n in range(40)]
    articles = [article(1, STORY + footer), article(2, OTHER + footer, hours=1), *others]
    prints = fingerprints(articles)
    groups = group_articles(articles, prints, threshold=0.5, window=timedelta(days=30))
    assert not any({1, 2} <= {a.id for a in g.articles} for g in groups)


def test_short_text_is_never_grouped():
    groups = group([article(1, "삼성전자 주가 상승"), article(2, "삼성전자 주가 상승", hours=1)])
    assert len(groups) == 2


def test_containment_groups_a_short_copy_that_jaccard_keeps_apart():
    short, long = STORY, STORY + OTHER * 3
    assert len(group([article(1, short), article(2, long, hours=1)], threshold=0.7)) == 2
    assert len(group([article(1, short), article(2, long, hours=1)], threshold=0.7,
                     metric="containment")) == 1


def test_lost_stocks_are_those_only_members_mention():
    groups = group([article(1, STORY), article(2, STORY + " SK하이닉스도 참여한다", hours=1)])
    assert lost_stocks(groups[0], NAMES) == {"000660"}


def test_summary_counts_what_grouping_would_save():
    groups = group([article(1, STORY), article(2, STORY + " SK하이닉스도 참여한다", hours=1),
                    article(3, OTHER, hours=2)])
    summary = summarize(groups, NAMES)
    assert (summary.articles, summary.groups, summary.removed, summary.grouped) == (3, 2, 1, 1)
    assert summary.largest == 2
    assert summary.sizes == {"2": 1}
    assert summary.removed_chars == len(groups[0].members[0].article.text)
    # 묶음 1: 삼성전자(대표에 있음)·SK하이닉스(없음), 묶음 2: 현대차(있음)
    assert (summary.stock_pairs, summary.lost_pairs) == (3, 1)


def test_review_lists_only_multi_article_groups(tmp_path):
    groups = group([article(1, STORY, publisher="a.com", title="대표"),
                    article(2, STORY + " SK하이닉스도 참여한다", hours=1, publisher="b.com", title="묶임"),
                    article(3, OTHER, hours=2, title="혼자")])
    out = tmp_path / "review.csv"
    assert write_groups(groups, NAMES, out) == 2
    rows = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    assert [r["title"] for r in rows] == ["대표", "묶임"]
    assert rows[0]["similarity"] == "" and float(rows[1]["similarity"]) > 0.5
    assert rows[0]["lost_stocks"] == "SK하이닉스"


async def test_measure_command_reports_news_only_and_writes_review(monkeypatch, tmp_path, capsys):
    """DB 자리만 바꿔 명령을 끝까지 돌린다. 폴더가 없어도 검토표를 쓰고, 리포트·메시지는 묶지 않는다."""

    def record(card_id, kind, body, hours):
        return SimpleNamespace(id=card_id, kind=kind, title="제목", body=body, has_body=bool(body),
                               publisher=f"매체{card_id}", available_at=START + timedelta(hours=hours))

    records = [record(1, "news", STORY, 0), record(2, "news", STORY, 1), record(3, "news", OTHER, 2),
               record(4, "pdf", STORY, 3), record(5, "message", STORY, 4), record(6, "news", None, 5)]
    basis = load_basis(Path(__file__).parent / "fixtures" / "mock_classification_basis.json")
    monkeypatch.setattr(cli, "load_basis", lambda path: basis)
    monkeypatch.setattr(cli, "SessionLocal", MagicMock(return_value=AsyncMock()))
    monkeypatch.setattr(cli, "classifiable_card_ids", AsyncMock(return_value=[r.id for r in records]))
    monkeypatch.setattr(cli, "get_sources", AsyncMock(return_value=records))

    out = tmp_path / "없는폴더" / "review.csv"
    await cli.run_dedupe_measure(argparse.Namespace(
        basis=None, since=None, window_hours=48, metric="jaccard", threshold=0.5, out=out))

    printed = capsys.readouterr().out
    assert "본문 있는 자료 5건" in printed
    assert "묶는 뉴스 3건" in printed
    rows = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    assert {r["card_id"] for r in rows} == {"1", "2"}


def test_shingles_ignore_spacing_and_punctuation():
    assert shingles("삼성 전자, 주가!") == shingles("삼성전자주가")
