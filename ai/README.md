# ai/

증권사 애널리스트 리포트를 모아 DB에 넣는 수집 파이프라인. 나중에 에이전트도 여기 들어온다.

`backend/` 와 **같은 Postgres 를 쓰지만 별개 프로젝트다.** 각자 `pyproject.toml` 과
가상환경을 갖는다. 모노레포 규칙대로 작업할 때 이 폴더 안에서 세션을 연다.

```
ai/
  alembic/        DB 구조 변경 이력
  alembic.ini     Alembic 설정
  app/
    core/         설정·DB 연결
    models/       테이블 (SQLAlchemy)
    services/     외부 API 클라이언트·파싱
    repositories/ DB 읽기·쓰기
    collectors/   python -m 으로 도는 수집 배치
  tests/
```

폴더 이름은 `backend/app/` 을 그대로 따랐다. 팀원이 backend 를 보다 여기로 와도
같은 자리에 같은 게 있게 하려는 것이다.

## 왜 backend/ 가 아니라 여기인가

수집은 API 서버와 수명 주기가 다르다. API 는 요청이 오면 답하는 것이고, 수집은
하루 몇 번 도는 배치다. 한 프로젝트에 두면 `pdftotext`·`pypdf` 같은 수집 전용
의존성이 API 배포 이미지에 같이 실린다.

**대신 대가가 있다.** SQLAlchemy `Base` 가 `backend/app/core/database.py` 와
여기 둘로 갈라진다. AI Alembic은 `analyst_reports`만 관리하고, 변경 이력은
`alembic_version_ai`에 저장한다. backend의 모델·변경 이력과 구분한다.
나중에 API 가 리포트를 읽어야 하면 그때 `AnalystReport` 모델을 backend 에서
import 하거나 읽기 전용 쿼리를 쓴다.

## 실행

```bash
cd ai
uv sync

# Postgres 는 backend/docker-compose.yml 것을 같이 쓴다
cd ../backend && docker compose up -d db && cd ../ai

# 빈 DB 최초 설치 또는 기존 Alembic DB의 구조 변경 적용
# create_all로 만든 기존 DB는 아래 전환 절차를 먼저 읽는다.
uv run alembic upgrade head

# 최근 7일 리포트 수집
uv run python -m app.collectors.analyst_report --days 7

uv run pytest
uv run ruff check .
```

### `pdftotext` 가 필요하다

PDF 본문 추출에 poppler 의 `pdftotext` 를 쓴다. 없으면 pypdf 로 넘어가지만
품질이 떨어진다.

```bash
brew install poppler          # macOS
sudo apt install poppler-utils # Ubuntu
```

## 수집 대상

네이버 증권 리서치 (`m.stock.naver.com/api/research/{category}`). 인증이 없다.

네이버 API 는 5종으로 준다 — `company` `industry` `economy` `invest` `daily`.
(`market` 엔드포인트도 응답하지만 `daily` 와 researchId 까지 같은 **동일 데이터**라 안 받는다.)

우리 표의 `category` 는 **4종**이다.

| `category` | 내용 | 종목코드·투자의견·목표주가 |
|---|---|---|
| `company` | 종목분석 | 있다 |
| `industry` | 산업분석 | 없다. 대신 업종의견·Top picks 를 PDF 에서 뽑는다 |
| `economy` | 경제분석. 금리·물가·고용 등 거시지표 | 없다 |
| `market` | 시황·투자전략 | 없다 |

**네이버의 `invest` 와 `daily` 를 합쳐 `market` 으로 받는다.** 네이버 229건으로 채점해보니
둘이 안 갈린다 — 3종으로 두면 62~69%, 합치면 84~86% 다. 네이버 라벨 자체가 흔들려서다.
같은 'Weekly' 가 증권사에 따라 `invest` 이기도 `daily` 이기도 하다. 증권사가 자기
발간물을 어디에 올릴지 정하는 거라 제목·본문으로는 복원이 안 된다.

> ⚠️ 우리 `category='market'` 과 네이버 API 의 `market` 엔드포인트는 **다른 것이다.**
> 네이버 쪽은 `daily` 의 중복본이고 우리는 받지 않는다.

**PDF 원본은 저장하지 않는다.** 임시 폴더에 받아 텍스트만 뽑고 파일은 지운다.
`attach_url` 이 계속 살아 있어서 파서를 고치면 다시 받아 재파싱할 수 있다.

**한국IR협의회가 AI로 생성한 자료(`[AI] ` 로 시작하는 제목)는 받지 않는다.**
애널리스트 리포트가 아니고, 실제로 네이버 API 원본의 제목이 종목과 어긋나 있다.


## DB 구조 변경

수집기는 테이블을 만들지 않는다. 배포/개발 환경 준비 단계에서
`uv run alembic upgrade head`를 실행한 다음 수집기를 실행한다.
AI와 backend의 `DATABASE_URL`은 같은 DB를 가리키도록 설정한다.

```bash
# 기존 이력까지 적용된 개발용 DB에서 모델을 수정한 뒤
uv run alembic revision --autogenerate -m "describe schema change"
# 생성된 파일의 upgrade/downgrade, 데이터 이전 로직을 검토한 후
uv run alembic upgrade head
uv run alembic check
```

자동 생성은 데이터의 의미를 알지 못한다. 기존 행 채우기와 데이터 충돌 처리는
직접 작성한다. 리비전에는 당시 DDL을 고정하고 현재 모델의 `create_all()`을 쓰지 않는다.
AI 표를 추가할 때 `alembic/env.py`의 `MANAGED_TABLES`에도 추가한다.
자기 표를 삭제하는 변경은 자동 생성으로 검출할 수 있도록 소유 목록에서 즉시 빼지 않는다.

### Alembic 도입 이전의 DB

수집기를 중지하고 백업한 뒤, 실제 칼럼·타입·NULL 허용 여부·인덱스·제약을
마이그레이션과 대조한다. `stamp`는 테이블을 고치거나 일치 여부를 검사하지 않는다.
테이블이 있다는 이유만으로 `stamp head`를 실행하지 않는다.

| 실제 스키마 | 전환 방법 |
|---|---|
| `analyst_reports`가 없음 | `uv run alembic upgrade head` |
| `0001`과 정확히 같음: `source_category` 없음, 구 자연키 | 확인 후 `uv run alembic stamp 0001`, 다음 `uv run alembic upgrade head` |
| #18 모델과 정확히 같음: `source_category NOT NULL`, 새 자연키 | 전체 구조·데이터가 해당 리비전과 같음을 확인한 후 `uv run alembic stamp 0018_source_category`, 다음 `uv run alembic check` |
| 일부만 적용되었거나 다른 구조 | stamp하지 않고 차이를 먼저 조사해 별도 이전 절차 작성 |

`0018_source_category`는 기존 행의 source가 naver이고 category가 원본 분류면 그 값을
사용한다. `market` 행은 `end_url`의 invest/daily 및 원본 ID가 확인될 때만 복구한다.
근거 없는 market 행이나 다른 출처의 행이 있으면 변경 전체를 롤백한다.
외부 API를 호출하거나 기존 행을 삭제하지 않는다. 원본을 확인해 잘못되거나 누락된
기존 메타데이터를 복구한 뒤 다시 실행한다. 이미 덮어써진 리포트는 이 변경으로 되살릴 수 없다.

새 자연키로 invest/daily의 동일 번호가 공존할 수 있다. 이 상태에서 구 자연키로
downgrade하려 하면 데이터 보존을 위해 중단한다. 자동으로 행을 합치거나 지우지 않는다.

### 팀 PR 통합

- #26의 고정 DDL `0001`을 재사용했다. #18의 head는 `0018_source_category`다.
- #26의 `0002`도 `0001`에서 출발하므로 두 PR을 그대로 합치면 head가 둘이다.
  두 리비전 파일이 모두 있는 통합 브랜치에서 아래 명령으로 **빈 merge revision**을
  추가한다. 이미 적용된 `0001`/`0002` 파일의 부모를 바꾸지 않는다.

```bash
uv run alembic merge -m "merge analyst and stock report migrations" 0018_source_category 0002
uv run alembic upgrade head
uv run alembic check
```

- env.py는 이 PR의 `version_table="alembic_version_ai"`를 유지하고, #26에서
  추가하는 네 `stock_move_report*` 표도 `MANAGED_TABLES`에 명시한다.
  모델 import는 양쪽을 합친다. dependency/lockfile도 양쪽 의존성을 유지한다.
- #26을 이미 기본 `alembic_version`으로 실행했다면 새 이력 표로 자동 복사하지 않는다.
  기존 이력이 AI 것인지 BE 것인지와 실제 스키마를 확인하고, 검증된 **AI revision만**
  `alembic_version_ai`에 stamp한다. 기존 BE 이력을 삭제하거나 덮어쓰지 않는다.
- #26의 오프라인 테스트는 CREATE TABLE만 비교하므로 이 PR의 ALTER COLUMN 이력을
  반영하지 못한다. 통합 시 PostgreSQL에 전체 리비전을 실행한 뒤 `alembic check`로
  최종 스키마를 비교하는 테스트를 유지한다.
- #23/#24의 backend 설정은 별도 통합이 필요하다. backend는 자기 표만 비교하도록
  필터를 두고 AI와 다른 버전 표를 사용해야 한다. #23의 baseline은 고정 DDL로 바꾸고,
  #24 주식 표와 중복 생성되지 않도록 BE 리비전의 범위·순서를 맞춰야 한다.
  이 PR이 backend 쪽 오류까지 수정하는 것은 아니다.

### PostgreSQL 마이그레이션 테스트

실제 DB 테스트는 환경변수가 없으면 skip된다. 테스트 전용 PostgreSQL의
DB 생성 권한이 있는 주소를 `MIGRATION_TEST_ADMIN_URL`로 지정한다.
테스트는 `pr18_migration_<uuid>` DB를 생성하고 그 DB만 제거한다.
앱의 `.env`나 `DATABASE_URL`을 테스트 DB로 자동 사용하지 않는다.

```bash
MIGRATION_TEST_ADMIN_URL=postgresql://USER:PASSWORD@HOST:PORT/postgres uv run pytest
```

빈 DB 전체 설치, 기존 데이터 보존, 복구 불가 행의 트랜잭션 롤백,
자연키 충돌 시 downgrade 중단, backend 표·이력 보존과 최종 모델 일치를 검증한다.

### 텔레그램 PDF 요약

`ai/.env`의 `DATABASE_URL`이 수집 데이터를 가진 DB를 가리키는지 먼저 확인한다.
`OPENROUTER_API_KEY`가 있어야 생성할 수 있다. 모델은 `SUMMARY_MODEL`로 설정한다.
기본 추론 강도는 `SUMMARY_REASONING_EFFORT=low`, 요청 전체 제한은
`SUMMARY_TIMEOUT_SEC=180`초다. 바꾸는 모델이 지원하는 추론 값을 사용한다.
텔레그램 로그인 세션은 수집에만 필요하고, 저장된 본문의 요약에는 필요 없다.

```bash
# 대상 확인: DB와 외부 API를 변경하지 않는다.
uv run python -m app.collectors.summary --dry-run

# 비어 있는 요약만 채운다. 같은 PDF의 정상 요약이 있으면 재사용한다.
uv run python -m app.collectors.summary --report summary-result.json

# 기존 요약 중 현재 검증을 통과하지 못한 것까지 복구한다.
uv run python -m app.collectors.summary --repair-invalid --dry-run
uv run python -m app.collectors.summary --repair-invalid --report summary-repair.json
```

본문 1,000자 이하 또는 워터마크만 추출된 PDF는 요약 대상에서 제외한다. OCR은 이번 구현 범위에 포함하지 않는다. 네이버 요약은 수정하지 않는다.

길이·숫자·목표주가 검증에 실패하면 최대 세 번 재시도하고, 끝내 통과하지 못하면
기존 DB 값을 유지한다. 실행 결과에는 실패한 행 ID와 사유가 남고 종료 코드는 1이다.
정상 결과는 PDF마다 커밋하므로 중단 후 다시 실행해 이어갈 수 있다.
조회 후 다른 작업이 요약을 수정했다면 덮어쓰지 않고 `conflicts`에 기록한다.
`--force`는 정상 요약까지 재생성할 때만 사용한다.
`--ids` 뒤에 리포트 ID를 지정하면 원문 대조에서 확인한 특정 행만 처리할 수 있다.

수치 검증은 본문의 값·단위와 확정 목표가를 대조하는 규칙이다. 숫자가 어떤 항목·기간에
해당하는지, 서술 전체가 사실인지까지 보장하지는 않으므로 표본 원문 대조가 필요하다.


### 원본 식별키와 내부 분류

`source_category`와 `category`는 역할이 다르다. 내부 분류를 바꿔도 원본 식별키는 바꾸지 않는다.

| 출처 | source_category | source_id | category 예시 |
|---|---|---|---|
| 네이버 | 원본 API 분류 `invest` | `37550` | `market` |
| 네이버 | 원본 API 분류 `daily` | `37550` | `market` |
| 텔레그램 | 원본 채널 `channel_one` | 메시지 번호 `123` | `company` |
| 텔레그램 | 원본 채널 `channel_two` | 메시지 번호 `123` | `company` |

고유키는 `(source, source_category, source_id)`다. 위 네 행은 모두 별개로 저장된다.
네이버에 같은 PDF 해시가 있으면 텔레그램 행은 추가하지 않는다. 텔레그램 채널끼리
같은 PDF를 공유한 경우에는 출처 행을 보존하고 정상 요약을 재사용한다.

### 텔레그램 수집 실행

별도 환경 준비 단계에서 `uv run alembic upgrade head`를 먼저 실행한다.
수집기는 DB 구조를 생성하거나 마이그레이션을 자동 실행하지 않는다.
수집 서버 한 곳만 실행한다면 그 서버에만 설정하면 된다. 각자 로컬에서 수집할 때는
각자 계정으로 로그인한다. 비공개 채널은 해당 계정에 가입·접근 권한이 있어야 한다.

1. `.env.example`을 참고해 `.env`에 `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`를 설정한다.
   앱 인증정보는 [my.telegram.org/apps](https://my.telegram.org/apps)에서 발급받는다.
2. 아래 로그인 명령으로 전화번호·인증 코드(필요하면 2단계 비밀번호)를 입력한다.
   세션은 접근 권한을 제한한 `.env.telegram`에 저장하고 자동으로 읽는다. 공유·커밋하지 않는다.
3. 수집할 채널의 접근 확인을 실행한 뒤 수집한다. 기본 대상은 `sunstudy1234` 하나다.

```bash
uv run python -m app.collectors.telegram_setup --login
uv run python -m app.collectors.telegram_setup --check --channel sunstudy1234 --channel DOC_POOL
uv run python -m app.collectors.telegram --days 7 --channel sunstudy1234 --channel DOC_POOL
```

채널 이름 조회가 실패하면 같은 계정의 대화 목록에서도 찾는다. 직접 지정해야 한다면
`--channel 'CHANNEL=CHANNEL_ID:ACCESS_HASH'`를 사용한다. access_hash는 계정별 값이므로
다른 사람의 것을 복사하지 않는다. 세션·채널 접근 확인 실패는 종료 코드 1로 알리며,
수집 중 오류가 나도 성공으로 표시하지 않는다. 배치에서는 로그인 입력을 기다리지 않는다.
세션 재발급은 기존 `.env.telegram`을 별도로 보관한 뒤 로그인 명령을 다시 실행한다.

채널별로 이미 수집한 메시지는 발행일과 관계없이 건너뛴다. 오래된 발행일의 자료를
오늘 다시 게시해도 같은 메시지를 다시 받지 않는다. 동시에 수집한 경우에도 기존
텔레그램 행을 덮어쓰지 않는다. 본문 재추출과 메타데이터 교정은 별도 검토 작업이다.
네이버는 제공 요약·조회 수를 갱신하되 PDF 재추출 실패로 기존 정상 본문을 지우지 않는다.

`body_status='empty'`는 추출된 텍스트가 없다는 뜻이고, `unusable`은 워터마크 등으로
실제 본문이 부족하다는 뜻이다. 글자가 보존되어 있어도 사용할 수 없는 자료일 수 있다.
`ok` 또한 전체 페이지 추출이나 OCR 정확성을 보증하지 않는다. 요약기는 별도로 길이와
내용을 검사한다. OCR은 지원하지 않으며 표의 숫자·기간·항목 대응은 별도 원문 검토가 필요하다.
요약 저장 중 본문·PDF 해시 또는 기존 요약이 바뀌면 저장하지 않고 충돌로 기록한다.

### 텔레그램 자료의 품질 범위

OCR은 지원하지 않는다. 이미지 PDF·본문 부족 자료는 원문 링크와 추출 상태를 보존하되
요약하지 않는다. 원문 링크를 가진 행 수와 본문/요약을 확보한 행 수는 구분해서 집계한다.
발행처·종목코드·분류는 파일명과 텍스트에서 추정하므로 네이버 제공 메타데이터와 같은
정확도를 보장하지 않는다. 특히 코드 없는 기업 IR은 market으로 분류될 수 있다.
발행일도 파일명 우선, 파일명에 없으면 게시일을 사용하므로 실제 표지 날짜와 다를 수 있다.

### 네이버와 텔레그램 PDF 중복

네이버 수집을 먼저 실행한 뒤 텔레그램을 수집한다. PDF SHA-256이 네이버 저장본과
같으면 텔레그램 저장·요약을 건너뛴다. 파일명은 비교 기준으로 쓰지 않으며, 파일을
다운로드해야 해시를 알 수 있다. 해시가 없거나 서로 다르면 중복이라고 추측해 버리지 않는다.

저장 직전에도 네이버 해시를 다시 확인한다. 네이버 저장이 먼저 진행 중인 같은 PDF는
그 트랜잭션이 끝난 후 확인한다. 텔레그램이 먼저 저장되고 나중에 네이버가 추가된 경우의
기존 텔레그램 행은 수집기가 자동 삭제하지 않으므로 별도 정리가 필요하다.

### 날짜 기준

네이버는 업로드일, 텔레그램은 파일명 날짜(없으면 게시일)를 사용한다. 발간 후 다음 날이나
주말을 지나 올라오는 자료는 실제 발간일과 차이가 난다. 표지 날짜를 확인하는 것이 정확하지만,
본문에서 자동 추출하면 실적 기준일 등 다른 날짜와 혼동할 수 있어 현재 방식은 유지한다.
하루 이틀 차이가 서비스 판단에 중요한 영향을 주는 시점에 발간일 추출을 다시 검토한다.
