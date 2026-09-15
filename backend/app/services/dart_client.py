import httpx

from app.core.config import settings

BASE_URL = "https://opendart.fss.or.kr/api"


async def fetch_disclosure_list(corp_code: str, bgn_de: str, end_de: str) -> dict:
    """GET /api/list.json — 공시 목록 조회."""
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
        return response.json()


async def fetch_corp_code_zip() -> bytes:
    """GET /api/corpCode.xml — 종목코드 ↔ DART 고유번호 매핑 (zip 바이너리로 응답)."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/corpCode.xml",
            params={"crtfc_key": settings.dart_api_key},
        )
        response.raise_for_status()
        return response.content
