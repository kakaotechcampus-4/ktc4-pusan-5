"""Shared isolated PostgreSQL fixture for repository tests."""

import ipaddress

import pytest

from app.services.news_link import fetch
from tests.test_migrations import database, empty_database  # noqa: F401

# 가짜 DNS 가 모르는 호스트에 돌려주는 공개 IP (example.com 의 것).
PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def fake_dns(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> dict[str, list[str]]:
    """링크 열기 전 주소 검사(news_link.fetch.ensure_public)가 실제 DNS 를 타지 않게 한다.

    MockTransport 로 남의 서버 없이 도는 테스트가 DNS 때문에 네트워크를 타면 안 된다.
    돌려준 dict 에 `{"호스트": ["IP"]}` 를 넣으면 그 호스트만 그 IP 로 푼다.
    IP 가 바로 적힌 주소는 그 IP, 나머지는 공개 IP 로 푼다.
    network 마커 테스트는 실제 DNS 를 쓴다.
    """
    table: dict[str, list[str]] = {}
    if request.node.get_closest_marker("network"):
        return table

    async def resolve(host: str) -> list[str]:
        if host in table:
            return table[host]
        try:
            return [str(ipaddress.ip_address(host))]
        except ValueError:
            return [PUBLIC_IP]

    monkeypatch.setattr(fetch, "resolve_host", resolve)
    return table
