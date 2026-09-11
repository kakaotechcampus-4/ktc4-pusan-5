"""FRED API 심층 스펙 조사 스크립트.

backend/.env 의 FRED_API_KEY / FRED_API_BASE_URL 을 읽어
요청받은 항목(인증/요청/응답/데이터/운영)을 실제 호출로 검증하고,
모든 요청/응답 원문을 docs/api-research/raw/fred/ 에 JSON으로 저장한다.

실행: uv run python docs/api-research/scripts/test_fred_detailed.py
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env")
RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "raw", "fred")

# 요청 대상 + 겹침 후보(비교용)
SERIES_IDS = [
    "NASDAQSOX",
    "SP500",
    "NASDAQCOM",
    "NASDAQ100",  # 나스닥 겹침 후보
    "VIXCLS",
    "DGS10",
    "DGS2",
    "DTWEXBGS",
    "DTWEXAFEGS",  # 달러인덱스 겹침 후보
    "DTWEXEMEGS",  # 달러인덱스 겹침 후보
    "DCOILWTICO",
    "DCOILBRENTEU",
]


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


def timed_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "basis-backend-test/1.0"})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            elapsed = time.monotonic() - start
            body = json.loads(resp.read().decode("utf-8"))
            return resp.status, body, elapsed, dict(resp.headers)
    except urllib.error.HTTPError as e:
        elapsed = time.monotonic() - start
        body = json.loads(e.read().decode("utf-8"))
        return e.code, body, elapsed, dict(e.headers)


def main():
    env = load_env(ENV_PATH)
    base_url = env.get("FRED_API_BASE_URL", "https://api.stlouisfed.org/fred")
    api_key = env.get("FRED_API_KEY", "")

    if not api_key:
        print("FRED_API_KEY가 비어있습니다.")
        return

    manifest = []

    def call(label, endpoint, params, save_name):
        url = f"{base_url}/{endpoint}?{urllib.parse.urlencode(params)}"
        status, body, elapsed, _headers = timed_get(url)
        record = {
            "label": label,
            "url": url.replace(api_key, "***REDACTED***"),
            "status": status,
            "elapsed_sec": round(elapsed, 4),
        }
        save_raw(save_name, {"request": record, "response": body})
        manifest.append(record)
        print(f"[{status}] {elapsed:.3f}s  {label}")
        return status, body

    # ── 1. series 메타데이터 (frequency, units, seasonal_adjustment, notes 등) ──
    print("\n=== 1. series 메타데이터 ===")
    for sid in SERIES_IDS:
        call(
            f"series metadata: {sid}",
            "series",
            {"series_id": sid, "api_key": api_key, "file_type": "json"},
            f"01_series_meta_{sid}.json",
        )

    # ── 2. observations (최신 3건) ──
    print("\n=== 2. observations 최신 3건 ===")
    for sid in SERIES_IDS:
        call(
            f"observations latest: {sid}",
            "series/observations",
            {
                "series_id": sid,
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": "3",
            },
            f"02_observations_{sid}.json",
        )

    # ── 3. 휴장일(공휴일) 응답 형태 확인: 2026-09-07(Labor Day, 월) 전후 조회 ──
    print("\n=== 3. 휴장일 응답 형태 (Labor Day 2026-09-07 전후) ===")
    for sid in ["VIXCLS", "DGS10", "NASDAQSOX"]:
        call(
            f"holiday window: {sid}",
            "series/observations",
            {
                "series_id": sid,
                "api_key": api_key,
                "file_type": "json",
                "observation_start": "2026-09-03",
                "observation_end": "2026-09-09",
            },
            f"03_holiday_window_{sid}.json",
        )

    # ── 4. 페이지네이션(limit/offset) 동작 확인 ──
    print("\n=== 4. 페이지네이션 (limit=5, offset=0/5) ===")
    call(
        "pagination offset=0",
        "series/observations",
        {
            "series_id": "DGS10",
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "asc",
            "limit": "5",
            "offset": "0",
        },
        "04_pagination_offset0.json",
    )
    call(
        "pagination offset=5",
        "series/observations",
        {
            "series_id": "DGS10",
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "asc",
            "limit": "5",
            "offset": "5",
        },
        "04_pagination_offset5.json",
    )

    # ── 5. 에러 케이스 ──
    print("\n=== 5. 에러 케이스 ===")
    call(
        "invalid api_key",
        "series/observations",
        {
            "series_id": "DGS10",
            "api_key": "invalid0000000000000000000000000",
            "file_type": "json",
        },
        "05_error_invalid_key.json",
    )
    call(
        "invalid series_id",
        "series/observations",
        {
            "series_id": "NOT_A_REAL_SERIES_ID",
            "api_key": api_key,
            "file_type": "json",
        },
        "05_error_invalid_series.json",
    )
    call(
        "missing series_id param",
        "series/observations",
        {"api_key": api_key, "file_type": "json"},
        "05_error_missing_param.json",
    )

    # ── 6. 요청 제한 실측: 60회 연속 호출 시간 측정 ──
    print("\n=== 6. 요청 제한 실측 (연속 60회) ===")
    burst_start = time.monotonic()
    burst_results = []
    for i in range(60):
        url = (
            f"{base_url}/series/observations?"
            f"{urllib.parse.urlencode({'series_id': 'DGS10', 'api_key': api_key, 'file_type': 'json', 'limit': '1'})}"
        )
        status, body, elapsed, _headers = timed_get(url)
        burst_results.append({"seq": i + 1, "status": status, "elapsed_sec": round(elapsed, 4)})
        if status != 200:
            print(f"  #{i + 1}: HTTP {status} — rate limit 도달 추정")
            save_raw("06_burst_rate_limit_hit.json", {"seq": i + 1, "response": body})
            break
    burst_total = time.monotonic() - burst_start
    save_raw(
        "06_burst_summary.json",
        {
            "total_requests": len(burst_results),
            "total_elapsed_sec": round(burst_total, 3),
            "results": burst_results,
        },
    )
    print(f"  {len(burst_results)}건 완료, 총 {burst_total:.2f}초 소요, 전부 200 여부: "
          f"{all(r['status'] == 200 for r in burst_results)}")

    with open(os.path.join(RAW_DIR, "00_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print("\n완료. raw 응답은 docs/api-research/raw/fred/ 에 저장됨.")


if __name__ == "__main__":
    main()
