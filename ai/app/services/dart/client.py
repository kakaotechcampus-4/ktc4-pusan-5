"""DART 공시 검색(list.json) 어댑터.

https://opendart.fss.or.kr/api/list.json
응답 필드: corp_code, corp_name, stock_code, corp_cls, report_nm, rcept_no, flr_nm, rcept_dt, rm

**회사를 하나씩 묻지 않고 하루치 코스피 공시를 통째로 받는다.** 회사별로 물으려면 종목코드를
DART 고유번호(corp_code)로 바꾸는 표(corpCode.xml, 수 MB 짜리 zip)가 필요하다. 하루치 코스피
공시는 수백 건이라 몇 쪽이면 끝나고, 종목코드가 응답에 들어 있어 거르기만 하면 된다.
corp_code 없이 검색할 수 있는 기간은 3개월이라 하루 단위면 걸리지 않는다.

**접수 시각은 주지 않는다.** rcept_dt 는 날짜뿐이다. 장중 기준 시각보다 먼저 나온 공시인지는
이 응답만으로 알 수 없다. 저장소가 처음 본 시각(first_seen_at)을 같이 남기는 이유다.

backend `app/services/dart_client.py` 와 같은 API 를 부른다. ai 는 backend 코드를 import 하지
않으므로 따로 둔다.
"""

from datetime import date

import httpx

from app.core.config import settings
from app.services.dart.schema import Disclosure
from app.services.news.failure import FailureKind, dart_status, failure_kind, http_error

LIST_URL = "https://opendart.fss.or.kr/api/list.json"
PAGE_COUNT = 100  # 쪽당 최대 건수
MAX_PAGES = 50  # 하루 코스피 공시가 5천 건을 넘을 일은 없다. 넘으면 응답이 이상한 것이다

_STATUS_OK = "000"
_STATUS_EMPTY = "013"  # 조회된 데이터가 없음


class DartError(Exception):
    """DART 호출 실패. 원인 예외는 __cause__ 에 남는다.

    reason 은 news.body_error 와 같은 형식(`http_error: 503`, `dart_status: 020` …)이고,
    kind 로 영구·요청 과다·일시 실패를 가른다(services/news/failure.py). 재시도는 하지 않는다.
    HTTP 200 인데 응답을 믿을 수 없으면 `invalid_response: <어디가>` 다. 무엇이 왔는지 몰라
    kind 는 unknown 이다.
        not_json          JSON 이 아니다(점검 HTML·잘린 응답)
        not_object        JSON 이지만 객체가 아니다(배열·문자열 등)
        status            status 가 없거나 문자열이 아니다
        total_page        성공인데 쪽 수가 숫자가 아니거나 지금 쪽보다 작다
        list              성공인데 list 가 객체 목록이 아니다
        disclosure        공시 행의 필드가 없거나 형식이 다르다(parse_list 실패)
    """

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason

    @property
    def kind(self) -> FailureKind:
        return failure_kind(self.reason)


def parse_list(rows: list[dict]) -> list[Disclosure]:
    """list.json 의 list → Disclosure. 종목코드가 없는 행(비상장 등)은 버린다."""
    items: list[Disclosure] = []
    for row in rows:
        stock_code = (row.get("stock_code") or "").strip()
        if not stock_code:
            continue
        items.append(
            Disclosure(
                rcept_no=row["rcept_no"],
                corp_code=row["corp_code"],
                corp_name=row["corp_name"].strip(),
                stock_code=stock_code,
                report_nm=" ".join(row["report_nm"].split()),
                flr_nm=row["flr_nm"].strip(),
                rcept_dt=date(int(row["rcept_dt"][:4]), int(row["rcept_dt"][4:6]),
                              int(row["rcept_dt"][6:8])),
                rm=(row.get("rm") or "").strip() or None,
            )
        )
    return items


async def _page(client: httpx.AsyncClient, key: str, day: date, page_no: int) -> dict:
    ymd = day.strftime("%Y%m%d")
    params = {
        "crtfc_key": key,
        "bgn_de": ymd,
        "end_de": ymd,
        "corp_cls": "Y",  # 유가증권시장(코스피)
        "page_no": str(page_no),
        "page_count": str(PAGE_COUNT),
    }
    try:
        resp = await client.get(LIST_URL, params=params)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        reason = http_error(e.response.status_code)
        raise DartError(f"{ymd} p{page_no}: {reason}", reason=reason) from e
    except httpx.HTTPError as e:
        reason = f"request_failed: {type(e).__name__}"
        raise DartError(f"{ymd} p{page_no}: {reason}", reason=reason) from e
    try:
        body = resp.json()
    except ValueError as e:  # JSONDecodeError·UnicodeDecodeError 둘 다 ValueError 다
        reason = "invalid_response: not_json"
        raise DartError(f"{ymd} p{page_no}: {reason}", reason=reason) from e
    if not isinstance(body, dict):
        reason = "invalid_response: not_object"
        raise DartError(f"{ymd} p{page_no}: {reason}", reason=reason)
    status = body.get("status")
    if not isinstance(status, str) or not status:
        reason = "invalid_response: status"
        raise DartError(f"{ymd} p{page_no}: {reason}", reason=reason)
    if status == _STATUS_EMPTY:
        return {"list": [], "total_page": 0}
    if status != _STATUS_OK:
        # 키를 메시지에 남기지 않는다
        reason = f"{dart_status(status)} ({body.get('message')})"
        raise DartError(f"{ymd} p{page_no}: {reason}", reason=reason)
    # 성공인데 쪽 수가 없으면 1쪽에서 멈춰 나머지 쪽을 빠뜨린다. 쪽 수는 정수나 숫자 문자열이고
    # 지금 쪽 이상이어야 한다. bool 은 int 의 하위형이라, "²" 는 isdigit 이 참이라 따로 막는다.
    total = body.get("total_page")
    if (isinstance(total, bool) or not isinstance(total, (int, str))
            or (not str(total).isascii() or not str(total).isdigit()) or int(total) < page_no):
        reason = "invalid_response: total_page"
        raise DartError(f"{ymd} p{page_no}: {reason}", reason=reason)
    rows = body.get("list")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        reason = "invalid_response: list"
        raise DartError(f"{ymd} p{page_no}: {reason}", reason=reason)
    return body


async def fetch_day(day: date) -> list[Disclosure]:
    """그날 접수된 코스피 공시 전부. 하루라도 쪽이 빠지면 DartError — 일부만 저장하지 않는다."""
    key = settings.require_dart()
    items: list[Disclosure] = []
    async with httpx.AsyncClient(timeout=settings.http_timeout_sec) as client:
        page_no, total = 1, 1
        while page_no <= total:
            body = await _page(client, key, day, page_no)
            total = int(body.get("total_page") or 0)
            if total > MAX_PAGES:
                raise DartError(f"{day}: 쪽 수가 비정상이다 ({total})")
            try:
                parsed = parse_list(body["list"])
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                # 외부 필드 값은 오류 메시지에 넣지 않는다.
                reason = "invalid_response: disclosure"
                raise DartError(f"{day:%Y%m%d} p{page_no}: {reason}", reason=reason) from e
            items.extend(parsed)
            page_no += 1
    return items
