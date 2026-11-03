# market_data fixture

테스트는 이 파일을 MockTransport 로 돌려준다. **전부 2026-10-28 에 실제로 호출한 응답에서 행만 골랐다.**
행 안의 필드는 손대지 않았다.

## KRX (기준일 2026-10-27)

- `krx_kospi_dd_trd.json`: 54행 중 4행.
  - "코스피 (외국주포함)": 가격 칸이 `""` 로 온다. 이 행을 쓰면 안 되는 이유다.
  - "코스피": 종합지수. fetch_kospi 가 고르는 행이다.
  - "전기전자": 전일대비가 `"3,868.34"` 처럼 쉼표가 붙어 왔다. 54행 중 이것 하나였다.
  - "코스피 200 25/50 NTR 지수": 거래량·거래대금·시가총액이 `""` 로 온다.
- `krx_stk_bydd_trd.json`: 940행 중 AJ네트웍스, 삼성전자, DH오토넥스.
  - DH오토넥스는 그날 거래량이 0 이었다(거래정지). 시가·고가·저가 `"0"`, 등락률 `"0.00"` 으로 온다.
    그날 거래량 0 인 25종목이 모두 같은 모양이었다.
- `krx_empty.json`: 일요일(2026-10-25) 응답. 당일(10-28)도 같은 모양이었다.
- `krx_unauthorized_*.json`: 401 응답. "Unauthorized API Call" 은 이용신청 승인 전 실제 응답과 같다.

## ECOS

- `ecos_usd_krw.json`: 2026-10-20~28 응답 7건 중 3건. 자른 만큼 `list_total_count` 도 줄였다.
- `ecos_base_rate.json`: 일 주기(D) 2026-07-01~08-31 응답 62건 중 3건. 7월 16일에 2.5 → 2.75 로 바뀐다.
- `ecos_no_data.json`(INFO-200, 주말 구간), `ecos_invalid_key.json`(INFO-100, 가짜 키)은 응답 그대로다.
- 값은 `"1328"`, `"3"` 처럼 소수점 없이도 온다. ECOS 응답에는 쉼표가 없었다.

실제 응답과 모양이 어긋나는지는 `uv run pytest -m network -s tests/test_market_data_live.py` 로 본다.
