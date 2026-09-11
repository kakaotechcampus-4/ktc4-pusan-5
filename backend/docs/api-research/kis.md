# 한국투자증권 KIS Developers API 스펙 조사

조사일: 2026-09-11
대상: 종목별 투자자 순매수·공매도·신용잔고·투자의견/목표주가·추정실적·종목뉴스·현재가·휴장일

> 실호출 스크립트: `docs/api-research/scripts/test_kis.py`
> 요청/응답 원문: `docs/api-research/raw/kis/*.json` (App Key/Secret/Access Token 전부 `***REDACTED***` 처리)
> TR_ID·경로는 공식 GitHub(`koreainvestment/open-trading-api`, `examples_llm/domestic_stock/`)의 실제 예제 코드로 확인 후 전부 실호출로 재검증함.

## 0. ⚠️ 설정 불일치 발견 → 정정 완료 (2026-09-11)

최초 조사 시점엔 `.env`에 `KIS_ENV=real`(실전투자)로 되어 있는데 `KIS_API_BASE_URL=https://openapivts.koreainvestment.com:29443`은 **모의투자(virtual) 도메인**이라 서로 안 맞는 상태였다(공식 코드 주석: `my_url` = 실전 `openapi.koreainvestment.com:9443`, `paper` = 모의 `openapivts.koreainvestment.com:29443`). 당시 확인된 내용:

- 모의투자 도메인 + 이 App Key로 요청받은 8개 기능 전부 정상(200) 호출됨 → 이 키는 실질적으로 모의투자 환경으로 동작 중이었음
- `chk_holiday`(국내휴장일조회, TR `CTCA0903R`)만 `500 {"rt_cd":"1","msg_cd":"EGW02006","msg1":"모의투자 TR 이 아닙니다."}` — 이 TR은 모의투자 도메인에서 아예 지원 안 됨
- 진단 목적으로 같은 키로 실전 도메인에 토큰 발급만 시도했더니 이것도 200으로 성공 → **App Key/Secret 자체는 도메인에 종속되지 않고, 실전/모의 여부는 도메인+TR_ID 조합으로 결정됨**

**→ `.env`의 `KIS_API_BASE_URL`을 `https://openapi.koreainvestment.com:9443`(실전)으로 수정 완료.** 이후 **9개 엔드포인트 전부(요청받은 8개 + `chk_holiday`) 실전 도메인으로 재검증 완료 — 전부 200/`rt_cd="0"`.** 모의투자 대비 유일한 차이였던 `chk_holiday`도 실전에서는 정상 동작함(7.8절에 실제 응답 반영).

**⚠️ 운영 주의**: 공식 코드 주석에 "토큰 발급 시 무조건 카카오톡 알림톡이 계좌 소유자에게 발송된다"고 되어 있음. 이번 조사 전체에서 토큰 발급을 여러 차례 호출함(모의투자 스크립트 1회, 실전 도메인 진단 1회, 버스트 테스트 재사용 확인 1회, 도메인 수정 후 실전 재검증 1회) — **테스트/개발 중에는 토큰을 캐싱해서 재사용하고, 불필요하게 재발급 호출을 반복하지 말 것.** (토큰은 "6시간 이내 재요청 시 기존 토큰과 동일한 값 반환"이라 재발급 자체는 안전하지만, 그래도 알림 스팸을 유발함)

## 1. 개요

| 항목 | 내용 |
|---|---|
| 포털 | https://apiportal.koreainvestment.com/ |
| Base URL | 실전 `https://openapi.koreainvestment.com:9443` / 모의 `https://openapivts.koreainvestment.com:29443` |
| HTTP Method | 조회성 API는 전부 **GET** (쿼리 파라미터) |
| 공식 예제 저장소 | https://github.com/koreainvestment/open-trading-api (`examples_llm/domestic_stock/`) |

## 2. [인증]

| 항목 | 실측 결과 |
|---|---|
| 토큰 발급 방식 | OAuth2 Client Credentials. `POST /oauth2/tokenP`, body `{"grant_type":"client_credentials","appkey":...,"appsecret":...}`, 헤더는 `Content-Type: application/json`만 필요(인증 헤더 불필요 — 발급 전이므로 당연함) |
| 응답 필드 | `access_token`(JWT), `access_token_token_expired`(만료 일시, `YYYY-MM-DD HH:MM:SS`), `token_type`(`Bearer`), `expires_in`(초, 실측 `86400`=1일) |
| 유효기간 | **1일(86400초)**. 만료 전 6시간 이내 재요청 시 새 토큰을 안 만들고 **기존 토큰 값을 그대로 반환**(공식 코드 주석 기준, 이번 조사에서 실제 재요청 간격이 6시간이 안 돼서 직접 재현은 못 함) |
| 갱신 절차 | 별도 refresh token 없음 — 만료되면 동일한 `/oauth2/tokenP`를 다시 호출해서 재발급받는 방식(=사실상 "재발급"이 곧 "갱신") |
| 토큰 발급 자체의 호출 제한 | 문서상 명시된 수치는 못 찾음. **다만 발급마다 계좌 소유자에게 카카오톡 알림이 무조건 발송된다는 점이 중요한 제약** — 잦은 재발급을 피해야 함(0절 참고) |
| 인증 성공 후 요청 헤더 | 모든 API 호출에 `authorization: Bearer <token>`, `appkey`, `appsecret`, `tr_id`(API별 고유), `custtype: P`(개인) 필요 |
| 실전/모의 TR_ID 치환 규칙 | 공식 예제 코드에 따르면 TR_ID가 `T`/`J`/`C`로 시작하면 모의투자 시 첫 글자를 `V`로 바꿔야 하는 케이스가 있음(주문류 TR에 흔함). 이번에 조사한 조회성 TR_ID는 전부 `F`/`H`로 시작해 이 규칙 대상이 아니었고, 유일하게 `C`로 시작하는 `CTCA0903R`(휴장일)은 이 규칙이 아니라 **아예 모의투자 자체를 지원 안 함**(0절) |

## 3. [요청]

| 항목 | 실측 결과 |
|---|---|
| 필수 헤더 | `authorization`, `appkey`, `appsecret`, `tr_id` — 이번 조사에서 전부 갖춰서 호출했고, 하나라도 빠뜨렸을 때의 동작은 별도 테스트 안 함(4절 미해결 참고) |
| 조회 단위 | **단건(종목코드 하나) 전용.** 모든 엔드포인트가 `FID_INPUT_ISCD` 또는 `SHT_CD` 파라미터 하나로 종목 하나만 지정. 여러 종목을 한 번에 조회하는 배치 API는 이번 조사 대상에 없음(순위분석류 별도 API가 있을 수 있으나 미조사) |
| 기간 조회 최대 건수 | API마다 다름: `daily-credit-balance`는 "한 번의 호출에 최대 30건"(공식 docstring 명시). `daily-short-sale`/`invest-opinion`은 시작~종료일 범위를 줘도 되지만 최대 건수 문서화는 못 찾음(이번 조사에서 실제로 온 건수: `invest-opinion` 3건, `daily-short-sale`/`daily-credit-balance`는 응답에 여러 날짜가 배열로 옴) |
| 연속조회(페이지네이션) | **`tr_cont` 헤더 + 응답의 `CTX_AREA_FK`/`CTX_AREA_NK`(또는 헤더의 `tr_cont`가 `M`/`F`)로 이어받는 방식.** `chk_holiday`/`daily-credit-balance`/`investor-trade-by-stock-daily`/`invest-opinion`/`news-title`/`estimate-perform` 전부 공식 예제 코드에 이 재귀 방식이 구현돼 있음 — KRX(페이지네이션 아예 없음)나 FRED(`limit`/`offset`)와는 다른 방식. **`chk_holiday` 실호출로 구조 확인**: 응답에 `ctx_area_nk`/`ctx_area_fk`가 실제로 채워져서 오고 "조회가 계속됩니다" 안내 메시지가 붙음(7.8절) — 이 값을 다음 요청의 `CTX_AREA_NK`/`CTX_AREA_FK`에 그대로 넣으면 이어받을 수 있는 구조로 보이나, 실제로 다음 페이지까지 따라가서 확인하진 않음(9절) |

## 4. [응답]

| 항목 | 실측 결과 |
|---|---|
| 성공/실패 판별 필드 | **`rt_cd`**("0"=성공, 그 외=실패) — 모든 API 공통. KRX/FRED와 달리 HTTP 상태코드가 아니라 **응답 바디 안의 `rt_cd`로 판별**해야 함(단, 이번 조사에서 실패 케이스는 HTTP 상태도 같이 바뀜 — `chk_holiday` 실패 시 HTTP `500`) |
| 에러코드 | 실측된 것: `msg_cd="EGW02006"`, `msg1="모의투자 TR 이 아닙니다."`(`chk_holiday`를 모의투자 도메인에 호출했을 때). 그 외 에러코드는 재현 못 함 |
| "데이터 없음"과 "에러" 구분 | `rt_cd`로 명확히 구분됨 — 정상 조회인데 데이터가 없으면 `rt_cd="0"` + 빈 `output`(추정, 이번 조사에선 전부 데이터가 있는 종목만 조회해서 직접 재현은 못 함) |
| 필드 타입 | KRX와 동일하게 **숫자도 전부 JSON 문자열**(`"259500"`, `"-3.53"`) — 캐스팅 필요 |
| 응답 envelope 구조 | API마다 다름: 단일 객체는 `output`, 두 블록은 `output1`+`output2`(예: 공매도, 신용잔고, 투자자매매동향), 네 블록까지 있는 것도 있음(`estimate-perform`의 `output1~4`) — **엔드포인트마다 구조가 달라서 공통 파서를 만들기 어려움, 개별 대응 필요** |
| **응답 필드가 그 자체로 자기서술적이지 않은 경우 있음** | `estimate-perform`(추정실적)의 `output2`/`output3`은 `data1~data5`라는 **무의미한 제네릭 필드명**으로 오고, 실제 어떤 재무 지표(매출액/영업이익/EPS 등)인지는 응답에 안 담겨 있음 — `output4`가 `dt`(연도: `2023.12`~`2027.12E`)로 컬럼 헤더 역할만 하고, **행(row)이 무슨 지표인지는 API 문서 밖에서 알아내야 함**(6.7절 미해결로 표시) |

## 5. [데이터]

| 항목 | 실측 결과 |
|---|---|
| 지연/갱신 시각 | `inquire_investor`(투자자 3주체) 공식 docstring에 명시: **"당일 데이터는 장 종료 후 제공됩니다."** 이번 실호출(장중 여부 불명확한 시점)에서 최신 행이 `stck_bsop_date="20260911"`(당일)로 왔지만, 정확히 몇 시부터 반영되는지는 실측 못 함 |
| 신용잔고의 D+2 특성 | **실측으로 정확히 확인됨.** `daily-credit-balance` 응답에 `deal_date`(체결일자)=`"20260908"`, `stlm_date`(결제일자)=`"20260910"`이 같은 행에 있음 — 체결일과 결제일 사이 정확히 2 영업일 차이(사용자 요청의 "D+2 지연"과 일치). 서비스에서 "이 신용잔고는 며칠 전 체결분"이라고 보여주려면 `deal_date`를 `asOf`로 써야 함(오늘 날짜나 `stlm_date`가 아니라) |
| 휴장일 응답 형태 | **실전 도메인에서 검증 완료(7.8절).** `bzdy_yn`(영업일여부)이 주말·공휴일 전부 `N` — 추석 연휴(2026-09-24~27)가 정확히 `N`으로 나와 실제 캘린더와 일치 확인. KRX처럼 "행 자체가 사라지는" 방식이 아니라 **모든 날짜가 다 나오고 `Y`/`N` 플래그로 구분**되는 방식이라 오히려 KRX보다 다루기 쉬움(주말이든 휴장일이든 요청한 날짜 범위의 모든 날짜가 응답에 포함됨) |
| 수정주가 반영 여부 | `investor-trade-by-stock-daily`의 `FID_ORG_ADJ_PRC`(수정주가 원주가 가격) 파라미터가 존재 — **이 API는 수정주가 여부를 선택할 수 있는 파라미터가 있다는 뜻.** 이번 조사에서 공란으로 보냈을 때의 기본 동작(수정주가 적용 여부)은 확인 못 함(7절 미해결) |
| 종목코드 표기 불일치 | `estimate-perform`의 `output1.sht_cd`가 `"A005930"`(접두 `A` 포함)으로 오는데, 다른 API들은 전부 `"005930"`(접두 없음)로 옴 — **API마다 종목코드 포맷이 다름**, DB 조인 시 주의 필요(KRX 조사에서 발견한 `ISU_CD` 형식 불일치와 유사한 함정) |
| 투자의견 텍스트 비표준화 | `invest-opinion`의 `invt_opnn`(투자의견) 값이 증권사마다 **"매수"/"Buy"/"BUY"**로 제각각 옴(실측: 같은 의미인데 한글/영문 초성/영문 대문자 3가지 형태 confirmed) — 컨센서스 집계 전에 정규화(대소문자·한영 통일) 로직이 필요함 |

## 6. [운영]

| 항목 | 실측/문서 결과 |
|---|---|
| 점검 시간대 | 이번 조사에서 확인 못 함(별도 조사 필요) |
| 요청 제한(커뮤니티 자료) | 실전 초당 20건, 모의투자는 이보다 낮다는 자료가 있음(정확한 수치는 출처마다 다름, 1차 KIS 조사 때도 "초당 10~20건"으로 불명확했음) |
| 요청 제한(실측) | 토큰 재사용 상태로 `inquire-price`에 연속 10회 호출(0.84초, 페이스 약 710회/분)까지 전부 200 — 최소 이 페이스에서는 문제없음 확인. 정확한 상한선은 이번 조사로 확정 못 함 |
| `chk_holiday` 별도 제약 | 공식 docstring에 "당사 원장서비스와 연관되어 있어 단시간 내 다수 호출시 서비스에 영향을 줄 수 있어 **가급적 1일 1회 호출** 부탁드립니다" — 다른 API와 달리 이 엔드포인트만 명시적으로 호출 빈도 제한 권고가 있음. 배치 스케줄러에 쓸 때 하루 1회만 부르도록 설계할 것 |

## 7. 기능별 엔드포인트 매핑 및 상세 스펙

| 요청 기능 | 명칭 | TR_ID | Path | 결과 |
|---|---|---|---|---|
| 종목별 투자자 순매수(12주체) | 종목별 투자자매매동향(일별) | `FHPTJ04160001` | `/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily` | ✅ 200 |
| 종목별 공매도 | 국내주식 공매도 일별추이 | `FHPST04830000` | `/uapi/domestic-stock/v1/quotations/daily-short-sale` | ✅ 200 |
| 신용잔고 | 국내주식 신용잔고 일별추이 | `FHPST04760000` | `/uapi/domestic-stock/v1/quotations/daily-credit-balance` | ✅ 200 |
| 투자의견·목표주가 | 국내주식 종목투자의견 | `FHKST663300C0` | `/uapi/domestic-stock/v1/quotations/invest-opinion` | ✅ 200 |
| 추정실적 | 국내주식 종목추정실적 | `HHKST668300C0` | `/uapi/domestic-stock/v1/quotations/estimate-perform` | ✅ 200 |
| 종목뉴스 제목 | 종합 시황/공시(제목) | `FHKST01011800` | `/uapi/domestic-stock/v1/quotations/news-title` | ✅ 200 |
| 현재가(PER/PBR/EPS/52주고저) | 주식현재가 시세 | `FHKST01010100` | `/uapi/domestic-stock/v1/quotations/inquire-price` | ✅ 200 |
| 휴장일 | 국내휴장일조회 | `CTCA0903R` | `/uapi/domestic-stock/v1/quotations/chk-holiday` | ✅ 200(모의투자에선 미지원, **실전에서 정상 확인** — 0절) |
| (참고, 미요청) 투자자 3주체 간이버전 | 주식현재가 투자자 | `FHKST01010900` | `/uapi/domestic-stock/v1/quotations/inquire-investor` | ✅ 200(12주체 요구엔 부족 — 7.1절 참고) |

### 7.1 종목별 투자자 순매수(12주체) — `investor-trade-by-stock-daily`

**요청 예시**: `GET /uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily?FID_COND_MRKT_DIV_CODE=J&FID_INPUT_ISCD=005930&FID_INPUT_DATE_1=20260910&FID_ORG_ADJ_PRC=&FID_ETC_CLS_CODE=`
헤더: `tr_id: FHPTJ04160001` + 공통 인증 헤더

**⚠️ 주의: 간단해 보이는 `inquire-investor`(TR `FHKST01010900`)는 3주체(개인/외국인/기관)만 줘서 이번 요구사항엔 부족함.** "12개 주체"는 `investor-trade-by-stock-daily`가 정답.

**응답 원문 (output2, 일부 필드)**:
```json
{
  "stck_bsop_date": "20260910",
  "frgn_ntby_qty": "-5769453",
  "prsn_ntby_qty": "-434111",
  "orgn_ntby_qty": "4266985",
  "scrt_ntby_qty": "4966007",
  "ivtr_ntby_qty": "-1118100",
  "pe_fund_ntby_vol": "194531",
  "bank_ntby_qty": "-82",
  "insu_ntby_qty": "33008",
  "mrbn_ntby_qty": "1014",
  "fund_ntby_qty": "190607",
  "etc_corp_ntby_vol": "1936579",
  "etc_orgt_ntby_vol": "0"
}
```

**주체별 필드 매핑(순매수량 `_ntby_qty`/`_ntby_vol` 기준, 거래대금은 `_ntby_tr_pbmn`/`_ntby_pbmn` 접미사로 별도 존재)**:

| 접두사 | 주체 | 비고 |
|---|---|---|
| `frgn` | 외국인 | `frgn_reg_*`(등록외국인)/`frgn_nreg_*`(비등록외국인)로 세분화된 필드도 별도 존재 |
| `prsn` | 개인 | |
| `orgn` | 기관계 | 아래 6개 항목의 합계로 추정 |
| `scrt` | 증권 | |
| `ivtr` | 투신 | |
| `pe_fund` | 사모펀드 | |
| `bank` | 은행 | |
| `insu` | 보험 | |
| `mrbn` | (추정) 종금/기타금융 | 공식 필드 설명 못 찾음, 영문 축약(merchant bank?)으로 추정 — 미해결 |
| `fund` | 연기금등 | 요청하신 "연기금" 대응 필드로 추정 |
| `etc_corp` | 기타법인 | |
| `etc_orgt` | 기타단체 | |

→ 외국인/개인/기관계(집계)/증권/투신/사모펀드/은행/보험/mrbn/연기금등/기타법인/기타단체 = **정확히 12개 필드 그룹**으로, 요청하신 "12개 주체"와 개수가 일치함. `output1`엔 종목 요약(`stck_prpr`, `prdy_vrss` 등)이 별도로 옴.

### 7.2 종목별 공매도 — `daily-short-sale`

**요청 예시**: `GET .../daily-short-sale?FID_COND_MRKT_DIV_CODE=J&FID_INPUT_ISCD=005930&FID_INPUT_DATE_1=20260901&FID_INPUT_DATE_2=20260910`

**응답 원문 (output2, 1행)**:
```json
{
  "stck_bsop_date": "20260910",
  "stck_clpr": "269000",
  "acml_vol": "22517075",
  "ssts_cntg_qty": "692808",
  "ssts_vol_rlim": "3.08",
  "acml_ssts_cntg_qty": "7203326",
  "acml_ssts_cntg_qty_rlim": "5.21",
  "ssts_tr_pbmn": "184051995500",
  "ssts_tr_pbmn_rlim": "3.05"
}
```

| 필드 | 설명 |
|---|---|
| `ssts_cntg_qty` | 당일 공매도 체결수량(요청하신 "공매도량") |
| `ssts_vol_rlim` | 당일 공매도 거래량 비중(%) — "거래대비 비중" 그대로 |
| `ssts_tr_pbmn` / `ssts_tr_pbmn_rlim` | 공매도 거래대금 / 거래대금 비중(%) |
| `acml_ssts_*` | 누적(기간 내) 공매도 수량/비중 |

요청하신 "공매도량 + 거래대비 비중"이 `ssts_cntg_qty` + `ssts_vol_rlim` 조합으로 정확히 커버됨. 날짜 범위(`FID_INPUT_DATE_1`~`2`) 지정 가능 — KRX와 달리 이 API는 **기간 조회를 지원함**.

### 7.3 신용잔고 — `daily-credit-balance`

**요청 예시**: `GET .../daily-credit-balance?FID_COND_MRKT_DIV_CODE=J&FID_COND_SCR_DIV_CODE=20476&FID_INPUT_ISCD=005930&FID_INPUT_DATE_1=20260910`

**응답 원문 (output, 1행)**:
```json
{
  "deal_date": "20260908",
  "stlm_date": "20260910",
  "whol_loan_new_stcn": "2281800",
  "whol_loan_rdmp_stcn": "3400302",
  "whol_loan_rmnd_stcn": "22110525",
  "whol_loan_rmnd_amt": "480893244",
  "whol_loan_rmnd_rate": "0.36",
  "whol_stln_rmnd_stcn": "10391",
  "whol_stln_rmnd_rate": "0.00"
}
```

| 필드 | 설명 |
|---|---|
| `deal_date` | 체결일자(=실제 신용거래가 일어난 날) |
| `stlm_date` | 결제일자 — **`deal_date`+2영업일로 실측 확인, "D+2 지연"의 근거** |
| `whol_loan_rmnd_stcn`/`whol_loan_rmnd_amt` | 융자잔고 수량/금액 |
| `whol_loan_rmnd_rate` | **융자잔고비율(잔고율)** — 요청하신 "잔고율" |
| `whol_stln_*` | 대주(공매도용 대차) 관련 잔고, 신용융자와 별개 |

한 번 호출에 최대 30건, `FID_INPUT_DATE_1`을 바꿔가며 이어 조회하는 방식(공식 docstring).

### 7.4 투자의견·목표주가 — `invest-opinion`

**요청 예시**: `GET .../invest-opinion?FID_COND_MRKT_DIV_CODE=J&FID_COND_SCR_DIV_CODE=16633&FID_INPUT_ISCD=005930&FID_INPUT_DATE_1=20260801&FID_INPUT_DATE_2=20260910`

**응답 원문 (output, 1행)**:
```json
{
  "stck_bsop_date": "20260907",
  "invt_opnn": "매수",
  "invt_opnn_cls_code": "2",
  "rgbf_invt_opnn": "매수",
  "rgbf_invt_opnn_cls_code": "3",
  "mbcr_name": "미래에셋",
  "hts_goal_prc": "400000",
  "stck_prdy_clpr": "255500",
  "dprt": "-35.12"
}
```

| 필드 | 설명 |
|---|---|
| `mbcr_name` | 증권사명 |
| `invt_opnn` | 투자의견(텍스트) — **증권사마다 "매수"/"Buy"/"BUY"로 형식이 다름(5절), 정규화 필요** |
| `rgbf_invt_opnn` | 직전 투자의견 — 요청하신 "직전의견" |
| `hts_goal_prc` | 목표주가 |
| `dprt` | 괴리율(%, 목표주가 대비 현재가 괴리) |

기간(`FID_INPUT_DATE_1`~`2`) 내 여러 증권사의 의견이 각각 한 행씩 옴 — **이 행들의 `hts_goal_prc` 평균을 내면 컨센서스 목표주가 계산 가능**(사용자 요청과 일치).

### 7.5 추정실적 — `estimate-perform`

**요청 예시**: `GET .../estimate-perform?SHT_CD=005930` (날짜 파라미터 없음, 종목코드만)

**응답 원문**:
```json
{
  "output1": {"sht_cd": "A005930", "item_kor_nm": "삼성전자", "name1": "채민숙", "estdate": "20260730", "rcmd_name": "매수"},
  "output4": [{"dt": "2023.12"}, {"dt": "2024.12"}, {"dt": "2025.12"}, {"dt": "2026.12E"}, {"dt": "2027.12E"}]
}
```

| 블록 | 설명 |
|---|---|
| `output1` | 애널리스트명(`name1`), 추정일자(`estdate`), 추천의견(`rcmd_name`) |
| `output4` | **연도 라벨**(2023~2027, `E` 접미사=추정치) — `output2`/`output3`의 컬럼 헤더 역할 |
| `output2` | `data1~data5`(연도별 값) 6행 — **어떤 재무지표인지 응답에 안 나옴(미해결)** |
| `output3` | `data1~data5` 8행 — 마찬가지로 지표명 불명 |

`sht_cd`가 `"A005930"`(접두 `A` 포함)으로 다른 API와 표기가 다름(5절).

### 7.6 종목뉴스 제목 — `news-title`

**요청 예시**: `GET .../news-title?FID_NEWS_OFER_ENTP_CODE=2&FID_COND_MRKT_CLS_CODE=00&FID_INPUT_ISCD=005930&FID_TITL_CNTT=&FID_INPUT_DATE_1=20260910&FID_INPUT_HOUR_1=090000&FID_RANK_SORT_CLS_CODE=01&FID_INPUT_SRNO=`

**응답 원문 (1건, 40건 중)**:
```json
{
  "cntt_usiq_srno": "2026091008044376375",
  "data_dt": "20260910",
  "data_tm": "080443",
  "hts_pbnt_titl_cntt": "[한경유레카] 애널리스트 출신 방송공자 장우진 대표 강의 오픈...",
  "dorg": "한국경제신문",
  "iscd1": "005930", "kor_isnm1": "삼성전자",
  "iscd2": "", "kor_isnm2": ""
}
```

| 필드 | 설명 |
|---|---|
| `data_dt`/`data_tm` | 작성일자/시각 — 요청하신 "시각" |
| `hts_pbnt_titl_cntt` | 뉴스 제목 |
| `dorg` | 언론사 — 요청하신 "언론사" |
| `iscd1`~`iscd10` / `kor_isnm1`~`10` | **관련종목코드/종목명 최대 10개 — "관련종목 자동 태깅" 요구사항을 그대로 충족** |

### 7.7 현재가(PER/PBR/EPS/52주 고저) — `inquire-price`

**요청 예시**: `GET .../inquire-price?FID_COND_MRKT_DIV_CODE=J&FID_INPUT_ISCD=005930`

**응답 원문 (일부, 80개 필드 중 요청 관련분)**:
```json
{
  "stck_prpr": "259500", "prdy_vrss": "-9500", "prdy_ctrt": "-3.53",
  "per": "39.53", "pbr": "4.05", "eps": "6564.00", "bps": "63997.00",
  "w52_hgpr": "374500", "w52_hgpr_date": "20260619",
  "w52_lwpr": "72100", "w52_lwpr_date": "20250911",
  "whol_loan_rmnd_rate": "0.36", "ssts_yn": "Y"
}
```

요청하신 실시간시세·PER·PBR·EPS·52주고저 전부 `per`/`pbr`/`eps`/`w52_hgpr`/`w52_lwpr` 필드로 정확히 커버됨. 덤으로 `bps`(주당순자산), `whol_loan_rmnd_rate`(신용잔고비율 요약치), `ssts_yn`(공매도 가능 여부)까지 같이 옴 — 이 API 하나로 종목 상세 화면의 상당 부분을 채울 수 있음. **주의: 웹소켓이 아니라 REST 폴링 방식이라 진짜 "실시간"은 아니고, 폴링 주기만큼의 지연이 있음**(공식 문서: "실시간 시세를 원하신다면 웹소켓 API를 활용하세요").

### 7.8 휴장일 — `chk-holiday`

TR `CTCA0903R`. **모의투자 도메인에서 미지원, 실전 도메인에서 실호출 검증 완료(2026-09-11).**

**요청 예시**: `GET .../chk-holiday?BASS_DT=20260910&CTX_AREA_NK=&CTX_AREA_FK=`

**응답 원문 (일부, 전체 23건 중 3건)**:
```json
{
  "ctx_area_nk": "20261003            ",
  "ctx_area_fk": "20260910            ",
  "output": [
    {"bass_dt": "20260910", "wday_dvsn_cd": "05", "bzdy_yn": "Y", "tr_day_yn": "Y", "opnd_yn": "Y", "sttl_day_yn": "Y"},
    {"bass_dt": "20260912", "wday_dvsn_cd": "07", "bzdy_yn": "N", "tr_day_yn": "Y", "opnd_yn": "N", "sttl_day_yn": "N"},
    {"bass_dt": "20260924", "wday_dvsn_cd": "05", "bzdy_yn": "N", "tr_day_yn": "Y", "opnd_yn": "N", "sttl_day_yn": "N"}
  ],
  "rt_cd": "0",
  "msg_cd": "KIOK0500",
  "msg1": "조회가 계속됩니다..다음버튼을 Click 하십시오."
}
```

| 필드 | 설명 |
|---|---|
| `bass_dt` | 기준일자 |
| `wday_dvsn_cd` | 요일구분코드. 실측으로 매핑 확정: `01`=일, `02`=월, `03`=화, `04`=수, `05`=목, `06`=금, `07`=토 |
| `bzdy_yn` | 영업일여부 — 주말·공휴일 전부 `N`. 실측: 추석 연휴(2026-09-24~27, 목~일)가 정확히 `N`으로 나와 실제 한국 공휴일 캘린더와 일치 확인 |
| `opnd_yn` | 개장일여부 — 이번 샘플에서 `bzdy_yn`과 항상 동일하게 옴. 공식 문서가 "주문 가능 여부 확인 시 이 필드 사용" 권장 |
| `sttl_day_yn` | 결제일여부 — 이번 샘플에서 `bzdy_yn`과 동일하게 옴 |
| `tr_day_yn` | 거래일여부 — **이번 샘플에서 주말·휴장일 포함 전부 `Y`로 옴.** `bzdy_yn`/`opnd_yn`과 다른 의미로 보이나 정확한 정의는 미해결(9절) |

**한 번 호출로 기준일 기준 약 3주치(`20260910`~`20261003`, 23일)가 옴.** **페이지네이션 구조 실측 확인**: 응답에 `ctx_area_nk`/`ctx_area_fk`(다음 조회에 그대로 넣을 연속조회 키)가 실제로 채워져서 오고, `msg1`에 "조회가 계속됩니다..다음버튼을 Click 하십시오"라는 안내가 옴 — 요청 파라미터의 `CTX_AREA_FK`/`CTX_AREA_NK`를 응답값 그대로 다음 요청에 채워 넣으면 다음 구간을 이어받는 구조임을 확인함(다만 이번 조사에서 실제로 다음 페이지까지 따라가진 않음, 9절).

⚠️ 공식 docstring 경고대로 이 TR은 원장 시스템과 연결돼 있어 **1일 1회만 호출**했음 — 반복 재현 테스트는 하지 않음.

## 8. DB 스키마 매핑 시 주의사항

- 숫자 필드는 전부 문자열 — 캐스팅 필수(다른 소스와 동일)
- **종목코드 표기가 API마다 다름**: 대부분 `"005930"`(6자리, 접두 없음)이지만 `estimate-perform`만 `"A005930"`(접두 `A`) — 조인 전에 정규화 필요
- **신용잔고의 `asOf`는 `deal_date`(체결일)를 써야 함, `stlm_date`(결제일)이 아님** — 결제일 기준으로 저장하면 실제 신용거래 발생 시점보다 2일 늦은 날짜로 잘못 표시됨
- **투자의견 텍스트(`invt_opnn`)는 저장 전 정규화 필요** — "매수"/"Buy"/"BUY"처럼 표기가 제각각이라 그대로 저장하면 프론트에서 그룹핑/필터링이 깨짐. 다만 루트 CLAUDE.md의 "원본 값 그대로" 규약과 상충할 수 있어, 원본은 그대로 저장하고 정규화는 표시 단계(프론트 또는 별도 매핑 테이블)에서 처리하는 방식을 검토
- `estimate-perform`의 `output2`/`output3`은 지표명이 안 붙어있어 **그대로 저장하면 나중에 무슨 값인지 아무도 못 알아봄** — 저장 전에 반드시 지표명 매핑을 확정해야 함(9절 미해결)
- 휴장일(`chk_holiday`)은 모의투자에서 아예 안 됨 — 배치 스케줄러가 이 API에 의존한다면 반드시 실전 도메인 키로 호출해야 함(0절)
- 토큰은 1일 유효 — DB나 캐시에 저장할 경우 만료시각(`access_token_token_expired`)을 같이 저장해서 만료 전에만 재사용하고, 만료 임박이 아니면 재발급 호출 자체를 하지 말 것(알림톡 스팸 방지, 0절)

## 9. 아직 못 알아낸 것

- `chk_holiday`의 `tr_day_yn`(거래일여부) 필드가 `bzdy_yn`/`opnd_yn`과 정확히 어떻게 다른지 — 실측 샘플에선 주말·휴장일 포함 항상 `Y`로 와서 구분이 안 됨
- `chk_holiday`(및 다른 페이지네이션 지원 API들)의 `CTX_AREA_NK`/`CTX_AREA_FK` 연속조회를 실제로 다음 페이지까지 따라가서 검증하는 것 — 구조는 확인했으나(7.8절) 원장 시스템 부하 경고 때문에 실제 후속 호출은 안 함
- `estimate-perform`의 `output2`/`output3` 각 행이 정확히 어떤 재무지표(매출액/영업이익/순이익/EPS 등)인지 — API 응답 자체에 라벨이 없고 웹서치로도 못 찾음
- `investor-trade-by-stock-daily`의 `mrbn` 필드가 정확히 어떤 주체(추정: 종금/기타금융)인지 공식 명칭 확인 못 함
- 페이지네이션(`tr_cont`=`M`/`F`, `CTX_AREA_FK`/`NK`) 실제 동작 — 이번 조사에선 각 API 첫 페이지만 호출해서 재현 안 함
- `FID_ORG_ADJ_PRC`(수정주가 파라미터)를 공란으로 뒀을 때 기본값이 수정주가 적용인지 아닌지
- 정확한 요청 제한(초당 건수) 상한 — 문서마다 다른 수치, 실측으로도 상한까지 못 밀어붙임(계정 안전을 위해 보수적으로 테스트함)
- 헤더 하나(`appkey`/`appsecret`/`tr_id`)를 빠뜨렸을 때의 정확한 에러 형태 — 이번엔 전부 정상 헤더로만 테스트함
