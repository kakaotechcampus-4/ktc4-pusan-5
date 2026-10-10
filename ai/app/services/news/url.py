"""기사 주소 정규화. **같은 기사인지 가르는 데만 쓴다.** 원래 주소는 따로 그대로 둔다.

네이버 검색이 준 originallink 와 텔레그램 단축 URL 을 따라가 도착한 주소는 같은 기사라도
글자가 다를 수 있다. 추적용 파라미터(utm_*)가 붙거나, 호스트 대소문자·기본 포트·#조각이
다른 식이다. 그대로 비교하면 같은 기사가 news 에 두 줄로 들어간다.

**확실히 같은 주소가 되는 것만 고친다.**
    - scheme·호스트를 소문자로, 기본 포트(:80·:443)를 뺀다
    - #조각을 뺀다. 서버로 가지 않는 값이라 받는 문서가 같다
    - 광고·유입 추적 파라미터(TRACKING_PARAMS)만 뺀다. 나머지 쿼리는 순서까지 그대로 둔다
    - 경로가 비었으면 "/" 로 둔다

하지 않는 것: http↔https 통일, www 제거, 끝의 / 제거, 사이트별 파라미터(연합뉴스 input= 등)
제거. 사이트에 따라 다른 문서가 될 수 있어서다. 이런 차이로 같은 기사가 두 줄이 되는 것은
감수한다 — 다른 기사를 하나로 합쳐 본문을 잃는 것보다 낫다.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# 이 이름(소문자 비교)이거나 utm_ 으로 시작하는 쿼리 파라미터를 뺀다.
TRACKING_PARAMS = frozenset({
    "fbclid", "gclid", "dclid", "msclkid", "igshid", "yclid", "mc_cid", "mc_eid", "_ga",
})
DEFAULT_PORTS = {"http": 80, "https": 443}


def _is_tracking(key: str) -> bool:
    key = key.lower()
    return key.startswith("utm_") or key in TRACKING_PARAMS


def canonical_url(url: str) -> str:
    """중복 판정용 주소. http(s) 가 아니거나 읽을 수 없으면 앞뒤 공백만 뗀 원래 값이다."""
    raw = url.strip()
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:  # 포트가 숫자가 아닌 주소 등
        return raw
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS or not parts.hostname:
        return raw

    host = parts.hostname.lower()
    if ":" in host:  # IPv6 는 대괄호를 되돌린다
        host = f"[{host}]"
    if port is not None and port != DEFAULT_PORTS[scheme]:
        host = f"{host}:{port}"
    if parts.username is not None:
        userinfo = parts.username + (f":{parts.password}" if parts.password is not None else "")
        host = f"{userinfo}@{host}"

    pairs = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(key, value) for key, value in pairs if not _is_tracking(key)]
    # 뺀 것이 없으면 원래 쿼리 문자열을 그대로 둔다. 다시 인코딩하면 %XX 대소문자 같은
    # 표기가 바뀌어, 고친 게 없는데도 원래 주소와 달라진다.
    query = parts.query if len(kept) == len(pairs) else urlencode(kept)
    return urlunsplit((scheme, host, parts.path or "/", query, ""))
