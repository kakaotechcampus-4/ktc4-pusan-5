"""KRX Data Marketplace OPEN API 실호출 검증 스크립트.

backend/.env 의 KRX_AUTH_KEY / KRX_API_BASE_URL 을 읽어
요청받은 4개 기능에 필요한 API ID를 전부 호출 gn, HTTP 상태, 건수, 응답 필드를 확인

실행: uv run python docs/api-research/scripts/test_krx.py
"""

import json
import os
import urllib.error
import urllib.request

ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env")

# API 명 : API ID
ENDPOINTS = {
    "KRX 시리즈 일별시세정보": ("krx_dd_trd", "/idx/krx_dd_trd"),
    "KOSPI 시리즈 일별시세정보": ("kospi_dd_trd", "/idx/kospi_dd_trd"),
    "KOSDAQ 시리즈 일별시세정보": ("kosdaq_dd_trd", "/idx/kosdaq_dd_trd"),
    "유가증권 일별매매정보": ("stk_bydd_trd", "/sto/stk_bydd_trd"),
    "코스닥 일별매매정보": ("ksq_bydd_trd", "/sto/ksq_bydd_trd"),
    "코넥스 일별매매정보": ("knx_bydd_trd", "/sto/knx_bydd_trd"),
    "유가증권 종목기본정보": ("stk_isu_base_info", "/sto/stk_isu_base_info"),
    "코스닥 종목기본정보": ("ksq_isu_base_info", "/sto/ksq_isu_base_info"),
    "코넥스 종목기본정보": ("knx_isu_base_info", "/sto/knx_isu_base_info"),
    "ETF 일별매매정보": ("etf_bydd_trd", "/etp/etf_bydd_trd"),
}


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


def call_krx(base_url, auth_key, path, bas_dd):
    url = f"{base_url}{path}"
    payload = json.dumps({"basDd": bas_dd}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "AUTH_KEY": auth_key,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def main():
    env = load_env(ENV_PATH)
    base_url = env.get("KRX_API_BASE_URL", "https://data-dbg.krx.co.kr/svc/apis")
    auth_key = env.get("KRX_AUTH_KEY", "")

    if not auth_key:
        print("KRX_AUTH_KEY가 비어있습니다. backend/.env를 확인하세요.")
        return

    # 최근 영업일(주말/공휴일 제외 확인 필요 시 값 교체)
    bas_dd = "20260910"

    for name, (api_id, path) in ENDPOINTS.items():
        status, body = call_krx(base_url, auth_key, path, bas_dd)
        rows = body.get("OutBlock_1", []) if isinstance(body, dict) else []
        print(f"=== {name} ({api_id}) — HTTP {status} ===")
        if status != 200:
            print(" ", json.dumps(body, ensure_ascii=False))
        else:
            print(f"  rows: {len(rows)}")
            if rows:
                print("  sample:", json.dumps(rows[0], ensure_ascii=False))
        print()


if __name__ == "__main__":
    main()
