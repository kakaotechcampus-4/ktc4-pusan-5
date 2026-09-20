# 종목 상세 lazy 수집

이번 범위는 종목 기본정보, 시세, 주요 지표, 일봉 차트다. 재무 추이와 AI 보고서는
실제 데이터에 연결하지 않으며 상세 화면에서 목업 숫자를 제공하지 않는다.

## 실행

```bash
# backend 디렉터리에서 기존 DB를 유지한 채 신규 7개 테이블 생성
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
uv run python -m app.collectors.market --loop
```

기존 테이블은 startup의 create_all 방식을 유지하고 stock 테이블은 Alembic으로만 관리한다.
기존 DB에서 이미 stock 테이블을 수동 생성한 경우 무조건 stamp하지 말고 실제 스키마와
revision을 대조해야 한다. `uv run alembic check`는 관리 중인 stock 테이블만 검사한다.

수집기는 홈/상세가 하나의 KIS 토큰·HTTP 연결·0.6초 간격 제한을 공유한다.
프로세스 전체 advisory lock으로 중복 워커가 별도의 호출 예산을 쓰지 못하도록 한다.
상세 작업은 한 번에 하나이며 홈 수집 시각까지 남은 시간 내에서 실행한다.
현재 구조는 단일 워커의 소규모 트래픽을 목표로 한다. 대상 증가 시 우선순위별 대기 시간과
호출 제한을 계측한 후 갱신 주기를 조절하거나 공유 rate limiter를 두고 확장해야 한다.

## 저장 구조

| 테이블 | 키/역할 |
|---|---|
| stock | 6자리 종목코드 PK, 이름/시장/상장일/목록 포함 상태 |
| stock_quote_snapshot | 종목당 마지막 정상 시세, 금액 원·수량 주·등락률 % |
| stock_metric_snapshot | 종목당 PER/PBR/EPS/BPS/외국인 보유율/52주 고저 |
| stock_daily_price | 종목+거래일+raw PK, 원주가 OHLCV |
| stock_collection_state | 종목+영역 PK, 조회 수요·성공/실패·재시도 상태 |
| stock_collection_job | 종목+영역+90일 구간 UNIQUE, 임대 토큰으로 작업 소유권 확인 |
| stock_data_coverage | 종목+가격 기준+구간 PK, 빈 응답을 포함해 확인한 기간 기록 |

KIS 공식 KOSPI/KOSDAQ 마스터의 6자리 코드를 저장한다. 마스터에 있는 ETF 등도 포함될 수
있으며 미제공 지표는 null이다. 9자리 펀드 식별자는 제외한다. `inactive`는 전체 마스터에서
사라졌다는 의미이며 법적인 상장폐지 판정을 뜻하지 않는다. 두 시장 다운로드/검증이 모두
성공한 경우에만 목록을 교체하고 누락 상태를 표시한다. 목록은 일 단위 갱신한다.

금액/비율은 NUMERIC, 거래량은 BIGINT. 지표별 null과 실제 0을 구별한다.
KIS 시가총액 hts_avls의 억원 값을 원으로 변환한다. sourceAsOf는 원천에서 시각을
명확하게 제공할 때만 채우며 현재 inquire-price 응답에서는 null이다.
collectedAt은 수집 시각이며 실제 체결 시각이라고 표시하지 않는다.

## API 계약

- `GET /api/stocks/{code}/overview`: stock, quote, metrics
- `GET /api/stocks/{code}/prices?period=1Y`: 1M/3M/1Y/5Y/ALL

각 영역은 status, refreshing, data, sourceAsOf, collectedAt, retryAfterSeconds를 가진다.
ready는 저장 데이터가 캐시 정책상 유효하다는 뜻이며 거래소의 실시간성을 보증하지 않는다.
pending은 첫 수집 대기, stale은 정상값을 가진 갱신 지연, unavailable은 정상값 없이 실패,
empty는 정상 확인한 구간에 데이터가 없다는 뜻이다.

HTTP 요청에서는 외부 API를 부르지 않는다. 저장 값을 반환하면서 필요한 작업만 등록한다.
종목 마스터가 아직 없으면 503 CATALOG_PENDING, 목록에 없는 코드는 404 STOCK_NOT_FOUND,
잘못된 코드/기간은 422이다. 같은 종목 동시 요청은 DB 고유 제약으로 수집을 합친다.

현재가는 장중(한국시간 평일 09:00~15:40) 60초, 장외 1시간 캐시다.
거래소 휴장일 달력은 아직 없으며 평일 공휴일에는 추가 조회가 발생할 수 있다.
최근 10분 조회된 종목은 캐시 만료 시 자동 갱신한다. 차트는 수요가 있을 때만 수집한다.

일봉은 당일 미완성 봉을 제외하고 전일까지 요청한다. 90일 이하 달력 구간으로 나눠 KIS의
100건 한도를 넘지 않도록 한다. 원주가로 통일해 주식 분할 등이 차트에 가격 단절로
나타날 수 있다. 수정주가와 섞거나 분할을 가격 급락 시그널로 계산하지 않는다.
ALL 시작점은 알려진 상장일, 없으면 1990-01-01이며 실제 coverage 범위를 반환한다.
조회 구간의 확인 완료와 거래일별 데이터 존재는 구별한다. 장기 차트는 부분 결과를 먼저
제공하고 coverage.complete가 될 때까지 화면에서 수집 중임을 표시한다.
과거 구간은 요청 시 주간 재검증, 최근 구간은 일간 재검증해 원천 정정을 반영한다.

작업 임대는 60초이며 개별 외부 작업은 최대 12초 이내다. 워커가 종료되면 임대 만료 후
다른 워커가 회수한다. 저장 시 소유 토큰과 만료를 재확인해 이전 워커의 늦은 응답을 막는다.
네트워크 요청 중 DB 트랜잭션을 유지하지 않는다. 자동 재시도는 최대 5회이며 지수 backoff로 최대 15분 간격이다. 이후에는 새 조회 수요가 있을 때 작업을 다시 등록한다.

## 검증

```bash
uv run pytest
uv run ruff check .
uv run alembic check
```

외부 API 테스트는 모킹하고, 저장소 테스트는 rollback 또는 고유 테스트 종목 정리로 격리한다.
실제 응답 검증: SK하이닉스/삼성전자에서 cold pending→ready와 기존 DB 재사용을 확인한다.
