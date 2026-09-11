"""KIS Developers API 실호출 검증 스크립트.

backend/.env 의 KIS_APP_KEY / KIS_APP_SECRET / KIS_API_BASE_URL / KIS_ENV 를 읽어
OAuth2 토큰을 발급하고, 요청받은 8개 기능에 대응하는 엔드포인트를 호출해
요청/응답 원문을 docs/api-research/raw/kis/ 에 저장한다.

⚠️ chk_holiday(국내휴장일조회)는 원장 시스템과 연결되어 있어 공식 문서가 "가급적 1일 1회 호출"을
권고함 — 이 스크립트에서도 최대 1회만 호출한다.

실행: uv run python docs/api-research/scripts/test_kis.py
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env")
RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "raw", "kis")

SAMPLE_STOCK = "005930"  # 삼성전자 (KIS 공식 예제와 동일한 종목으로 통일)


def load_env(path):
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def save_raw(name, payload):
    path = os.path.join(RAW_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def http_call(method, url, headers, body_dict=None, query=None):
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    data = json.dumps(body_dict).encode("utf-8") if body_dict is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            elapsed = time.monotonic() - start
            resp_body = json.loads(resp.read().decode("utf-8"))
            return resp.status, resp_body, elapsed
    except urllib.error.HTTPError as e:
        elapsed = time.monotonic() - start
        raw = e.read().decode("utf-8")
        try:
            resp_body = json.loads(raw)
        except json.JSONDecodeError:
            resp_body = {"raw_text": raw}
        return e.code, resp_body, elapsed


def redact(headers):
    r = dict(headers)
    for k in ("authorization", "appkey", "appsecret"):
        if k in r:
            r[k] = "***REDACTED***"
    return r


def get_token(base_url, app_key, app_secret):
    url = f"{base_url}/oauth2/tokenP"
    headers = {"Content-Type": "application/json"}
    body = {"grant_type": "client_credentials", "appkey": app_key, "appsecret": app_secret}
    status, resp_body, elapsed = http_call("POST", url, headers, body_dict=body)
    # access_token 자체가 비밀값이므로 raw 저장/화면 출력 어디에도 그대로 남기지 않는다.
    redacted_response = dict(resp_body) if isinstance(resp_body, dict) else resp_body
    if isinstance(redacted_response, dict) and "access_token" in redacted_response:
        redacted_response["access_token"] = "***REDACTED***"
    save_raw(
        "00_token_issue.json",
        {
            "request": {"url": url, "headers": headers, "body": {**body, "appkey": "***", "appsecret": "***"}},
            "status": status,
            "elapsed_sec": round(elapsed, 4),
            "response": redacted_response,
        },
    )
    print(f"[{status}] {elapsed:.3f}s  OAuth2 토큰 발급")
    return status, resp_body


def main():
    env = load_env(ENV_PATH)
    base_url = env.get("KIS_API_BASE_URL", "").rstrip("/")
    app_key = env.get("KIS_APP_KEY", "")
    app_secret = env.get("KIS_APP_SECRET", "")
    kis_env_flag = env.get("KIS_ENV", "")

    if not app_key or not app_secret:
        print("KIS_APP_KEY/KIS_APP_SECRET이 비어있습니다.")
        return

    print(f"설정된 KIS_ENV={kis_env_flag!r}, KIS_API_BASE_URL={base_url!r}")

    status, token_body = get_token(base_url, app_key, app_secret)
    if status != 200:
        print("토큰 발급 실패 — 이후 호출을 진행하지 않음. raw/kis/00_token_issue.json 확인 필요")
        return

    access_token = token_body["access_token"]
    common_headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "custtype": "P",
    }

    manifest = []

    def call(label, tr_id, path, query, save_name, extra_headers=None):
        headers = {**common_headers, "tr_id": tr_id}
        if extra_headers:
            headers.update(extra_headers)
        url = f"{base_url}{path}"
        status, resp_body, elapsed = http_call("GET", url, headers, query=query)
        record = {
            "label": label,
            "tr_id": tr_id,
            "url": url,
            "query": query,
            "request_headers": redact(headers),
            "status": status,
            "elapsed_sec": round(elapsed, 4),
        }
        save_raw(save_name, {"request": record, "response": resp_body})
        manifest.append(record)
        rt_cd = resp_body.get("rt_cd") if isinstance(resp_body, dict) else None
        msg = resp_body.get("msg1") if isinstance(resp_body, dict) else None
        print(f"[{status}] {elapsed:.3f}s  {label} (tr_id={tr_id})  rt_cd={rt_cd} msg1={msg}")
        return status, resp_body

    # 1. 현재가(PER/PBR/EPS/52주 고저)
    call(
        "주식현재가 시세",
        "FHKST01010100",
        "/uapi/domestic-stock/v1/quotations/inquire-price",
        {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": SAMPLE_STOCK},
        "01_inquire_price.json",
    )

    # 2. 투자자 순매수(간단 버전, 3주체)
    call(
        "주식현재가 투자자(3주체)",
        "FHKST01010900",
        "/uapi/domestic-stock/v1/quotations/inquire-investor",
        {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": SAMPLE_STOCK},
        "02_inquire_investor.json",
    )

    # 3. 종목별 투자자매매동향(일별, 상세 다주체)
    call(
        "종목별 투자자매매동향(일별)",
        "FHPTJ04160001",
        "/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily",
        {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": SAMPLE_STOCK,
            "FID_INPUT_DATE_1": "20260910",
            "FID_ORG_ADJ_PRC": "",
            "FID_ETC_CLS_CODE": "",
        },
        "03_investor_trade_by_stock_daily.json",
    )

    # 4. 공매도 일별추이
    call(
        "국내주식 공매도 일별추이",
        "FHPST04830000",
        "/uapi/domestic-stock/v1/quotations/daily-short-sale",
        {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": SAMPLE_STOCK,
            "FID_INPUT_DATE_1": "20260901",
            "FID_INPUT_DATE_2": "20260910",
        },
        "04_daily_short_sale.json",
    )

    # 5. 신용잔고 일별추이
    call(
        "국내주식 신용잔고 일별추이",
        "FHPST04760000",
        "/uapi/domestic-stock/v1/quotations/daily-credit-balance",
        {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_COND_SCR_DIV_CODE": "20476",
            "FID_INPUT_ISCD": SAMPLE_STOCK,
            "FID_INPUT_DATE_1": "20260910",
        },
        "05_daily_credit_balance.json",
    )

    # 6. 종목투자의견(증권사별 의견+목표주가 컨센서스용)
    call(
        "국내주식 종목투자의견",
        "FHKST663300C0",
        "/uapi/domestic-stock/v1/quotations/invest-opinion",
        {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_COND_SCR_DIV_CODE": "16633",
            "FID_INPUT_ISCD": SAMPLE_STOCK,
            "FID_INPUT_DATE_1": "20260801",
            "FID_INPUT_DATE_2": "20260910",
        },
        "06_invest_opinion.json",
    )

    # 7. 종목추정실적
    call(
        "국내주식 종목추정실적",
        "HHKST668300C0",
        "/uapi/domestic-stock/v1/quotations/estimate-perform",
        {"SHT_CD": SAMPLE_STOCK},
        "07_estimate_perform.json",
    )

    # 8. 종목뉴스 제목
    call(
        "종합 시황/공시(제목)",
        "FHKST01011800",
        "/uapi/domestic-stock/v1/quotations/news-title",
        {
            "FID_NEWS_OFER_ENTP_CODE": "2",
            "FID_COND_MRKT_CLS_CODE": "00",
            "FID_INPUT_ISCD": SAMPLE_STOCK,
            "FID_TITL_CNTT": "",
            "FID_INPUT_DATE_1": "20260910",
            "FID_INPUT_HOUR_1": "090000",
            "FID_RANK_SORT_CLS_CODE": "01",
            "FID_INPUT_SRNO": "",
        },
        "08_news_title.json",
    )

    # 9. 국내휴장일조회 — 원장 시스템 부하 이슈로 딱 1회만 호출
    print("\n⚠️ chk_holiday는 원장 시스템 부하 문제로 1회만 호출합니다.")
    call(
        "국내휴장일조회",
        "CTCA0903R",
        "/uapi/domestic-stock/v1/quotations/chk-holiday",
        {"BASS_DT": "20260910", "CTX_AREA_NK": "", "CTX_AREA_FK": ""},
        "09_chk_holiday.json",
    )

    with open(os.path.join(RAW_DIR, "00_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print("\n완료. raw 응답은 docs/api-research/raw/kis/ 에 저장됨.")


if __name__ == "__main__":
    main()
