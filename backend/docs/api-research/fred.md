# FRED (연준 경제데이터) API 스펙 조사

조사일: 2026-09-11
대상: 종목 브리핑에 참고할 미국 시장 지표(글로벌 요인) 수집 — KRX(국내 시세)와 별도 소스
실호출 스크립트: `docs/api-research/scripts/test_fred_detailed.py`
요청/응답 원문: `docs/api-research/raw/fred/*.json` (전부 실제 호출 결과, API 키는 `***REDACTED***` 처리)

## 0. 겹치는 후보에 대한 선택 (사용자 확인 완료)

FRED에는 "나스닥"과 "달러인덱스"에 해당하는 시리즈가 여러 개 있어서, 실호출로 스펙을 비교한 뒤 사용자 확인을 받고 아래로 확정함.

| 구분 | 후보 | 선택 | 근거 |
|---|---|---|---|
| 나스닥 | `NASDAQCOM`(종합, 1971~) vs `NASDAQ100`(상위 100종목, 1986~) | **`NASDAQCOM`** | 요청 표에 "나스닥·S&P500 — 미국 증시 전반"이라 되어있어, 나스닥 상장 전체 종목을 담는 종합지수가 "시장 전반" 취지에 더 맞음. `NASDAQ100`은 금융업 제외 대형 기술주 100개로 SOX(반도체지수)와 성격이 겹침 |
| 달러인덱스 | `DTWEXBGS`(Broad, 26개국) vs `DTWEXAFEGS`(선진국만) vs `DTWEXEMEGS`(신흥국만) | **`DTWEXBGS`** | 연준이 직접 계산·발표하는 헤드라인 달러지수. 언론에서 "달러인덱스"를 연준 기준으로 언급할 때 가리키는 지표가 이것. AFEGS/EMEGS는 하위 분해 지표라 일반적 용도엔 과함 |

> **참고**: 언론·트레이딩에서 흔히 쓰는 **ICE DXY(달러인덱스)는 FRED에 아예 없다.** ICE(Intercontinental Exchange)가 독자 운영하는 상업 지수라 연준 통계에 포함되지 않음. DXY는 6개 통화(EUR·JPY·GBP·CAD·SEK·CHF)만 고정 가중치로 쓰는 반면, `DTWEXBGS`는 26개국 통화를 교역 비중으로 갱신하며 계산 — **수치가 서로 다르게 움직일 수 있음**. 화면에 "달러인덱스"로 표시할 때 이 차이를 인지하고 있어야 함(필요시 출처를 "연준 광범위 달러지수"로 명시하는 걸 권장).

## 1. 개요

| 항목 | 내용 |
|---|---|
| 제공기관 | Federal Reserve Bank of St. Louis |
| 포털 | https://fred.stlouisfed.org/ |
| Base URL | `https://api.stlouisfed.org/fred` |
| HTTP Method | GET |
| 이용 제약 | 상업적 이용 가능 (FRED Terms of Use 준수) |

## 2. [인증]

| 항목 | 실측/문서 확인 결과 |
|---|---|
| 토큰 발급 방식 | **OAuth 같은 토큰 발급 절차 없음.** `fredaccount.stlouisfed.org` 가입 후 My Account > API Keys 에서 32자 소문자 영숫자 문자열의 **정적 API 키**를 즉시 발급받음 |
| 인증 방식 | 헤더가 아니라 **쿼리 파라미터 `api_key`**로 전달 (`?api_key=...`) — Authorization 헤더 사용 안 함 |
| 유효기간 | 공식 문서(`docs/api/api_key.html`)에 만료 관련 언급 없음. 2026-09-08에 발급받은 키가 2026-09-11 현재도 정상 동작 — **만료 없이 계속 쓰는 방식으로 추정**(공식 문서에 명시적 확인 문구는 없음, 4절 "미해결" 참고) |
| 갱신 절차 | 문서에 갱신(rotate) 절차 언급 없음. 애플리케이션별로 별도 키를 새로 발급받는 방식만 안내됨("Developers should request a distinct API key for each application") |
| 키 발급 자체의 호출 제한 | 키 발급은 웹 콘솔에서 하는 1회성 액션이라 API 호출이 아님 — 해당 없음 |

## 3. [요청]

| 항목 | 실측 결과 |
|---|---|
| 필수 헤더 | **없음.** `api_key`가 헤더가 아니라 쿼리 파라미터라서 커스텀 헤더가 전혀 필요 없음(`User-Agent`도 필수 아님, 테스트에서 임의값 넣어도 정상 동작) |
| 조회 단위 | **단건만 가능.** `series_id`에 콤마로 여러 개(`DGS10,DGS2`)를 넣어봤더니 `400 Bad Request` — "Series IDs should be 25 or less alphanumeric characters" 에러. 시리즈마다 개별 호출 필요 (`docs/api-research/raw/fred/09_batch_series_id_test.json`) |
| 기간 조회 최대 건수 | `limit` 파라미터 범위 1~100000 (기본 100000). DGS10 전체 이력(1962~) 조회 시 `count: 16877`로 한 번의 응답 최상위 필드에 총 건수가 옴 — 이 스코프(최신 값 1~수개)에서는 페이지 제한에 걸릴 일 없음 |
| 페이지네이션 동작 | `limit`+`offset`으로 커서 이동. `offset=0,limit=5` 이후 `offset=5,limit=5`를 호출하면 정확히 이어지는 다음 5건이 옴(중복·누락 없음) — 실호출로 검증 (`04_pagination_offset0.json`, `04_pagination_offset5.json`) |

## 4. [응답]

| 항목 | 실측 결과 |
|---|---|
| 성공/실패 판별 | 성공 시 최상위에 `observations`(또는 `seriess`) 배열 키 존재. 실패 시 `error_code`/`error_message` 키만 있고 데이터 키 없음 — **HTTP 상태 코드 + 키 존재 여부 둘 다로 판별 가능** |
| "데이터 없음" vs "에러" | **HTTP 상태로 구분됨.** 유효한 요청인데 결과가 없으면(예: 주말만 포함된 기간 조회) **HTTP 200 + `count: 0` + `observations: []`** — 에러가 아님. 반면 잘못된 파라미터(키 오류, 시리즈 ID 오류, 필수 파라미터 누락)는 전부 **HTTP 400 + `error_code`/`error_message`**. 실측: `07_weekend_only_range.json`(정상 빈 응답) vs `05_error_*.json`(에러) |
| 에러코드 | 실측된 것: `400`(api_key 미등록/series_id 형식 오류/필수 파라미터 누락 — 셋 다 같은 400, 메시지만 다름). 공식 문서(`fred/errors.html`) 기준 전체 목록: **400**(Bad Request), **404**(Not Found), **423**(Locked), **429**(Too Many Requests — 분당 120건 초과 시), **500**(Internal Server Error). 429/500/423은 이번 조사에서 실제로 재현은 못 함(6절 요청 제한 실측 참고) |
| 필드 타입 | `observations[].value`는 **문자열**(숫자도 `"11735.26"` 형태) — 캐스팅 필요. 결측치는 문자열 `"."` |
| 등락률(부호) | FRED가 등락률을 직접 주는 필드는 없음. `units=pch` 쿼리 파라미터를 쓰면 전일 대비 변화율을 계산해서 줌 — 실측 예시(`08_units_pch_NASDAQSOX.json`): 하락은 `"-2.65813"`(마이너스 부호 포함), 상승은 `"0.36550"`(플러스 부호 없음, 숫자만). **주의**: `pch`는 전일 값이 필요한데 전일이 휴장(`.`)이면 당일 `pch`도 `.`로 연쇄 결측됨(9/7 휴장 → 9/8 pch도 `.`) — 등락률을 FRED에 맡기지 않고 백엔드가 연속 두 관측치의 원본 레벨 값으로 직접 계산하는 게 더 안전함(루트 CLAUDE.md의 "가공하지 않은 원본 값" 규약과도 맞음: 등락률 자체가 이미 가공이므로, 이 계산은 어차피 백엔드/프론트 중 누가 할지 별도 결정 필요) |
| 거래량/거래대금 단위 | **해당 필드 자체가 없음.** FRED가 주는 건 가격/지수/금리 레벨 값뿐이고, 거래량(주/천주)이나 거래대금(원/백만원) 개념은 존재하지 않음 — FRED는 거래소 시세 API가 아니라 거시경제 통계 API이기 때문(요청하신 항목 중 이 부분은 FRED엔 원천적으로 해당 없음) |

## 5. [데이터]

| 항목 | 실측 결과 |
|---|---|
| 지연/갱신 시각 | 시리즈마다 지연 일수가 다르고 고정값이 아님. 2026-09-11(금) 기준 실측: |

| 시리즈 | 최신 관측치 날짜 | 영업일 기준 지연 |
|---|---|---|
| `NASDAQSOX`(SOX) | 2026-09-10 | 1일 |
| `SP500` | 2026-09-10 | 1일 |
| `NASDAQCOM`(나스닥) | 2026-09-10 | 1일 |
| `VIXCLS`(VIX) | 2026-09-09 | 2일 |
| `DGS10`(국채10년) | 2026-09-09 | 2일 |
| `DGS2`(국채2년) | 2026-09-09 | 2일 |
| `DCOILWTICO`(WTI) | 2026-09-09 | 2일 |
| `DCOILBRENTEU`(브렌트) | 2026-09-09 | 2일 |
| `DTWEXBGS`(달러인덱스) | 2026-09-04 | 4일 |

> 이전 조사(2026-09-08 시점) 때도 같은 패턴(SOX/증시 1일, VIX/금리/유가 2일, 달러인덱스가 가장 느림)이 나왔음 — **다만 지연일 자체는 매 조회 시점마다 달라지므로 고정값으로 하드코딩하면 안 됨.** 매 배치마다 `observations[].date`로 실제 지연을 계산해야 함(6절 DB 매핑 메모 참고).

| 항목 | 실측 결과 |
|---|---|
| 휴장일 응답 형태 | **시리즈마다 다르게 동작함 — 일관되지 않음.** 2026-09-07(Labor Day, 월요일 휴장) 실측: |

| 시리즈 | 2026-09-07 값 | 패턴 |
|---|---|---|
| `DGS10` | `"."` | 결측 처리 |
| `DGS2` | `"."` | 결측 처리 |
| `NASDAQSOX` | `"."` | 결측 처리 |
| `DCOILWTICO` | `"."` | 결측 처리 |
| `VIXCLS` | `"15.3"` | **실제 값이 채워짐** |
| `DCOILBRENTEU` | `"104.47"` | **실제 값이 채워짐** |

> 같은 미국 공휴일인데 시리즈에 따라 결측(`.`)으로 오거나 실제 값이 채워져서 옴. 이유는 불명확(원천 데이터 제공기관의 발행 관행 차이로 추정 — 예: VIX는 옵션시장 특성상 별도 계산 방식이 있을 수 있음). **컬렉터에서 "휴장일=무조건 `.`"라고 가정하면 안 되고, 시리즈별로 값 유무를 그대로 신뢰하고 처리해야 함.**

| 항목 | 실측/문서 결과 |
|---|---|
| 수정주가 반영 여부 | **해당 없음.** 이 9개 시리즈는 전부 지수·금리·가격 "레벨" 값이고 개별 종목이 아니라서 액면분할 등에 의한 수정주가 개념이 없음. 지수 자체는 지수 산출기관(Nasdaq, CBOE, S&P 등)이 이미 구성종목 변경을 반영해서 계산한 단일 값이라, FRED 입장에서 "원본 vs 수정" 구분이 존재하지 않음 |
| 지수 코드 체계 | **해당 없음.** KRX의 `IDX_NM`/`IDX_CLSS` 같은 계층적 분류 체계가 없고, `series_id`가 FRED에서 부여하는 평평한(flat) 고유 식별자일 뿐임(예: `NASDAQSOX`, `DGS10`). 시리즈 간 상하위 관계나 코드 규칙성 없음 |
| 업종 코드 체계 | **해당 없음.** 이번에 쓰는 9개 시리즈는 전부 시장 전체/거시 지표라 업종 분류가 없음. (참고: FRED에 업종별 시리즈가 아예 없는 건 아니지만, 이번 조사 대상 범위 밖) |

## 6. [운영]

| 항목 | 실측/문서 결과 |
|---|---|
| 점검 시간대 | **공식 문서·API 문서 인덱스 어디에도 점검/다운타임 일정 안내를 찾지 못함.** FRED는 별도 상태 페이지(status page)도 공개돼 있지 않은 것으로 보임 — 확인 불가 (4절 "아직 못 알아낸 것" 참고) |
| 요청 제한(공식 문서) | `fred/errors.html`에 명시: **분당 120건**, 초과 시 HTTP `429`, "반복 위반 시 일시 차단될 수 있음"이라고 되어 있음 |
| 요청 제한(실측) | **연속 60회 호출(24.05초, 페이스 약 150회/분)에서 전부 200, 이어서 추가 150회 연속 호출(66.85초, 페이스 약 135회/분)에서도 전부 200 — 429를 한 번도 재현하지 못함.** 즉 실측으로는 문서상 "분당 120건"보다 더 관대하게 동작했음(`06_burst_summary.json` 참고). 정확한 상한선은 이번 조사로 확정 못 함 — 실제 배치 설계 시엔 문서값(분당 120건)을 상한으로 잡고 여유 있게 스케줄링하는 게 안전 |

## 7. 최종 엔드포인트 스펙 — `fred/series/observations`

요청받은 9개 지표 전부 **하나의 엔드포인트**(`GET /series/observations`)로 처리. `series_id`만 바뀜.

### 요청 예시 (NASDAQSOX, 최신 3건)

```
GET https://api.stlouisfed.org/fred/series/observations?series_id=NASDAQSOX&api_key=***&file_type=json&sort_order=desc&limit=3
```

### 응답 원문 (그대로)

```json
{
  "realtime_start": "2026-09-11",
  "realtime_end": "2026-09-11",
  "observation_start": "1776-07-04",
  "observation_end": "9999-12-31",
  "units": "lin",
  "output_type": 1,
  "file_type": "json",
  "order_by": "observation_date",
  "sort_order": "desc",
  "count": 3,
  "offset": 0,
  "limit": 3,
  "observations": [
    {"realtime_start": "2026-09-11", "realtime_end": "2026-09-11", "date": "2026-09-10", "value": "11614.17"},
    {"realtime_start": "2026-09-11", "realtime_end": "2026-09-11", "date": "2026-09-09", "value": "11931.32"},
    {"realtime_start": "2026-09-11", "realtime_end": "2026-09-11", "date": "2026-09-08", "value": "11887.87"}
  ]
}
```
(전체 원문: `docs/api-research/raw/fred/02_observations_NASDAQSOX.json`)

### 확정 시리즈 매핑 표

| 기능 | series_id | units(FRED 응답 그대로) | 소스기관 | 실측 지연(영업일) | 요청 예시 raw | 응답 raw |
|---|---|---|---|---|---|---|
| 필라델피아 반도체(SOX) | `NASDAQSOX` | Index | Nasdaq, Inc. | 1일 | `01_series_meta_NASDAQSOX.json` | `02_observations_NASDAQSOX.json` |
| S&P500 | `SP500` | Index | S&P Dow Jones Indices | 1일 | `01_series_meta_SP500.json` | `02_observations_SP500.json` |
| 나스닥 | `NASDAQCOM` | Index Feb 5, 1971=100 | Nasdaq, Inc. | 1일 | `01_series_meta_NASDAQCOM.json` | `02_observations_NASDAQCOM.json` |
| VIX | `VIXCLS` | Index | CBOE | 2일 | `01_series_meta_VIXCLS.json` | `02_observations_VIXCLS.json` |
| 미국채 10년 | `DGS10` | Percent | 연준(H.15) | 2일 | `01_series_meta_DGS10.json` | `02_observations_DGS10.json` |
| 미국채 2년 | `DGS2` | Percent | 연준(H.15) | 2일 | `01_series_meta_DGS2.json` | `02_observations_DGS2.json` |
| 달러인덱스 | `DTWEXBGS` | Index Jan 2006=100 | 연준(H.10) | 4일 | `01_series_meta_DTWEXBGS.json` | `02_observations_DTWEXBGS.json` |
| WTI 유가 | `DCOILWTICO` | Dollars per Barrel | EIA | 2일 | `01_series_meta_DCOILWTICO.json` | `02_observations_DCOILWTICO.json` |
| 브렌트유 | `DCOILBRENTEU` | Dollars per Barrel | EIA | 2일 | `01_series_meta_DCOILBRENTEU.json` | `02_observations_DCOILBRENTEU.json` |

### 공통 요청 파라미터

| 파라미터 | 필수 | 설명 |
|---|---|---|
| `series_id` | ✅ | 위 표의 9개 값 중 하나. 콤마로 여러 개 넣으면 400 에러(단건 전용) |
| `api_key` | ✅ | 발급받은 키 |
| `file_type` | 권장 | `json` (기본값 XML) |
| `sort_order` | 권장 | `desc` — 최신값 우선 |
| `limit` | 권장 | `1`(최신값만) 또는 `3`(전일 대비 계산용 등) |
| `observation_start`/`observation_end` | 선택 | `YYYY-MM-DD`, 기간 조회 시 |

### 공통 응답 필드

| 필드 | 타입(응답상) | 설명 |
|---|---|---|
| `count` | number | 조건에 맞는 전체 관측치 수(페이지네이션과 무관하게 총량) |
| `observations[].date` | string(`YYYY-MM-DD`) | 관측 기준일 — **`asOf`로 쓸 값은 이거지, 오늘 날짜 아님** |
| `observations[].value` | string | 값(숫자도 문자열). 결측 시 `"."` |
| `observations[].realtime_start`/`realtime_end` | string(`YYYY-MM-DD`) | 데이터 개정(revision) 시점 — 시리즈마다 다르게 옴(예: NASDAQSOX는 요청일, SP500은 다른 날짜). **asOf로 쓰면 안 됨**, `date` 필드와 혼동 주의 |

## 8. DB 스키마 매핑 시 주의사항

- `observations[].value`는 항상 문자열 — 저장 전 `float` 캐스팅 필수. `"."`(결측)은 `NULL`로 저장하고 값이 있는 척 `0` 등으로 채우면 안 됨
- `asOf`(루트 CLAUDE.md 규약)는 **`observations[].date`를 그대로 ISO 8601로 변환**해서 씀. 오늘 날짜나 `realtime_start`를 쓰면 안 됨(5절 참고) — 예: WTI를 9/11에 조회해도 최신 관측치가 9/9일이면 `asOf`는 `"2026-09-09"` 기준으로 나가야 함
- 지연일을 DB나 코드에 상수로 박아두지 말 것. 배치가 매번 응답의 `date`로 "오늘과 며칠 차이나는지" 계산해서 써야 함(6절/이전 조사에서도 같은 결론)
- 휴장일 결측(`.`) 여부가 시리즈마다 다르므로(5절), 컬렉터에서 "이 날짜는 휴장이니 전 시리즈 다 결측일 것"이라고 가정한 일괄 스킵 로직을 짜면 안 됨 — 시리즈별 응답을 그대로 신뢰
- 시리즈당 API 호출이 1건씩 필요(배치 불가) — 9개 지표를 한 배치에서 갱신하려면 순차 또는 병렬로 9번 호출. 분당 120건 제한(문서 기준) 대비 여유는 충분
- `units=pch` 등 FRED 내장 변환을 쓰지 말고, 원본 레벨 값(`value`)만 저장한 뒤 등락률 계산은 별도 로직(백엔드든 프론트든, 이번 조사 범위 밖의 설계 결정)에 맡기는 걸 권장 — 원본 값이 있어야 나중에 다른 방식으로도 재계산 가능하고, `pch`는 휴장일 뒤에 연쇄 결측되는 문제가 있음(4절 참고)

## 9. 아직 못 알아낸 것

- API 키의 정확한 만료 여부 — 공식 문서에 명시 문구가 없어 "만료 없음"이라고 단정하지 못함. 발급 후 오래 지나 재확인 필요
- `429`(요청 제한 초과)·`423`(Locked)·`500`(서버 오류) 실제 응답 바디 형태 — 이번 조사에서 210회 연속 호출로도 429를 재현하지 못해 미검증. 문서상 형태(400과 동일하게 `error_code`/`error_message`일 것으로 추정)만 알고 있음
- 점검 시간대 — 공식 문서·상태페이지 어디에도 없어 확인 불가
- VIXCLS/DCOILBRENTEU가 휴장일에 실제 값을 채워 넣는 정확한 이유(원천 데이터 제공기관의 발행 관행) — 이번 조사로는 추정만 가능, CBOE/EIA 쪽 발행 정책까지 확인 필요하면 별도 조사 필요
- 이 서비스가 "달러인덱스"를 DTWEXBGS(연준 기준)로 노출했을 때, 사용자가 익숙한 DXY와 다르게 움직이는 걸 어떻게 안내할지는 API 스펙 밖의 UX/설계 결정 — 별도 논의 필요
