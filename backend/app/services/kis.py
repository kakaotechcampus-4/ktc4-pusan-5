import asyncio
import time
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.core.config import settings
from app.schemas.ranking import ACTIVE_RANKINGS, RankingItem
from app.services.market_data import MarketDataError, Quote, number
from app.services.ranking import parse_ranking

# 초당 제한(EGW00201)을 받았을 때 같은 요청을 다시 보내는 최대 횟수.
RATE_LIMIT_RETRIES = 2


class KisClient:
    """홈 지표(환율·금·랭킹·수급)와 종목 수집기가 토큰/HTTP 연결/호출 속도 제한을 공유한다.

    모든 KIS 요청은 lock 하나로 토큰 발급·간격·응답 대기·재시도까지 한 건씩 직렬화한다.
    간격을 응답 시간보다 짧게 줄이면 직렬화가 처리량 상한이 되므로, 그때는 다음 요청 시각
    예약만 lock으로 보호하고 HTTP 요청과 재시도 대기는 lock 밖에서 하도록 바꾼다.
    """

    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.token = ""
        self.expires_at = datetime.min.replace(tzinfo=UTC)
        self.lock = asyncio.Lock()
        self.next_request_at = 0.0
        self.auth_retry_at = 0.0

    async def _pace(self) -> None:
        await asyncio.sleep(max(0, self.next_request_at - time.monotonic()))
        self.next_request_at = time.monotonic() + settings.kis_request_interval_seconds

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
        self.expires_at = datetime.now(UTC) + timedelta(
            seconds=int(body["expires_in"]) - 60
        )

    async def get(self, path: str, tr_id: str, params: dict[str, str]) -> dict:
        async with self.lock:
            await self._authenticate()
            for attempt in range(RATE_LIMIT_RETRIES + 1):
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
                try:
                    body = response.json()
                except ValueError:
                    response.raise_for_status()
                    raise MarketDataError("INVALID_RESPONSE") from None
                if not isinstance(body, dict):
                    response.raise_for_status()
                    raise MarketDataError("INVALID_RESPONSE")
                # 초당 제한 오류(EGW00201)는 HTTP 500으로도 온다. 한도 아래에서도 간헐적으로 거부되므로
                # KIS 안내대로 60초 전체 정지 없이 이 요청만 _pace 간격을 지켜 다시 보낸다.
                # 재시도하는 동안 lock을 쥐고 있어 다른 요청은 기다리지만, 최대 재시도 횟수만큼이라 길지 않다.
                if body.get("msg_cd") != "EGW00201" or attempt == RATE_LIMIT_RETRIES:
                    break
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

    async def fetch_market_calendar(self, day: date) -> list[tuple[date, bool]]:
        """국내휴장일조회. 기준일부터 앞으로 24일치(주말 포함)의 개장 여부(opnd_yn)를 준다.

        KIS 안내대로 하루 한 번만 부른다. 연속조회는 하지 않고 첫 페이지만 쓴다.
        """
        body = await self.get(
            "/uapi/domestic-stock/v1/quotations/chk-holiday",
            "CTCA0903R",
            {"BASS_DT": day.strftime("%Y%m%d"), "CTX_AREA_NK": "", "CTX_AREA_FK": ""},
        )
        output = body.get("output")
        if (
            not isinstance(output, list)
            or not output
            or any(not isinstance(row, dict) for row in output)
        ):
            raise MarketDataError("INVALID_RESPONSE")
        days = []
        for row in output:
            raw, opened = row.get("bass_dt"), row.get("opnd_yn")
            if (
                not isinstance(raw, str)
                or len(raw) != 8
                or not (raw.isascii() and raw.isdigit())
                or opened not in ("Y", "N")
            ):
                raise MarketDataError("INVALID_RESPONSE")
            try:
                parsed = date.fromisoformat(raw)  # YYYYMMDD 형식
            except ValueError:
                raise MarketDataError("INVALID_RESPONSE") from None
            days.append((parsed, opened == "Y"))
        return days

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
        if not isinstance(output, list) or any(
            not isinstance(row, dict) for row in output
        ):
            raise MarketDataError("INVALID_RESPONSE")
        rows = sorted(
            (row for row in output if row.get("stck_bsop_date")),
            key=lambda row: row["stck_bsop_date"],
            reverse=True,
        )
        if len(rows) < 2:
            raise MarketDataError("NO_DATA")
        # output1 현재가에는 시각이 없으므로 날짜가 붙은 최신 시계열 값으로 표시한다.
        current, previous = number(rows[0]["ovrs_nmix_prpr"]), number(
            rows[1]["ovrs_nmix_prpr"]
        )
        if previous <= 0:
            raise MarketDataError("INVALID_RESPONSE")
        return Quote(
            current,
            (current - previous) / previous * 100,
            date.fromisoformat(rows[0]["stck_bsop_date"]),
        )

    async def fetch_gold_quote(self, symbol: str) -> Quote:
        """KRX 금시장(금 99.99) 일별 시세. 가격은 원/g 이다."""
        body = await self.get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-price",
            "FHKST01010400",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",
            },
        )
        output = body.get("output")
        if not isinstance(output, list) or any(
            not isinstance(row, dict) for row in output
        ):
            raise MarketDataError("INVALID_RESPONSE")
        rows = sorted(
            (row for row in output if row.get("stck_bsop_date")),
            key=lambda row: row["stck_bsop_date"],
            reverse=True,
        )
        if not rows:
            raise MarketDataError("NO_DATA")
        latest = rows[0]
        # 날짜가 붙은 최신 행의 종가와, KIS 가 주는 전일 대비율(prdy_ctrt)을 그대로 쓴다.
        # 필드가 없을 때도 값이 이상할 때와 같이 INVALID_RESPONSE 가 되도록 .get() 으로 읽는다.
        return Quote(
            number(latest.get("stck_clpr")),
            number(latest.get("prdy_ctrt")),
            date.fromisoformat(latest["stck_bsop_date"]),
        )
