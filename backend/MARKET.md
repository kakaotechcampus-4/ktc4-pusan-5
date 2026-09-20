# 주요 지수 실행

`외부 API → 별도 수집기 → PostgreSQL market_snapshot → GET /api/market/overview → 홈 카드`

## 로컬 실행

backend/.env에 `.env.example`의 FRED, KRX, KIS 키를 입력한다.
프론트는 `frontend/.env`의 `VITE_API_BASE_URL=http://localhost:8000`을 사용한다.

backend/에서 DB, API, 수집기를 실행한다. API와 수집기는 각각 별도 터미널에서 유지한다.

```bash
docker compose up -d db
uv sync --locked
uv run uvicorn app.main:app --reload
```

```bash
uv run python -m app.collectors.market --loop
```

`--loop` 없이 실행하면 갱신 주기가 지난 항목을 한 번 수집하고 종료한다.
배포 시 수집기를 별도 프로세스로 실행/재시작해야 한다. API 요청은 외부 호출을 하지 않는다.
수집기는 DB advisory lock과 `checked_at`으로 중복 실행을 억제한다.

## 저장 구조

기존 프로젝트의 `Base.metadata.create_all()` 방식에 맞춰 API/수집기 시작 시
`market_snapshot` 테이블을 추가한다. 기존 테이블과 데이터는 변경하지 않는다.
이 테이블은 항목별 최신 정상값 1개를 보관하며 과거 시계열 저장소는 아니다.
Alembic 도입 시 이 모델을 마이그레이션 대상에 포함해야 한다.

- code: 고유 키
- value, change: 원본 값과 직전 관측값 대비 등락률(%)
- observation_date: 원천 기준일
- collected_at: 마지막 정상 수집 시각(UTC)
- checked_at: 마지막 시도 시각(UTC)
- error_code: 비밀정보를 포함하지 않는 수집 오류 코드

실패 시 정상값은 보존한다. 이전 기준일 응답으로 값이 되돌아가지 않는다.

## 출처와 주기

| 항목 | 출처 | 수집 확인 주기 |
|---|---|---|
| 코스피 / 코스닥 | KRX 일별 지수 | 1시간 |
| S&P 500 / 나스닥 종합 | FRED SP500 / NASDAQCOM | 1시간 |
| 원/달러 | KIS X / FX@KRW | 1분 |
| 금현물 | 미정 | 호출 없음 |

수집 주기는 원천 데이터의 갱신 속도를 보장하지 않는다. KIS의 날짜가 있는
최신 시계열 값을 사용하고, 시각이 없는 현재가를 실시간이라고 표시하지 않는다.
FRED는 `.` 결측치를 제외한 최신 2개 관측으로 등락률을 계산한다.
KRX는 주말을 제외하고 최대 15일 범위에서 최근 데이터를 찾는다.
프론트는 1분마다 조회하며 숨겨진 탭에서는 멈추고 실패 시 최대 5분까지 간격을 늘린다.

## 응답

`GET /api/market/overview`는 인증 없이 6개의 `items`를 고정 순서로 반환한다.
각 항목은 code, name, source, unit, status, value, change, asOf, collectedAt을 가진다.
`asOf`는 실제 원천의 ISO 날짜(YYYY-MM-DD), `collectedAt`은 UTC 시각이다.
서로 다른 시장의 날짜를 하나의 가짜 기준시각으로 합치지 않는다.

- ready: 정상 수집된 데이터
- stale: 마지막 시도 실패 또는 정상 수집 이후 확인 주기의 3배 경과; 마지막 정상값 제공
- pending: 첫 수집 전
- unavailable: 정상값 없이 수집 실패
- notConfigured: 금현물 예약 항목. 값/등락률/기준일 모두 null

금은 출처를 확정한 후 수집 어댑터를 연결한다. 0원이나 가짜 등락률을 반환하지 않는다.

## 검증

DB를 실행하고 API나 수집기를 한 번 시작해 테이블을 생성한 뒤:

```bash
uv run pytest tests/test_market_services.py tests/test_market_repository.py tests/test_market_router.py tests/test_market_collector.py
```

외부 응답은 테스트에서 모킹한다. 저장소 테스트는 트랜잭션을 rollback한다.

## 랭킹 (거래대금 / 거래량 / 상승률 / 하락률)

기존 수집기 `--loop` 하나가 환율·랭킹을 함께 담당한다. 새 수집 프로세스를 추가하지 않는다.

- 거래대금: KIS `volume-rank`, `FID_BLNG_CLS_CODE=3`
- 거래량: 같은 API, `FID_BLNG_CLS_CODE=0`
- KRX 시장 전체(`J`, `0000`), 보통주(`FID_DIV_CLS_CODE=1`)
- 정리매매·거래정지·ETF·ETN·SPAC 제외 마스크: `0010011101`
- 각 탭의 원천 순위를 유지한다. 한 탭의 상위 종목을 다른 기준으로 재정렬하지 않는다.
- `ranking_snapshot`에 탭별 배열을 원자적으로 교체한다. 응답은 상위 10개로 제한한다.
- 오류 시 마지막 정상 배열을 보존하며 정상 빈 응답은 빈 순위로 저장한다.
- 등락률: KIS `fluctuation`, `FID_RANK_SORT_CLS_CODE=0` 상승 / `1` 하락.
- `FID_PRC_CLS_CODE=1`로 전일 대비 등락률(`prdy_ctrt`)에 맞춘다. 2026-09-20 실응답에서
  가격 기준 0은 표시값 순서와 불일치했고, 1은 상승/하락 각각 30개가 순서와 일치했다.
- 저장 전에 원천 순위가 등락률 내림차순/오름차순인지 검증한다. 불일치 시 기존 정상값을 보존한다.
  동률은 원천 순위를 유지하며 보합/반대 방향은 해당 탭에서 제외한다.
- 등락률 응답에 거래대금은 없으므로 `tradingValue=null`, 화면 보조 지표는 거래량을 사용한다.

홈의 `GET /api/market/overview`에 `rankings`를 함께 반환하므로 프론트는 기존 1분 폴링
한 번으로 지수와 랭킹을 갱신한다. 탭 전환은 네트워크 요청 없이 받은 배열을 표시한다.
독립 조회가 필요한 경우 `GET /api/market/rankings`도 같은 구조를 반환한다.
두 endpoint 모두 외부 API 호출 없이 DB만 읽는다.

KIS 순위 응답에는 명시적 거래일/체결시각이 없다. `collectedAt`은 수집 시각이며,
주말에 조회했다고 주말의 거래 시세라고 표기하지 않는다. 장중 갱신 속도는 별도 검증 대상이다.

### 호출·저장 부하

- 평상시 KIS 시세 호출은 환율 1회 + 네 랭킹 4회 = 분당 5회.
- 토큰과 HTTP 연결을 공유하며 KIS 호출 시작 간격은 최소 0.6초.
- 토큰 발급 실패 후 60초 쿨다운. 여러 탭의 동시 인증 재시도를 막는다.
- FRED/KRX 등 다른 출처는 비동기로 수집한다. KIS 내부 요청은 lock으로 직렬화한다.
- 항목별 전체 수집 제한 25초. 느린 출처와 무관하게 완료된 결과부터 저장한다.
- 외부 호출 중에는 DB의 조회/저장 세션을 닫고, 수집기 중복 방지용 락 연결 하나만 유지한다.
- DB 갱신 후 다음 만기까지 대기한다. 네트워크 처리 시간이 1분 주기에 계속 누적되지 않는다.
- 일반 API 호출은 지수·랭킹 두 테이블의 소수 행만 읽는다. 사용자 수만큼 외부 호출이 늘지 않는다.

추가 검증: `uv run pytest tests/test_ranking.py tests/test_market_collector.py`

## 합계 수급과 업종 지수

홈 overview의 `flows`는 `flowBuy`/`flowSell` 상위 5개를 제공한다.
KIS `foreign-institution-total`의 전체(ETC=0), 수량(DIV=0), 순매수/순매도(SORT=0/1)를
사용한다. `ntby_qty`에는 기타 법인이 포함되므로 화면에도 명시한다.
장중 가집계이며 1분마다 원천 데이터가 바뀐다는 의미는 아니다.
순서와 중복 종목을 검증하고 보합/반대 방향은 제외한다.

`sectors`는 `sectorKospi`/`sectorKosdaq`별 업종 지수 등락률 상위 5개다.
동일 KRX 응답에서 주요 지수와 업종을 추출해 함께 저장한다(추가 요청 없음).
표준 업종 이름 허용 목록을 관리하며 종합·규모·테마 지수와 넓은 제조 합계는 제외한다.
업종명 개편 시 `services/krx.py` 목록을 갱신해야 한다.
전부 하락하는 날에도 등락률이 높은 순서로 제공하며 제목에 '상승'을 단정하지 않는다.
대표 종목은 제공하지 않는다. 원천 기준일과 일별 종가임을 화면에 표시한다.

기존 `ranking_snapshot` JSONB에 네 종류를 추가하므로 테이블 변경은 없다.
수급은 60초, 업종은 주요 지수와 동일한 3600초 주기이며 실패 시 정상 배열을 보존한다.
KIS는 기존 5회 + 수급 2회 = 분당 7회. 토큰·호출 간격 제한을 공유한다.
프론트는 기존 overview 요청 하나를 사용하고 각 보드의 실패/지연을 독립적으로 표시한다.

### 수집 오류 격리

KIS의 JSON 객체 및 환율 시계열 구조를 검증하며 잘못된 응답은 해당 항목의 수집 실패로 처리한다.
KRX는 HTTP 응답을 공유하되 주요 지수와 업종의 파싱 오류를 독립적으로 저장한다.
업종 파싱 실패 시 정상 지수는 갱신하고 업종은 이전 정상 배열을 유지한다(반대도 동일).
업종의 과거 기준일 응답은 DB UPSERT에서 차단하고 `OUTDATED_RESPONSE`로 지연 상태를 표시한다.
같은 기준일의 정정값과 이후 기준일의 정상 응답은 허용한다.
