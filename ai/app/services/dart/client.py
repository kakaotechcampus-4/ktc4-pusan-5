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
        total_page        성공인데 쪽 수가 숫자가 아니거나, 지금 쪽보다 작거나, MAX_PAGES 를 넘는다
        list              성공인데 list 가 객체 목록이 아니다
        disclosure        공시 행의 필드가 없거나 형식이 다르다(parse_list)

    메시지는 `<위치>: <reason>` 이다. 위치는 날짜·쪽(`20261008 p2`)이고 공시 행이면 몇째 행인지
    붙인다. 외부 필드 값은 넣지 않는다.
    """

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason

    @property
    def kind(self) -> FailureKind:
        return failure_kind(self.reason)


def _error(at: str, reason: str) -> DartError:
    return DartError(f"{at}: {reason}", reason=reason)


def _invalid(at: str, where: str) -> DartError:
    """HTTP 200 인데 응답을 믿을 수 없다. where 는 DartError 의 표에 있는 이름이다."""
    return _error(at, f"invalid_response: {where}")


def _text(row: dict, key: str, at: str, *, optional: bool = False) -> str:
    """공시 행의 문자열 필드. optional 이면 없을 때 "" 다."""
    value = row.get(key)
    if optional and value is None:
        return ""
    if not isinstance(value, str):
        raise _invalid(at, "disclosure")
    return value


def _rcept_dt(value: str, at: str) -> date:
    """접수일 YYYYMMDD → date."""
    if len(value) != 8 or not value.isascii() or not value.isdigit():
        raise _invalid(at, "disclosure")
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:]))
    except ValueError as e:  # 13월·32일처럼 없는 날짜
        raise _invalid(at, "disclosure") from e


def parse_list(rows: list[dict], *, at: str = "list") -> list[Disclosure]:
    """list.json 의 list → Disclosure. 종목코드가 없는 행(비상장 등)은 버린다.

    행의 필드가 없거나 형식이 다르면 DartError(invalid_response: disclosure). 필드는 읽는
    자리에서 검사하므로 이 함수 안의 다른 예외는 응답 문제가 아니라 코드 문제다.
    at 은 메시지 앞에 붙일 위치(날짜·쪽)다.
    """
    items: list[Disclosure] = []
    for index, row in enumerate(rows):
        row_at = f"{at} row {index}"
        stock_code = _text(row, "stock_code", row_at, optional=True).strip()
        if not stock_code:
            continue
        items.append(
            Disclosure(
                rcept_no=_text(row, "rcept_no", row_at),
                corp_code=_text(row, "corp_code", row_at),
                corp_name=_text(row, "corp_name", row_at).strip(),
                stock_code=stock_code,
                report_nm=" ".join(_text(row, "report_nm", row_at).split()),
                flr_nm=_text(row, "flr_nm", row_at).strip(),
                rcept_dt=_rcept_dt(_text(row, "rcept_dt", row_at), row_at),
                rm=_text(row, "rm", row_at, optional=True).strip() or None,
            )
        )
    return items


def _read_page(body: dict, at: str, page_no: int) -> tuple[int, list[Disclosure]]:
    """성공(000) 응답 본문의 형식을 검사해 (쪽 수, 공시) 로."""
    # 성공인데 쪽 수가 없으면 1쪽에서 멈춰 나머지 쪽을 빠뜨린다. 쪽 수는 정수나 숫자 문자열이고
    # 지금 쪽 이상이어야 한다. bool 은 int 의 하위형이라, "²" 는 isdigit 이 참이라 따로 막는다.
    total = body.get("total_page")
    if (isinstance(total, bool) or not isinstance(total, (int, str))
            or (not str(total).isascii() or not str(total).isdigit())
            or not page_no <= int(total) <= MAX_PAGES):
        raise _invalid(at, "total_page")
    rows = body.get("list")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise _invalid(at, "list")
    return int(total), parse_list(rows, at=at)


async def _page(
    client: httpx.AsyncClient, key: str, day: date, page_no: int,
) -> tuple[int, list[Disclosure]]:
    """한 쪽을 받아 (쪽 수, 공시) 로. 전송과 DART 상태 코드를 보고, 본문 형식은 _read_page 가 본다."""
    ymd = day.strftime("%Y%m%d")
    at = f"{ymd} p{page_no}"
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
        raise _error(at, http_error(e.response.status_code)) from e
    except httpx.HTTPError as e:
        raise _error(at, f"request_failed: {type(e).__name__}") from e
    try:
        body = resp.json()
    except ValueError as e:  # JSONDecodeError·UnicodeDecodeError 둘 다 ValueError 다
        raise _invalid(at, "not_json") from e
    if not isinstance(body, dict):
        raise _invalid(at, "not_object")
    status = body.get("status")
    if not isinstance(status, str) or not status:
        raise _invalid(at, "status")
    if status == _STATUS_EMPTY:
        return 0, []
    if status != _STATUS_OK:
        # 키를 메시지에 남기지 않는다
        raise _error(at, f"{dart_status(status)} ({body.get('message')})")
    return _read_page(body, at, page_no)


async def fetch_day(day: date) -> list[Disclosure]:
    """그날 접수된 코스피 공시 전부. 하루라도 쪽이 빠지면 DartError — 일부만 저장하지 않는다."""
    key = settings.require_dart()
    items: list[Disclosure] = []
    async with httpx.AsyncClient(timeout=settings.http_timeout_sec) as client:
        page_no, total = 1, 1
        while page_no <= total:
            total, parsed = await _page(client, key, day, page_no)
            items.extend(parsed)
            page_no += 1
    return items
