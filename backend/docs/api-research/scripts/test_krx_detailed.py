"""KRX Data Marketplace OPEN API 심층 스펙 조사 스크립트.

FRED 조사(test_fred_detailed.py)와 동일한 깊이로 인증/요청/응답/데이터/운영 항목을
실제 호출로 검증하고, 모든 요청/응답 원문을 docs/api-research/raw/krx/ 에 저장한다.

실행: uv run python docs/api-research/scripts/test_krx_detailed.py
"""

import json
import os
import time
import urllib.error
import urllib.request

ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env")
RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "raw", "krx")

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


def save_raw(name, payload):
    path = os.path.join(RAW_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def timed_call(base_url, path, headers, body_dict):
    url = f"{base_url}{path}"
    payload = json.dumps(body_dict).encode("utf-8") if body_dict is not None else b""
    req = urllib.request.Request(url, data=payload, method="POST", headers=headers)
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


def main():
    env = load_env(ENV_PATH)
    base_url = env.get("KRX_API_BASE_URL", "https://data-dbg.krx.co.kr/svc/apis")
    auth_key = env.get("KRX_AUTH_KEY", "")

    if not auth_key:
        print("KRX_AUTH_KEY가 비어있습니다.")
        return

    manifest = []

    def call(label, path, headers, body_dict, save_name):
        status, resp_body, elapsed = timed_call(base_url, path, headers, body_dict)
        record = {
            "label": label,
            "url": base_url + path,
            "request_headers": {k: ("***REDACTED***" if k == "AUTH_KEY" else v) for k, v in headers.items()},
            "request_body": body_dict,
            "status": status,
            "elapsed_sec": round(elapsed, 4),
        }
        save_raw(save_name, {"request": record, "response": resp_body})
        manifest.append(record)
        rows = resp_body.get("OutBlock_1") if isinstance(resp_body, dict) else None
        row_info = f"rows={len(rows)}" if isinstance(rows, list) else ""
        print(f"[{status}] {elapsed:.3f}s  {label}  {row_info}")
        return status, resp_body

    valid_headers = {"AUTH_KEY": auth_key, "Content-Type": "application/json"}
    bas_dd_recent = "20260910"  # 최근 확인된 영업일(목)
    bas_dd_today = "20260911"  # 오늘(금) — 당일 반영 여부 확인용

    # ── 1. 전체 엔드포인트 존재/타이밍 확인 ──
    print("\n=== 1. 엔드포인트별 존재/타이밍 ===")
    for name, (api_id, path) in ENDPOINTS.items():
        call(
            f"{name} ({api_id})",
            path,
            valid_headers,
            {"basDd": bas_dd_recent},
            f"01_endpoint_{api_id}.json",
        )

    # ── 2. [인증] 에러 케이스 ──
    print("\n=== 2. 인증 에러 케이스 ===")
    call(
        "invalid AUTH_KEY",
        "/sto/stk_bydd_trd",
        {"AUTH_KEY": "INVALID_KEY_0000000000000000000", "Content-Type": "application/json"},
        {"basDd": bas_dd_recent},
        "02_error_invalid_auth_key.json",
    )
    call(
        "missing AUTH_KEY header",
        "/sto/stk_bydd_trd",
        {"Content-Type": "application/json"},
        {"basDd": bas_dd_recent},
        "02_error_missing_auth_header.json",
    )
    call(
        "missing Content-Type header",
        "/sto/stk_bydd_trd",
        {"AUTH_KEY": auth_key},
        {"basDd": bas_dd_recent},
        "02_missing_content_type.json",
    )

    # ── 3. [요청] 파라미터 에러/변형 케이스 ──
    print("\n=== 3. 요청 파라미터 케이스 ===")
    call(
        "missing basDd",
        "/sto/stk_bydd_trd",
        valid_headers,
        {},
        "03_error_missing_basdd.json",
    )
    call(
        "malformed basDd (dash format)",
        "/sto/stk_bydd_trd",
        valid_headers,
        {"basDd": "2026-09-10"},
        "03_error_malformed_basdd.json",
    )
    call(
        "invalid basDd (out of range date)",
        "/sto/stk_bydd_trd",
        valid_headers,
        {"basDd": "20261345"},
        "03_error_invalid_basdd.json",
    )
    call(
        "date-range attempt (strtDd/endDd, 미문서화 파라미터)",
        "/sto/stk_bydd_trd",
        valid_headers,
        {"basDd": bas_dd_recent, "strtDd": "20260901", "endDd": bas_dd_recent},
        "03_daterange_attempt.json",
    )

    # ── 4. [데이터] 당일/휴장일/주말 응답 형태 ──
    print("\n=== 4. 당일/휴장일/주말 응답 ===")
    call(
        "오늘(basDd=today) 조회",
        "/sto/stk_bydd_trd",
        valid_headers,
        {"basDd": bas_dd_today},
        "04_today.json",
    )
    call(
        "주말(토, 20260912) 조회",
        "/sto/stk_bydd_trd",
        valid_headers,
        {"basDd": "20260912"},
        "04_weekend_sat.json",
    )
    call(
        "주말(일, 20260913) 조회",
        "/sto/stk_bydd_trd",
        valid_headers,
        {"basDd": "20260913"},
        "04_weekend_sun.json",
    )
    # 추석 연휴: 9/24(목)·9/25(금) 평일 휴장, 9/23(수)·9/28(월) 전후 영업일
    for d, tag in [
        ("20260923", "전영업일(화요일 아님-수요일)"),
        ("20260924", "추석연휴 1일차(목, 평일휴장)"),
        ("20260925", "추석연휴 2일차(금, 평일휴장)"),
        ("20260928", "연휴후 첫영업일(월)"),
    ]:
        call(
            f"휴장일 케이스: {d} {tag}",
            "/idx/kospi_dd_trd",
            valid_headers,
            {"basDd": d},
            f"04_holiday_{d}.json",
        )

    # ── 5. [운영] 연속 호출 타이밍(일 10,000건 한도 고려해 30회만) ──
    print("\n=== 5. 연속 호출 타이밍 (30회) ===")
    burst_start = time.monotonic()
    burst_results = []
    for i in range(30):
        status, _body, elapsed = timed_call(
            base_url, "/sto/stk_isu_base_info", valid_headers, {"basDd": bas_dd_recent}
        )
        burst_results.append({"seq": i + 1, "status": status, "elapsed_sec": round(elapsed, 4)})
        if status != 200:
            print(f"  #{i + 1}: HTTP {status}")
            break
    burst_total = time.monotonic() - burst_start
    save_raw(
        "05_burst_summary.json",
        {
            "total_requests": len(burst_results),
            "total_elapsed_sec": round(burst_total, 3),
            "results": burst_results,
        },
    )
    print(
        f"  {len(burst_results)}건 완료, 총 {burst_total:.2f}초, 전부 200 여부: "
        f"{all(r['status'] == 200 for r in burst_results)}"
    )

    with open(os.path.join(RAW_DIR, "00_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print("\n완료. raw 응답은 docs/api-research/raw/krx/ 에 저장됨.")


if __name__ == "__main__":
    main()
