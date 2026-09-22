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

### 원본 분류 복구 실패 시 전체 행 조회

오류에는 실패 건수와 ID를 최대 5개 표시한다. 전체 실패 행은 아래 쿼리로 확인한다.
마이그레이션 실패 시 `source_category` 추가도 롤백되므로 기존 칼럼만 사용한다.
이 쿼리는 조회만 하며, 출력된 행의 원본 메타데이터를 확인한 뒤 수정한다.

```sql
WITH original AS (
    SELECT id, source, source_id, category, end_url,
           regexp_match(end_url,
               '^https?://m[.]stock[.]naver[.]com/(?:api/)?research/(invest|daily)/([0-9]+)(?:[?#].*)?$'
           ) AS parts
    FROM analyst_reports
)
SELECT id, source, source_id, category, end_url
FROM original
WHERE NOT COALESCE(
    source = 'naver' AND (
        category IN ('company', 'industry', 'economy', 'invest', 'daily')
        OR (category = 'market' AND parts[2] = source_id)
    ), false
)
ORDER BY id;
```

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
