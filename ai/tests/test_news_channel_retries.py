"""기존 기사의 재시도가 신규 수량을 소비하거나 다른 기사를 덮지 않는지 검사한다."""

import httpx

from app.collectors.news_channels import ChannelStats, attach_link_bodies
from app.repositories.news import KnownArticle
from app.services.telegram_web import Channel
from tests.test_news_channels import ARTICLE_HTML as MOCK_ARTICLE_HTML
from tests.test_news_channels import NOW
from tests.test_news_channels import _message as mock_message


def mock_article(url, status):
    return KnownArticle(id=1, url=url, canonical_url=url, status=status, fetched_at=NOW)


async def test_known_success_and_failure_do_not_consume_new_article_budget():
    mock_urls = [f"https://example.com/{key}" for key in ("ok", "failed", "new", "held")]
    mock_msg = mock_message(mock_urls)
    mock_stats = [ChannelStats(channel=Channel("ch", "mock", "mock", "A"))]
    mock_opened = []

    def mock_handler(request):
        mock_opened.append(str(request.url))
        return httpx.Response(200, html=MOCK_ARTICLE_HTML)

    held = await attach_link_bodies(
        [mock_msg], mock_stats, now=NOW, per_message=0, max_links=1,
        existing={mock_urls[0]: mock_article(mock_urls[0], "ok"),
                  mock_urls[1]: mock_article(mock_urls[1], "failed")},
        transport=httpx.MockTransport(mock_handler),
    )
    assert held == 1
    assert mock_opened == mock_urls[1:3]
    assert [body.url for body in mock_msg.link_bodies] == mock_urls[1:3]
    assert mock_stats[0].opened == 2


async def test_redirect_changed_during_retry_does_not_bypass_quota():
    mock_url = "https://example.com/old"
    mock_msg = mock_message([mock_url])
    mock_stats = [ChannelStats(channel=Channel("ch", "mock", "mock", "A"))]

    def mock_handler(request):
        if request.url.path == "/old":
            return httpx.Response(302, headers={"location": "/new"})
        return httpx.Response(200, html=MOCK_ARTICLE_HTML)

    held = await attach_link_bodies(
        [mock_msg], mock_stats, now=NOW, per_message=3, max_links=0,
        existing={mock_url: mock_article(mock_url, "failed")},
        transport=httpx.MockTransport(mock_handler),
    )
    assert held == 1
    assert mock_msg.link_bodies == []


async def test_purged_article_is_not_downloaded_again():
    mock_url = "https://example.com/purged"
    mock_msg = mock_message([mock_url])

    def mock_handler(request):
        raise AssertionError("A purged article was downloaded")

    assert await attach_link_bodies(
        [mock_msg], [ChannelStats(channel=Channel("ch", "mock", "mock", "A"))],
        now=NOW, per_message=3, max_links=10,
        existing={mock_url: mock_article(mock_url, "purged")},
        transport=httpx.MockTransport(mock_handler),
    ) == 0
    assert mock_msg.link_bodies == []
