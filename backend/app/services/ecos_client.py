import httpx

from app.core.config import settings

BASE_URL = "https://ecos.bok.or.kr/api"


async def fetch_statistic_search(
    stat_code: str,
    cycle: str,
    start_date: str,
    end_date: str,
    item_code1: str,
) -> dict:
    """GET /api/StatisticSearch — 통계표코드+항목코드 기준 시계열 조회."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/StatisticSearch/{settings.ecos_api_key}/json/kr/1/100/"
            f"{stat_code}/{cycle}/{start_date}/{end_date}/{item_code1}"
        )
        response.raise_for_status()
        return response.json()


async def fetch_base_rate(start_date: str, end_date: str) -> dict:
    """기준금리 (722Y001 / 0101000, 월 단위)."""
    return await fetch_statistic_search("722Y001", "M", start_date, end_date, "0101000")


async def fetch_usd_krw(start_date: str, end_date: str) -> dict:
    """원/달러 환율 (731Y001 / 0000001, 일 단위)."""
    return await fetch_statistic_search("731Y001", "D", start_date, end_date, "0000001")


async def fetch_cpi(start_date: str, end_date: str) -> dict:
    """소비자물가지수 (901Y009 / 0, 월 단위)."""
    return await fetch_statistic_search("901Y009", "M", start_date, end_date, "0")
