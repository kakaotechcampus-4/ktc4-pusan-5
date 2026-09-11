# KRX Data Marketplace OPEN API 스펙 조사

조사일: 2026-09-11 (2026-09-11 1차 조사에서 심층 재조사, FRED 조사와 동일한 깊이로 진행)
대상: 시세/지수 폴링 수집. 인증/요청/응답/데이터/운영 항목 전부 실호출로 검증

> 실호출 스크립트: `docs/api-research/scripts/test_krx.py`(엔드포인트 존재 확인), `docs/api-research/scripts/test_krx_detailed.py`(인증/요청/응답/데이터/운영 심층 검증)
> 요청/응답 원문: `docs/api-research/raw/krx/*.json` (전부 실제 호출 결과, AUTH_KEY는 `***REDACTED***` 처리)

## 1. 개요

| 항목 | 내용 |
|---|---|
| 포털 | https://openapi.krx.co.kr/ |
| Base URL | `https://data-dbg.krx.co.kr/svc/apis` |
| HTTP Method | POST |
| 비용 | 무료 |

## 2. [인증]

| 항목 | 실측/문서 확인 결과 |
|---|---|
| 토큰 발급 방식 | OAuth 같은 토큰 발급 절차 없음. 포털 가입 → 로그인 → 마이페이지 > API 인증키 신청 → 승인(통상 당일~1일) 후 **정적 AUTH_KEY** 발급 |
| 유효기간 | 발급일로부터 **1년** |
| 갱신 절차 | 공식 문서에 자동 갱신/재발급 절차 명시 없음 — 만료 임박 시 포털에서 재신청하는 방식으로 추정(미검증) |
| 토큰 발급 자체의 호출 제한 | 웹 콘솔에서 하는 1회성 액션이라 API 호출이 아님 — 해당 없음 |
| **키 발급과 API별 이용신청은 별개** | 인증키 하나로는 아무 API도 호출 못 함. 사용할 API ID마다 포털에서 개별 "이용신청" 승인이 필요 — 실측: `knx_isu_base_info`(코넥스 종목기본정보) 하나만 이용신청이 안 되어 있어서 **`401 {"respMsg":"Unauthorized API Call","respCode":"401"}`** (`docs/api-research/raw/krx/01_endpoint_knx_isu_base_info.json`) |
| 인증 실패 응답 | AUTH_KEY 자체가 틀렸거나 헤더가 아예 없으면 **`401 {"respMsg":"Unauthorized Key","respCode":"401"}`** — 위의 "Unauthorized API Call"과 메시지가 달라서, 같은 401이라도 **"키가 틀림" vs "이 API는 승인 안 됨"을 `respMsg` 텍스트로 구분 가능**. 실측: `02_error_invalid_auth_key.json`, `02_error_missing_auth_header.json` |

## 3. [요청]

| 항목 | 실측 결과 |
|---|---|
| 필수 헤더 | `AUTH_KEY`(필수 — 없으면 401). `Content-Type: application/json`은 **없어도 에러 없이 200이 오지만, 결과가 항상 빈 배열**로 옴(`02_missing_content_type.json`) — 서버가 본문을 못 읽어서 파라미터가 비어있는 것처럼 처리되는 것으로 추정. **실무에선 반드시 명시할 것** |
| 조회 단위 | **단건 전용.** 파라미터는 `basDd`(YYYYMMDD) 하나뿐이고, 임의로 `strtDd`/`endDd`(기간 조회를 기대하고 추가한 미문서화 파라미터)를 얹어 호출해봤더니 **조용히 무시되고 `basDd` 하루치만 반환됨**(943건, 요청한 기간과 무관) — 배치/기간 조회 API 자체가 없음. 실측: `03_daterange_attempt.json` |
| 기간 조회 최대 건수 | 해당 없음(단건 조회만 가능하므로 "최대 건수" 개념이 없음). 하루 조회 시 시장 전체가 페이지 제한 없이 한 번에 옴(코스닥 1823건까지 확인) |
| 연속조회(페이지네이션) | **없음.** `limit`/`offset`류 파라미터가 아예 없고, 하루치 전체가 한 응답에 다 담겨서 옴 |

## 4. [응답]

| 항목 | 실측 결과 |
|---|---|
| 성공/실패 판별 필드 | 성공 시 `OutBlock_1`(배열) 키 존재. 인증 실패 시엔 `OutBlock_1` 없이 `respMsg`/`respCode`만 있음 |
| 에러코드 | 실측된 것은 `401`(Unauthorized Key / Unauthorized API Call) **뿐**. 그 외의 모든 "이상한 요청"(파라미터 누락, 형식 오류, 존재하지 않는 날짜)은 에러가 아니라 **`200 {"OutBlock_1": []}`**로 옴 |
| **"데이터 없음"과 "에러"의 구분** | **인증 실패만 명확히 구분되고, 나머지는 전부 구분이 안 됨.** 아래 케이스가 전부 동일하게 `200 + 빈 배열`로 응답됨 — 실무에서 "이 요청이 잘못됐는지 그냥 그날 데이터가 없는지"를 응답만 보고는 알 수 없다는 뜻: |

| 케이스 | 결과 | raw 파일 |
|---|---|---|
| `basDd` 파라미터 자체를 안 보냄 | `200`, 빈 배열 | `03_error_missing_basdd.json` |
| `basDd`를 잘못된 포맷으로 보냄(`"2026-09-10"`, 대시 포함) | `200`, 빈 배열 | `03_error_malformed_basdd.json` |
| `basDd`가 존재하지 않는 날짜(`"20261345"`, 13월) | `200`, 빈 배열 | `03_error_invalid_basdd.json` |
| `basDd`가 미래(응답 데이터가 아직 없는 날) | `200`, 빈 배열 | `04_today.json` (아래 5절) |
| `basDd`가 주말/휴장일(정상적인 "거래 없음") | `200`, 빈 배열 | `04_holiday_past_20260505.json` (아래 5절) |

→ **컬렉터 설계 시 주의**: 빈 배열이 왔다고 "정상적으로 휴장이었다"고 단정하면 안 됨 — 요청 자체가 잘못됐을 가능성을 배제할 수 없음. 최소한 `basDd` 포맷을 클라이언트에서 미리 검증(정규식 `^\d{8}$` 등)해서 이 모호함을 줄여야 함.

| 항목 | 실측 결과 |
|---|---|
| 필드 타입 | 숫자 필드도 전부 **JSON 문자열**(`"−1.42"`, `"422276446"`) — 캐스팅 필요 |
| 등락률(FLUC_RT) 부호 | 하락은 `"-"` 접두 포함(예: `"-1.42"`), 상승은 부호 없이 숫자만(예: `"1.89"`) — FRED의 `pch`와 동일한 표기 관례 |
| 거래량(ACC_TRDVOL) 단위 | **주 단위(원주, 1000주 아님).** 검증: AJ네트웍스 2026-09-10 `ACC_TRDVOL="52491"` — 이 종목의 시가총액·유통 규모 대비 52,491주는 합리적인 하루 거래량. 천주 단위였다면 5,249만 주로 상장주식수(4,525만 주)를 넘어서는 비상식적 수치가 됨 |
| 거래대금(ACC_TRDVAL) 단위 | **원 단위(백만원 아님).** 같은 종목 `ACC_TRDVAL="218465470"`(2억 1,846만 원) — `종가(4180) × 거래량(52,491) = 219,412,380`으로 근사 일치(체결가 분산으로 완전 일치는 아님, 근사치로 검증됨) |
| 시가총액(MKTCAP) 검증 | `MKTCAP = LIST_SHRS × TDD_CLSPRC` 정확히 일치 확인 — `45,252,759 × 4,180 = 189,156,532,620` (실제 응답값과 소수점까지 정확히 같음). **원 단위, 가공 없는 순수 곱셈값**임을 재확인 |

## 5. [데이터]

| 항목 | 실측 결과 |
|---|---|
| 지연/갱신 시각 | `basDd=오늘(2026-09-11)`로 조회하면 **빈 배열** — 당일 데이터는 제공 안 됨. 전영업일(`2026-09-10`)은 943건 정상 제공. 즉 **최소 T+1**(당일 장마감 후 다음 조회 시점부터 반영, 정확한 처리 완료 시각은 미확인) |
| 휴장일 응답 형태 | **과거 확정된 휴장일로 재검증**(2026-05-05 어린이날, 화요일 — 최초 조사 때 실수로 미래 날짜를 써서 무의미한 결과를 얻었던 걸 이번에 과거 확정 휴장일로 교정): |

| 날짜 | 구분 | 응답 |
|---|---|---|
| 2026-05-04(월) | 평일 영업일 | 948건 |
| 2026-05-05(화) | 어린이날(평일 휴장) | **0건** |
| 2026-05-06(수) | 평일 영업일 | 948건 |

→ 휴장일은 KRX 계열 전 API에서 **`200 + 빈 배열`**로 통일되게 옴(4절의 "데이터 없음 vs 에러 구분 안 됨" 문제와 동일한 형태). FRED처럼 특정 필드에 `"."` 같은 결측 마커를 넣는 방식이 아니라, **행 자체가 통째로 없음**

| 항목 | 실측/추정 결과 |
|---|---|
| 수정주가 반영 여부 | **직접 검증하지 못함(미해결).** KRX가 주는 `TDD_CLSPRC`는 그날의 거래소 확정 종가 자체이고, 이 API에 "수정 전/후"를 구분하는 별도 필드나 플래그가 없음. 액면분할·무상증자 같은 이벤트가 있었던 종목의 `LIST_SHRS`가 그 시점부터 어떻게 바뀌는지까지 실제로 비교해보지 못해서, "과거 시계열을 지금 다시 조회해도 분할 반영 전 가격 그대로 나오는지"는 확인이 안 됨 |
| 지수 코드 체계 | **짧은 코드가 없음.** `IDX_CLSS`(계열구분: `KRX`/`KOSPI`/`KOSDAQ`, 3종류뿐) + `IDX_NM`(지수명, 자유 텍스트 — "코스피", "KRX 반도체" 등)의 조합으로만 식별됨. 숫자·영문 코드 체계가 따로 없어서, **DB에서 지수를 식별하려면 `IDX_NM` 문자열을 그대로 자연키로 쓰거나 서비스 자체 내부 enum으로 매핑해야 함**(KRX가 안정적인 코드를 안 주기 때문에 오탈자·명칭 변경에 취약할 수 있음) |
| 업종 코드 체계 | **종목 단위엔 아예 없음.** `stk_isu_base_info` 등 종목 기본정보 API 응답 필드(`ISU_CD`/`ISU_SRT_CD`/`ISU_NM`/`ISU_ABBRV`/`ISU_ENG_NM`/`LIST_DD`/`MKT_TP_NM`/`SECUGRP_NM`/`SECT_TP_NM`/`KIND_STKCERT_TP_NM`/`PARVAL`/`LIST_SHRS`)에 업종 분류 필드가 없음. `SECT_TP_NM`(소속부)은 업종이 아니라 "벤처기업부"/"우량기업부" 같은 **시장 내 등급 구분**임. 업종 정보는 `kospi_dd_trd`/`kosdaq_dd_trd`의 **업종 지수 이름**(화학·전기전자·금융 등, `sector_daily` 집계용)으로만 간접적으로 존재하고, "이 종목이 어느 업종에 속하는지"를 알려주는 개별 종목-업종 매핑은 KRX Open API에 없음 — **필요하면 DART 등 다른 소스에서 별도로 가져와야 함** |

## 6. [운영]

| 항목 | 실측/문서 결과 |
|---|---|
| 점검 시간대 | 공식 안내(포털 FAQ): **원칙상 24시간 365일 운영**하되, 정기점검·시스템 안정화 작업 시 사전 공지 후 일시 중단. 예시 공지: 2026-03-27(금) 18:30~24:00(5.5시간) 전체 서비스 점검. **고정된 정기 점검 요일/시간대는 없고, 그때그때 포털 공지로 확인해야 함** |
| 요청 제한(공식) | AUTH_KEY 1개당 **일 10,000건** |
| 요청 제한(실측) | 연속 30회 호출(16.46초, 페이스 약 109회/분) 전부 200 — 짧은 버스트로는 문제없음 확인. **일 10,000건 한도 자체는 소진 테스트를 하지 않아 실측 못 함**(하루 배치 기준 9~10개 API 호출이면 매우 여유 있음) |

## 7. 엔드포인트별 상세 스펙

### 7.1 공통 요청 형식

```
POST https://data-dbg.krx.co.kr/svc/apis{path}
Headers: AUTH_KEY: <키>, Content-Type: application/json
Body: {"basDd": "YYYYMMDD"}
```

### 7.2 API 목록 및 실측 상태 (2026-09-11, basDd=20260910)

| API 명 | API ID | 경로 | 결과 | 응답시간 | 건수 |
|---|---|---|---|---|---|
| KRX 시리즈 일별시세정보 | `krx_dd_trd` | `/idx/krx_dd_trd` | ✅ 200 | 0.245s | 40 |
| KOSPI 시리즈 일별시세정보 | `kospi_dd_trd` | `/idx/kospi_dd_trd` | ✅ 200 | 0.137s | 51 |
| KOSDAQ 시리즈 일별시세정보 | `kosdaq_dd_trd` | `/idx/kosdaq_dd_trd` | ✅ 200 | 0.111s | 40 |
| 유가증권 일별매매정보 | `stk_bydd_trd` | `/sto/stk_bydd_trd` | ✅ 200 | 1.840s | 943 |
| 코스닥 일별매매정보 | `ksq_bydd_trd` | `/sto/ksq_bydd_trd` | ✅ 200 | 1.709s | 1823 |
| 코넥스 일별매매정보 | `knx_bydd_trd` | `/sto/knx_bydd_trd` | ✅ 200 | 0.108s | 108 |
| 유가증권 종목기본정보 | `stk_isu_base_info` | `/sto/stk_isu_base_info` | ✅ 200 | 0.455s | 943 |
| 코스닥 종목기본정보 | `ksq_isu_base_info` | `/sto/ksq_isu_base_info` | ✅ 200 | 0.784s | 1823 |
| 코넥스 종목기본정보 | `knx_isu_base_info` | `/sto/knx_isu_base_info` | ❌ 401 | 0.074s | — (이용신청 누락) |
| ETF 일별매매정보 | `etf_bydd_trd` | `/etp/etf_bydd_trd` | ✅ 200 | 0.315s | 1168 |

응답 시간은 대체로 **반환 건수(=payload 크기)에 비례** — 코스닥(1823건)이 코넥스(108건)보다 10배 이상 느림.

### 7.3 지수 일별시세 — `krx_dd_trd` / `kospi_dd_trd` / `kosdaq_dd_trd`

**요청 예시**: `POST /idx/kospi_dd_trd` `{"basDd": "20260910"}`

**응답 원문 (일부, KOSPI 종합지수 행)**:
```json
{"BAS_DD":"20260910","IDX_CLSS":"KOSPI","IDX_NM":"코스피","CLSPRC_IDX":"7033.92","CMPPREVDD_IDX":"-17.72","FLUC_RT":"-0.25","OPNPRC_IDX":"7038.85","HGPRC_IDX":"7072.79","LWPRC_IDX":"6898.45","ACC_TRDVOL":"422276446","ACC_TRDVAL":"28927397176014","MKTCAP":"5802329384905229"}
```

| 필드명 | 타입 | 단위 | 설명 |
|---|---|---|---|
| BAS_DD | string | `YYYYMMDD` | 기준일자 |
| IDX_CLSS | string | — | 계열구분(`KRX`/`KOSPI`/`KOSDAQ`) |
| IDX_NM | string | — | 지수명(자유 텍스트, 코드 없음) |
| OPNPRC_IDX/HGPRC_IDX/LWPRC_IDX/CLSPRC_IDX | string(숫자) | 지수 포인트 | 시가/고가/저가/종가 |
| CMPPREVDD_IDX | string(숫자) | 지수 포인트 | 전일대비 |
| FLUC_RT | string(숫자, 부호포함) | % | 등락률 |
| ACC_TRDVOL | string(숫자) | 주 | 거래량 |
| ACC_TRDVAL | string(숫자) | 원 | 거래대금 |
| MKTCAP | string(숫자) | 원 | 상장시가총액 |

**주의**: 각 API의 첫 번째 행("코스피 (외국주포함)")은 가격 필드가 빈 문자열(`""`)로 옴 — `IDX_NM="코스피"`/`"코스닥"` 행(두 번째)을 써야 함. `kospi_dd_trd`/`kosdaq_dd_trd`엔 종합지수 + 표준 업종분류 지수(화학·전기전자·금융 등)가 같이 들어있고, `krx_dd_trd`엔 KRX 계열 업종·테마 지수(KRX 반도체 등)만 있음.

### 7.4 종목 일별매매정보 — `stk_bydd_trd` / `ksq_bydd_trd` / `knx_bydd_trd`

**요청 예시**: `POST /sto/stk_bydd_trd` `{"basDd": "20260910"}`

**응답 원문 (일부)**:
```json
{"BAS_DD":"20260910","ISU_CD":"095570","ISU_NM":"AJ네트웍스","MKT_NM":"KOSPI","SECT_TP_NM":"","TDD_CLSPRC":"4180","CMPPREVDD_PRC":"10","FLUC_RT":"0.24","TDD_OPNPRC":"4175","TDD_HGPRC":"4185","TDD_LWPRC":"4140","ACC_TRDVOL":"52491","ACC_TRDVAL":"218465470","MKTCAP":"189156532620","LIST_SHRS":"45252759"}
```

| 필드명 | 타입 | 단위 | 설명 |
|---|---|---|---|
| BAS_DD | string | `YYYYMMDD` | 기준일자 |
| ISU_CD | string | — | 종목코드(단축코드 6자리, ISIN 아님 — 주의: 7절 참고) |
| ISU_NM | string | — | 종목명 |
| MKT_NM | string | — | 시장구분 |
| SECT_TP_NM | string | — | 소속부(업종 아님, 시장 등급) — 유가증권은 빈 문자열 |
| TDD_OPNPRC/TDD_HGPRC/TDD_LWPRC/TDD_CLSPRC | string(숫자) | 원 | 시가/고가/저가/종가 |
| CMPPREVDD_PRC | string(숫자, 부호포함) | 원 | 전일대비 |
| FLUC_RT | string(숫자, 부호포함) | % | 등락률 |
| ACC_TRDVOL | string(숫자) | 주 | 거래량(4절에서 단위 검증 완료) |
| ACC_TRDVAL | string(숫자) | 원 | 거래대금(4절에서 단위 검증 완료) |
| MKTCAP | string(숫자) | 원 | 시가총액(`LIST_SHRS × TDD_CLSPRC`와 정확히 일치 검증) |
| LIST_SHRS | string(숫자) | 주 | 상장주식수 |

> **`ISU_CD` 표기 주의**: 4.2절 예시처럼 `stk_bydd_trd`의 `ISU_CD`는 `"095570"`(6자리 단축코드)로 오는데, `stk_isu_base_info`(종목기본정보)의 `ISU_CD`는 `"KR7095570008"`(12자리 ISIN)로 온다 — **같은 필드명(`ISU_CD`)인데 API에 따라 담긴 값의 형식이 다름.** 두 API를 조인해서 쓸 계획이면 `stk_bydd_trd.ISU_CD`(6자리) ↔ `stk_isu_base_info.ISU_SRT_CD`(6자리, 단축코드)로 매칭해야 하고, `stk_isu_base_info.ISU_CD`(ISIN)와 직접 비교하면 안 됨. 수급(`price_daily`) 저장 시 이 매핑 실수를 주의할 것.

**수급(투자자별 매매동향) 필드 없음** — `price_daily`의 수급 컬럼은 이 API로 못 채움, 증권사 API로 확인 필요.

### 7.5 종목 기본정보 — `stk_isu_base_info` / `ksq_isu_base_info` / `knx_isu_base_info`

**요청 예시**: `POST /sto/stk_isu_base_info` `{"basDd": "20260910"}`

**응답 원문**:
```json
{"ISU_CD":"KR7095570008","ISU_SRT_CD":"095570","ISU_NM":"AJ네트웍스보통주","ISU_ABBRV":"AJ네트웍스","ISU_ENG_NM":"AJ Networks Co.,Ltd.","LIST_DD":"20150821","MKT_TP_NM":"KOSPI","SECUGRP_NM":"주권","SECT_TP_NM":"","KIND_STKCERT_TP_NM":"보통주","PARVAL":"1000","LIST_SHRS":"45252759"}
```

| 필드명 | 타입 | 단위 | 설명 |
|---|---|---|---|
| ISU_CD | string | — | **ISIN 12자리**(`stk_bydd_trd`의 6자리 `ISU_CD`와 형식 다름, 위 주의사항 참고) |
| ISU_SRT_CD | string | — | 단축코드 6자리(`stk_bydd_trd.ISU_CD`와 매칭되는 값) |
| ISU_NM/ISU_ABBRV/ISU_ENG_NM | string | — | 한글 종목명/약명/영문명 |
| LIST_DD | string | `YYYYMMDD` | 상장일 |
| MKT_TP_NM | string | — | 시장구분 |
| SECUGRP_NM | string | — | 증권구분(예: "주권") |
| SECT_TP_NM | string | — | 소속부 |
| KIND_STKCERT_TP_NM | string | — | 주식종류(예: "보통주") |
| PARVAL | string(숫자) | 원 | 액면가 |
| LIST_SHRS | string(숫자) | 주 | 상장주식수 |

코넥스(`knx_isu_base_info`)는 이용신청 미승인이라 실응답 미검증.

### 7.6 ETF 일별매매정보 — `etf_bydd_trd`

7.4의 필드 + ETF 고유 필드(`NAV`, `IDX_IND_NM`, `OBJ_STKPRC_IDX`, `CMPPREVDD_IDX`, `FLUC_RT_IDX`, `INVSTASST_NETASST_TOTAMT`). 이번 스코프 우선순위 낮음 — 세부 스펙은 이전 조사 결과 유지.

## 8. 기능별 매핑

| 기능 | 필요 데이터 | 사용할 API ID |
|---|---|---|
| 종목 일별 시세 | 시가·고가·저가·종가·등락률·거래량·거래대금·시가총액 | `stk_bydd_trd` + `ksq_bydd_trd` + `knx_bydd_trd` |
| 거래대금 순위 | 커버리지 종목 선정 기준(시총 순보다 급등주 포착에 유리) | 전용 API 없음. `ACC_TRDVAL` 기준 클라이언트 정렬 — 실측(2026-09-08 조사, SK하이닉스>삼성전자>삼성전기 순 확인) |
| 지수 일별 시세 | KOSPI·KOSDAQ 종가·등락률 | `kospi_dd_trd`, `kosdaq_dd_trd` |
| 종목 기본정보 | 종목명·종목코드·ISIN·상장일·상장주식수 | `stk_isu_base_info` + `ksq_isu_base_info` + `knx_isu_base_info`(이용신청 대기) |

## 9. DB 스키마 매핑 시 주의사항

- 숫자 필드는 전부 문자열로 옴 — 저장 전 `int`/`float` 캐스팅 필수(가공 아닌 타입 변환이라 CLAUDE.md 규약 위반 아님)
- **`ISU_CD` 필드가 API마다 형식이 다름**(7.4/7.5절) — `price_daily`와 `stock`(종목 마스터) 테이블을 조인할 외래키를 설계할 때 6자리 단축코드로 통일할지 12자리 ISIN으로 통일할지 먼저 정하고, 어느 쪽이든 매핑 규칙을 명시적으로 문서화할 것
- **빈 배열 응답이 "정상 휴장"인지 "잘못된 요청"인지 API 레벨에서 구분이 안 됨**(4절) — 컬렉터에서 `basDd` 포맷을 보내기 전에 자체 검증하고, 빈 응답이 오면 최소한 "이게 진짜 주말/공휴일인지"를 캘린더로 교차 확인하는 방어 로직을 넣는 게 안전
- 업종 코드가 종목 단위로 없음(5절) — `sector_daily`는 KRX 업종지수로 채울 수 있어도, 개별 종목에 `sector_id` 같은 FK를 붙이려면 KRX 밖의 소스가 필요함. 이번 스코프에 그 요구사항이 있는지 먼저 확인 필요
- `asOf`는 `BAS_DD` 필드를 ISO 8601로 변환해서 사용(루트 CLAUDE.md 규약)
- 당일 데이터는 최소 T+1까지 없음(5절) — 배치를 "오늘자 데이터 갱신"으로 스케줄링하면 안 되고 "전영업일자 데이터 갱신"으로 설계해야 함

## 10. 아직 못 알아낸 것

- API 키 갱신(재발급) 절차의 정확한 방법 — 문서에 명시 없음, 만료 임박 시 실제로 재확인 필요
- 수정주가(액면분할·무상증자) 반영 여부 — 실제 분할 이벤트가 있었던 종목으로 비교 검증 못 함
- 일 10,000건 한도 초과 시 정확한 에러 형태(`429`류로 추정하나 미재현)
- 당일 데이터가 정확히 몇 시에 반영되기 시작하는지(장마감 직후인지, 익일 새벽 배치 후인지)는 실시간 시계열로 오래 관찰해야 확인 가능 — 이번 조사에선 "당일=없음, 전영업일=있음"까지만 확인
