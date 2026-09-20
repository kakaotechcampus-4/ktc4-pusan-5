import httpx

from app.core.config import settings

BASE_URL = "https://opendart.fss.or.kr/api"

_STATUS_OK = "000"
_STATUS_EMPTY = "013"  # 조회된 데이타가 없음


class DartApiError(Exception):
    """DART Open API 호출 실패. 원인 예외는 __cause__ 에 남는다."""


async def fetch_disclosure_list(corp_code: str, bgn_de: str, end_de: str) -> dict:
    # GET /api/list.json : 공시 목록 조회. 
    # status 013(조회된 결과 없음)은 빈 list 반환
    # 그 외 000이 아닌 status는 DartApiError
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/list.json",
                params={
                    "crtfc_key": settings.dart_api_key,
                    "corp_code": corp_code,
                    "bgn_de": bgn_de,
                    "end_de": end_de,
                },
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise DartApiError(f"{corp_code}: HTTP {e.response.status_code}") from e
    except httpx.HTTPError as e:
        raise DartApiError(f"{corp_code}: {type(e).__name__}") from e

    body = response.json()
    status = body.get("status")
    if status == _STATUS_EMPTY:
        return {**body, "list": []}
    if status != _STATUS_OK:
        raise DartApiError(f"{corp_code}: DART status {status} ({body.get('message')})")
    return body


async def fetch_corp_code_zip() -> bytes:
    """GET /api/corpCode.xml — 종목코드 ↔ DART 고유번호 매핑 (zip 바이너리로 응답)."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/corpCode.xml",
            params={"crtfc_key": settings.dart_api_key},
        )
        response.raise_for_status()
        return response.content
