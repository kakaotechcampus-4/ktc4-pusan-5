"""기사 주소 정규화. 같은 기사인 것만 같게 만들고, 다른 문서일 수 있는 차이는 남긴다."""

import pytest

from app.services.news.url import canonical_url


@pytest.mark.parametrize("raw,expected", [
    # 확실히 같은 주소
    ("HTTPS://News.Example.COM/a/1", "https://news.example.com/a/1"),
    ("https://news.example.com:443/a/1", "https://news.example.com/a/1"),
    ("http://news.example.com:80/a/1", "http://news.example.com/a/1"),
    ("https://news.example.com/a/1#comments", "https://news.example.com/a/1"),
    ("https://news.example.com", "https://news.example.com/"),
    ("  https://news.example.com/a/1  ", "https://news.example.com/a/1"),
    # 추적 파라미터만 뺀다. 나머지 쿼리는 순서까지 그대로다
    ("https://news.example.com/a?utm_source=tg&id=3&UTM_Medium=x", "https://news.example.com/a?id=3"),
    ("https://news.example.com/a?b=2&a=1&fbclid=xyz", "https://news.example.com/a?b=2&a=1"),
    ("https://news.example.com/a?utm_source=tg", "https://news.example.com/a"),
])
def test_same_document_gets_the_same_address(raw, expected):
    assert canonical_url(raw) == expected


@pytest.mark.parametrize("raw", [
    "https://news.example.com/a/1/",  # 끝의 / 는 사이트에 따라 다른 문서다
    "https://www.news.example.com/a/1",  # www 도 다른 호스트일 수 있다
    "http://news.example.com/a/1",  # http·https 를 합치지 않는다
    "https://news.example.com:8443/a/1",  # 기본 포트가 아니면 남긴다
    "https://www.yna.co.kr/view/AKR1?input=1195m",  # 사이트별 파라미터는 모른다
])
def test_differences_that_may_be_another_document_are_kept(raw):
    assert canonical_url(raw) == raw


def test_query_untouched_when_nothing_is_removed():
    """뺀 게 없으면 다시 인코딩하지 않는다. %xx 표기가 바뀌면 원래 주소와 달라진다."""
    raw = "https://news.example.com/search?q=%ec%82%bc%ec%84%b1+%EC%A0%84%EC%9E%90"
    assert canonical_url(raw) == raw


@pytest.mark.parametrize("raw", ["ftp://example.com/a", "not a url", "https://", "https://a:b/c"])
def test_non_http_or_broken_addresses_are_left_alone(raw):
    assert canonical_url(raw) == raw.strip()
