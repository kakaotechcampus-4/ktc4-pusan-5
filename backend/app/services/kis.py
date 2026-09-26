import asyncio
import time
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.core.config import settings
from app.schemas.ranking import ACTIVE_RANKINGS, RankingItem
from app.services.market_data import MarketDataError, Quote, number
from app.services.ranking import parse_ranking


class KisClient:
    """환율·랭킹이 토큰/HTTP 연결/호출 속도 제한을 공유한다."""

    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.token = ""
        self.expires_at = datetime.min.replace(tzinfo=UTC)
        self.lock = asyncio.Lock()
        self.next_request_at = 0.0
        self.auth_retry_at = 0.0

    async def _pace(self) -> None:
        await asyncio.sleep(max(0, self.next_request_at - time.monotonic()))
        self.next_request_at = time.monotonic() + 0.6

    async def _authenticate(self) -> None:
        if not settings.kis_app_key or not settings.kis_app_secret:
            raise MarketDataError("MISSING_KEY")
        if settings.kis_env != "real":
            raise MarketDataError("UNSUPPORTED_ENV")
        if datetime.now(UTC) < self.expires_at:
            return
        if time.monotonic() < self.auth_retry_at:
            raise MarketDataError("AUTH_COOLDOWN")
        # 여러 탭이 동시에 실패해도 토큰 발급은 분당 한 번만 시도한다.
        self.auth_retry_at = time.monotonic() + 60
        await self._pace()
        response = await self.client.post(
            f"{settings.kis_api_base_url}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey": settings.kis_app_key,
                "appsecret": settings.kis_app_secret,
            },
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("access_token"), str):
            raise MarketDataError("INVALID_RESPONSE")
        self.token = body["access_token"]
        self.expires_at = datetime.now(UTC) + timedelta(seconds=int(body["expires_in"]) - 60)

    async def get(self, path: str, tr_id: str, params: dict[str, str]) -> dict:
        async with self.lock:
            await self._authenticate()
            await self._pace()
            response = await self.client.get(
                settings.kis_api_base_url + path,
                headers={
                    "authorization": f"Bearer {self.token}",
                    "appkey": settings.kis_app_key,
                    "appsecret": settings.kis_app_secret,
                    "tr_id": tr_id,
                    "custtype": "P",
                },
                params=params,
            )
            if response.status_code in (401, 403):
                self.expires_at = datetime.min.replace(tzinfo=UTC)
            # 초당 제한 오류는 HTTP 500으로도 반환된다. 다음 요청까지 대기한다.
            try:
                body = response.json()
            except ValueError:
                response.raise_for_status()
                raise MarketDataError("INVALID_RESPONSE") from None
            if not isinstance(body, dict):
                response.raise_for_status()
                raise MarketDataError("INVALID_RESPONSE")
            if body.get("msg_cd") == "EGW00201":
                self.next_request_at = time.monotonic() + 60
            response.raise_for_status()
            if body.get("rt_cd") != "0":
                if body.get("msg_cd") in ("EGW00121", "EGW00123"):
                    self.expires_at = datetime.min.replace(tzinfo=UTC)
                raise MarketDataError("UPSTREAM_ERROR")
            return body

    async def fetch_ranking(self, kind: str) -> list[RankingItem]:
        if kind not in ACTIVE_RANKINGS:
            raise MarketDataError("UNSUPPORTED_RANKING")
        if kind in ("gainers", "losers"):
            body = await self.get(
                "/uapi/domestic-stock/v1/ranking/fluctuation",
                "FHPST01700000",
                {
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_COND_SCR_DIV_CODE": "20170",
                    "FID_INPUT_ISCD": "0000",
                    "FID_RANK_SORT_CLS_CODE": "0" if kind == "gainers" else "1",
                    "FID_INPUT_CNT_1": "0",
                    # 0은 저가 등 다른 기준의 순위. 전일 대비 표시값과 일치하는 1 사용.
                    "FID_PRC_CLS_CODE": "1",
                    "FID_DIV_CLS_CODE": "1",
                    "FID_TRGT_CLS_CODE": "111111111",
                    "FID_TRGT_EXLS_CLS_CODE": "0010011101",
                    "FID_INPUT_PRICE_1": "",
                    "FID_INPUT_PRICE_2": "",
                    "FID_VOL_CNT": "",
                    "FID_RSFL_RATE1": "",
                    "FID_RSFL_RATE2": "",
                },
            )
            return parse_ranking(body["output"], kind)
        body = await self.get(
            "/uapi/domestic-stock/v1/quotations/volume-rank",
            "FHPST01710000",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_COND_SCR_DIV_CODE": "20171",
                "FID_INPUT_ISCD": "0000",
                "FID_DIV_CLS_CODE": "1",
                "FID_BLNG_CLS_CODE": "3" if kind == "tradingValue" else "0",
                "FID_TRGT_CLS_CODE": "111111111",
                # 정리매매, 거래정지, ETF, ETN, SPAC 제외 (KIS의 10자리 제외 마스크).
                "FID_TRGT_EXLS_CLS_CODE": "0010011101",
                "FID_INPUT_PRICE_1": "",
                "FID_INPUT_PRICE_2": "",
                "FID_VOL_CNT": "",
                "FID_INPUT_DATE_1": "",
            },
        )
        return parse_ranking(body["output"])

    async def fetch_flow(self, kind: str):
        from app.schemas.market_flow import FLOW_KINDS
        from app.services.market_flow import parse_flow

        if kind not in FLOW_KINDS:
            raise MarketDataError("UNSUPPORTED_RANKING")
        body = await self.get(
            "/uapi/domestic-stock/v1/quotations/foreign-institution-total",
            "FHPTJ04400000",
            {
                "FID_COND_MRKT_DIV_CODE": "V",
                "FID_COND_SCR_DIV_CODE": "16449",
                "FID_INPUT_ISCD": "0000",
                "FID_DIV_CLS_CODE": "0",
                "FID_RANK_SORT_CLS_CODE": "0" if kind == "flowBuy" else "1",
                # 전체에는 기타 법인이 포함된다. 화면에도 같은 범위를 표시한다.
                "FID_ETC_CLS_CODE": "0",
            },
        )
        return parse_flow(body["output"], kind)

    async def fetch_quote(self) -> Quote:
        today = datetime.now(ZoneInfo("Asia/Seoul")).date()
        body = await self.get(
            "/uapi/overseas-price/v1/quotations/inquire-daily-chartprice",
            "FHKST03030100",
            {
                "FID_COND_MRKT_DIV_CODE": "X",
                "FID_INPUT_ISCD": "FX@KRW",
                "FID_INPUT_DATE_1": (today - timedelta(days=30)).strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": today.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE": "D",
            },
        )
        output = body.get("output2")
        if not isinstance(output, list) or any(not isinstance(row, dict) for row in output):
            raise MarketDataError("INVALID_RESPONSE")
        rows = sorted(
            (row for row in output if row.get("stck_bsop_date")),
            key=lambda row: row["stck_bsop_date"],
            reverse=True,
        )
        if len(rows) < 2:
            raise MarketDataError("NO_DATA")
        # output1 현재가에는 시각이 없으므로 날짜가 붙은 최신 시계열 값으로 표시한다.
        current, previous = number(rows[0]["ovrs_nmix_prpr"]), number(rows[1]["ovrs_nmix_prpr"])
        if previous <= 0:
            raise MarketDataError("INVALID_RESPONSE")
        return Quote(
            current,
            (current - previous) / previous * 100,
            date.fromisoformat(rows[0]["stck_bsop_date"]),
        )
