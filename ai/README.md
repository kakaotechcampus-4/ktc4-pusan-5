# ai/

증권사 애널리스트 리포트·뉴스·텔레그램 메시지를 모아 DB에 넣는 수집 파이프라인.
나중에 에이전트도 여기 들어온다. 뉴스 수집은 backend 에 있던 것을 옮겨 왔다.

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
여기 둘로 갈라진다. AI Alembic은 아래 [표 관리 범위](#표-관리-범위)의 표만 관리하고,
변경 이력은 `alembic_version_ai`에 저장한다. backend의 모델·변경 이력과 구분한다.
나중에 API 가 리포트를 읽어야 하면 그때 `AnalystReport` 모델을 backend 에서
import 하거나 읽기 전용 쿼리를 쓴다.

## 실행

```bash
cd ai
uv sync

# Postgres 는 backend/docker-compose.yml 것을 같이 쓴다
cd ../backend && docker compose up -d db && cd ../ai

# backend 가 먼저다. news·channel·source_card 는 backend 첫 리비전이 만든다.
cd ../backend && uv run alembic upgrade head && cd ../ai

# 빈 DB 최초 설치 또는 기존 Alembic DB의 구조 변경 적용
# create_all로 만든 기존 DB는 아래 전환 절차를 먼저 읽는다.
uv run alembic upgrade head
# backend 에서 넘겨받은 기존 뉴스·PDF 에 공통 자료 ID 를 붙인다. 몇 번을 돌려도 된다.
uv run python -m app.collectors.sources register

# 수집기는 collection_scope.toml 에 적은 범위 안에서만 돈다. 비어 있으면 아무것도 받지 않는다.
# 팀이 정한 출처·종목·채널·기간·수집량·이용 조건을 먼저 적는다(아래 "데이터 이용 제한").

# 최근 7일 리포트 수집
uv run python -m app.collectors.analyst_report --days 7

# 뉴스: 네이버 검색 / 텔레그램 공개 채널 메시지와 거기 걸린 기사
uv run python -m app.collectors.news 삼성전자
uv run python -m app.collectors.news_channels

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


## 종목 변동 요인 분석 적재

LLM 이 생성한 "그 종목이 왜 그렇게 움직였는지" 를 DB 에 넣는다. 수집과 반대로
**입력이 DB 가 아니라 파일**이다 — `runs/<타임스탬프>/parsed/*.json` 을 사람이
가져다 두면 `app/repositories/stock_move_analysis.py` 가 읽는다. 생성 결과는 매
실행마다 새로 만들어지는 일회성 산출물이라 원본을 쌓을 표를 따로 두지 않았다.

```
stock_move_analyses                본체. 한 행 = 분석 한 회차
stock_move_analysis_factors        원인 (배열 순서 = 중요도)
stock_move_analysis_factor_sources 원인별 출처
stock_move_analysis_reviews        검수 판정. 표만 있고 아직 쓰지 않는다
```

`analyst_reports` 가 "증권사 애널리스트가 쓴 원문" 이고 이쪽은 "우리가 생성한
분석" 이다. 이름이 겹치지 않아야 같은 DB 에서 구분된다.

**INSERT only 다.** 같은 종목·같은 기준시각을 다시 생성해도 덮어쓰지 않고 새 행으로
쌓는다. 시스템 프롬프트가 "이전 회차를 언급하지 않는다" 고 규정해 각 회차가 독립
문서라서다. 그래서 자연키 `(ticker, target_date, as_of)` 에 UNIQUE 가 없다.

**검증 실패·스키마 위반 건도 버리지 않고 상태만 달아 적재한다.** 정규화 칼럼이 거의
전부 nullable 인 이유이고, 원본은 `raw_json` 에 통째로 남는다. 근거 검증 판정은 적재
모듈이 직접 하지 않고 인자로 받는다(`verify_status`, 기본 `not_verified`).
backend 조회는 `verify_status = 'passed'` 를 전제한다.

## 뉴스·텔레그램 메시지 수집

뉴스는 두 경로로 들어와 같은 `news` 표에 쌓인다. 같은 기사는 경로가 달라도 한 행이다.

| 경로 | 실행 | 본문 추출 | 발행 시각 |
|---|---|---|---|
| 네이버 뉴스 검색 | `python -m app.collectors.news <검색어>` | trafilatura (backend 그대로) | API 가 준다 |
| 텔레그램 메시지 링크 | `python -m app.collectors.news_channels` | news_link (bs4) | **모른다. NULL 로 둔다** |

```bash
uv run python -m app.collectors.news 삼성전자 --display 50
uv run python -m app.collectors.news --retry-failed            # 본문을 못 얻은 네이버 기사만 다시 연다
uv run python -m app.collectors.news_channels                  # 어제 0시부터. 범위의 채널을 DB 에 쓴다
uv run python -m app.collectors.news_channels --dry-run        # DB 에 쓰지 않고 범위 확인·요약만
uv run python -m app.collectors.news_channels --jsonl          # JSONL 파일 사본도 쓴다 (data/telegram/)
```

모두 `collection_scope.toml` 의 범위 안에서만 돈다(아래 "데이터 이용 제한"). 범위 밖의
검색어·채널은 거부하고, 기간 밖의 자료와 수집량 상한을 넘는 새 자료는 받지 않는다.
네이버 검색은 `.env` 에 `NAVER_CLIENT_ID`·`NAVER_CLIENT_SECRET` 이 있어야 한다.
텔레그램 공개 채널 수집은 로그인이 필요 없다.

공개 채널 수집기는 #43 때는 JSONL 파일에만 썼다. 이제 DB 가 원문 저장소이고 파일은 `--jsonl`
일 때만 쓰는 사본이다. 파일은 보관 정책으로 DB 본문을 지울 때 함께 지워지지 않는다.

**같은 기사인지는 정규화한 주소로 가른다**(`news.canonical_url`, `app/services/news/url.py`).
호스트 대소문자·기본 포트·#조각·추적 파라미터(utm_* 등)만 지운다. http/https·www·끝의 /
처럼 다른 문서일 수 있는 차이는 남긴다. 처음 들어온 주소는 `news.url` 에 그대로 둔다.

**본문은 한 번 확보하면 바꾸지 않는다.** 실패했던 본문만 다음 수집에서 채운다. 재수집에서
실패해도, 고쳐진 기사를 다시 받아도 성공한 본문은 그대로다. 기사 본문(`cleaned_text`)은
전체이고, 앞 3문장 발췌나 종목별로 고른 문장을 넣지 않는다. 본문을 받은 시각(`body_fetched_at`),
상태(`body_status` ok·failed), 실패 사유(`body_error`)를 같이 남긴다.

**발행 시각을 모르면 NULL 이다.** 링크를 연 시각·메시지 게시 시각으로 채우지 않는다. 같은
기사를 네이버가 나중에 찾으면 그때 채운다. 기준 시각으로 자료를 거를 때는 발행 시각이
없으면 메시지 게시 시각(`telegram_messages.posted_at`)과 본문 받은 시각을 따로 본다.

텔레그램 메시지는 `telegram_messages` 에, 메시지 안의 링크·첨부는 `telegram_message_links` 에
들어간다. 같은 기사를 여러 메시지가 올려도 기사는 한 행이고 발견 기록은 메시지마다 남는다.
메시지에 적힌 주소(대개 단축 URL)와 따라가 도착한 주소를 둘 다 둔다. 열지 않은 링크도
이유(`stale`: 24시간 지남·게시 시각 모름, `over_limit`, `not_fetchable`, `out_of_scope`: 수집
범위 밖)와 함께 남는다. 링크로 기사를 여는 것은 별도 출처(`telegram_link`)라, 범위에서 꺼 두면
메시지만 저장하고 기사는 열지 않는다.

**운영자가 쓴 글과 남의 자료를 나눠 둔다.** 다른 채널 글을 전달한 메시지는 `forwarded_from`·
`forwarded_from_url` 에 원래 채널과 원글을 남기고, 그 메시지의 원 발행처를 원래 채널로 적는다.
메시지에 걸린 외부 기사·PDF 는 메시지 글이 아니라 `news`·`analyst_reports` 의 별도 행이고
발행처는 언론사·증권사다. 메시지 글 안에 기사 제목·요약을 옮겨 적은 경우는 글자만으로
가려내지 못한다.

**메시지 본문은 처음 저장한 것을 바꾸지 않는다.** 다시 수집했을 때 글자가 달라졌으면
`edit_detected_at` 에 처음 감지한 시각만 남기고, 고친 내용은 저장하지 않는다. 채널에
"edited" 표시가 있으면 `edited` 가 참이다(처음 수집하기 전에 고친 글도 포함). 게시 시각을
못 읽은 메시지는 `posted_at` 이 NULL, 글자 없이 첨부만 올린 메시지는 `text` 가 빈 문자열이다.

로그인 계정으로 PDF 를 받는 `collectors/telegram.py` 도 PDF 가 붙어 있던 메시지와 발견 경로를
같은 표에 남긴다. 네이버에 같은 PDF 가 있어 텔레그램 행을 만들지 않은 경우에도 그 네이버
행에 연결한다(상태 `duplicate`). 이 기록이 실패해도 같은 묶음의 PDF 행은 저장된다.

## 공통 자료 ID

`source_card.id` 가 뉴스·PDF·메시지를 가리키는 공통 자료 ID 다. 원문은 종류별 표에 두고,
카드는 그 행 하나를 FK 로 가리킨다. 원문을 카드에 복제하지 않는다.

| card_type | 원문 표 | 원 발행처(source_name) | 수집 경로 |
|---|---|---|---|
| `news` | `news` | 기사 도메인 | `naver_news_search` · `telegram_link` |
| `pdf` | `analyst_reports` | 증권사 | `naver_research` · `telegram_attachment` |
| `message` | `telegram_messages` | 채널 이름 | `telegram_web` · `telegram_client` |

카드는 종류에 맞는 원문 하나만 가리킨다(CHECK 제약). 원문 하나에 카드도 하나다(UNIQUE).
수집기는 끝날 때 카드가 없는 원문에 카드를 만든다. 카드 등록이 실패해도 원문은 이미
커밋돼 있으므로 아래 명령으로 다시 등록한다. 분류(기업·산업)는 원문 저장과 분리되어 있어
분류를 하지 않거나 실패해도 원문과 카드는 남는다.

```bash
uv run python -m app.collectors.sources register      # 카드가 없는 원문 등록. 몇 번 돌려도 같다
uv run python -m app.collectors.sources show 12 34    # 공통 ID 로 발행처·수집 경로·시각·발견 경로
uv run python -m app.collectors.sources show 12 --body   # 본문 앞부분까지 (--full 이면 전체, 내부 확인용)
```

코드에서는 `app.repositories.source_card.get_sources(session, ids)` 가 같은 조회를 한다.
기사·PDF 는 그것을 공유한 메시지들을, 메시지는 그 메시지가 건 링크를 `discoveries` 로 준다.

**본문은 요청할 때만 준다.** `get_sources(..., include_body=True)` 일 때만 `body` 가 채워진다.
원문을 읽는 코드를 찾을 수 있게 하려는 것이다. 본문이 있는지(`has_body`)와 없으면 그 사유
(`body_missing_reason`)는 늘 준다.

| body_missing_reason | 뜻 |
|---|---|
| `failed: <사유>` | 기사를 열었지만 본문을 못 얻었다 (`http_error: 403`, `extract_empty` 등) |
| `empty`·`unusable`·`skipped`·`pending`… | PDF 본문 상태 그대로 (`analyst_reports.body_status`) |
| `empty: 글자 없이 첨부만 올린 메시지` | 메시지에 글자가 없다 |
| `purged: 보관 정책으로 삭제 (날짜) 사유` | 보관 정책으로 지웠다. 재분류·과거 결과 검증에 쓸 수 없다 |

## 데이터 이용 제한

뉴스·텔레그램·PDF 의 수집·저장·외부 LLM 전달에 관한 이용 권한과 공정이용 해당 여부는
**확인되지 않았다.** 아래는 불확실성을 줄이려는 운영 방침이고, 이용 허락을 받았거나 적법하다는
뜻이 아니다. 법적 검토가 끝나지 않은 상태는 기능 완료와 구분한다.

**수집 범위 — `collection_scope.toml`.** 모든 자료를 계속 쌓는 것을 기본으로 삼지 않는다.
팀이 정한 출처·종목·채널·기간·수집량 안에서만 수집하고(`app/core/scope.py`), 출처마다 이용
조건(확인 상태·근거·날짜·미확정 사항)을 같은 파일에 적는다. 저장소의 파일은 모든 출처가
꺼져 있어 그대로는 아무것도 수집하지 않는다.

| 출처 | 수집기 | 허용 목록 | 수집량(max_items)이 세는 것 |
|---|---|---|---|
| `naver_news` | `collectors.news` | `queries` 검색어 | `news` 중 네이버 검색으로 들어온 행 |
| `telegram_web` | `collectors.news_channels` | `channels` | 공개 채널에서 받은 `telegram_messages` |
| `telegram_link` | `collectors.news_channels` | (없음) | `news` 중 텔레그램 링크로 들어온 행 |
| `telegram_client` | `collectors.telegram` | `channels` | 텔레그램에서 받은 `analyst_reports` |
| `naver_research` | `collectors.analyst_report` | `categories`, `item_codes`(company) | 네이버에서 받은 `analyst_reports` |

- 기간은 자료 날짜(기사 발행일·메시지 게시일·리포트 작성일, KST) 기준이다. 게시 시각을 모르는
  메시지는 기간 안인지 모르므로 수집하는 날이 기간 안일 때만 받는다.
- 수집량은 그 경로로 DB 에 쌓인 행의 누적 상한이다. 본문을 지운 행도 센다. 닿으면 새 자료는
  받지 않고, 이미 있는 자료만 갱신한다. PDF·기사는 상한을 넘으면 내려받지도 않는다.
- 켠 출처는 기간·허용 목록·수집량·이용 조건을 모두 적어야 한다. 하나라도 비면 수집기가
  무엇을 채워야 하는지 알려주고 멈춘다. 이용 조건은 "미확인" 이어도 적는다.
- 텔레그램 운영자에게 받은 허락은 그 채널의 글에만 해당한다. 메시지에 걸린 외부 기사
  (`telegram_link`)·PDF 의 발행처에는 해당하지 않으므로 출처를 나눠 조건을 따로 적는다.

**보관 정책에 따른 본문 삭제.** 보관 기간·대상·처리 담당은 아직 정하지 않았다. 정해진 뒤
사람이 아래 명령으로 지운다(자동으로 지우지 않는다). 본문만 지우고 행·id·제목·주소·시각·공통
자료 ID·발견 경로는 남긴다. 지운 행은 `purged` 로 표시되고 다시 수집해도 되살아나지 않는다.

```bash
uv run python -m app.collectors.sources purge --ids 12 34 --reason "정책 이름"     # 대상 수만 센다
uv run python -m app.collectors.sources purge --kind news --before 2026-11-01 --reason "..." --confirm
```

요약(`news.summary`·`analyst_reports.summary_text`), 분류 근거, 생성 입력, JSONL 파일, 로그·백업은
본문의 사본이라 위 명령이 지우지 않는다. 사본의 보관·삭제 범위는 분류·생성 담당과 맞춘다.

**원문이 밖으로 나갈 수 있는 경로** (2026-10-05 점검)

| 경로 | 지금 상태 |
|---|---|
| DB 원문 칼럼 (`news.cleaned_text`·`analyst_reports.body_text`·`telegram_messages.text`) | DB 접속 권한으로만 읽힌다. 코드에서는 `include_body=True` 를 적은 곳만 읽는다. DB 역할별 권한은 아직 나누지 않았다 |
| backend API | 이 표들의 본문 칼럼을 읽는 라우터가 없다 |
| JSONL 파일 (`data/telegram/`) | `--jsonl` 일 때만 쓴다. git 에 올라가지 않는다. 메시지 글과 기사 앞 3문장이 들어간다 |
| 터미널 출력 | `sources show --body/--full` 은 본문을, `news_channels --show-links` 는 80자 미리보기를 출력한다. 내부 확인용이다 |
| 로그 | 수집기는 건수·주소·오류 종류만 남기고 본문은 남기지 않는다 |
| 테스트 자료 | 이번 브랜치에서 추가한 테스트는 직접 쓴 mock 데이터다. `tests/fixtures/reports/` 는 이전 PR 의 생성 결과라 별도 확인이 필요하다 |
| 외부 LLM | 이번 수집 브랜치는 LLM 을 부르지 않는다. 기존 텔레그램 PDF 요약(`collectors.summary`)은 본문을 외부 LLM 에 보낸다 — 제공자의 입력 보관·학습 조건 기록은 아직 없다 |

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

### 표 관리 범위

한 표는 한쪽 Alembic 만 비교·변경한다. 두 쪽이 같은 표를 비교하면 서로 상대가 더한 칼럼을
지우라는 마이그레이션을 만든다.

| 표 | 만든 곳 | 구조 변경 | 비고 |
|---|---|---|---|
| `analyst_reports`, `stock_move_analysis*` | ai | ai | 0023: 보관 정책상 삭제 기록 칼럼 |
| `telegram_messages`, `telegram_message_links` | ai (0021) | ai | |
| `news` | backend 첫 리비전 | **ai (0020~)** | 기존 행·id 그대로 넘겨받음 |
| `source_card` | backend 첫 리비전 | **ai (0022~)** | backend `report_citation` 이 FK 로 가리킨다 |
| `channel` | backend 첫 리비전 | backend | ai 는 FK 로 가리키고 처음 보는 채널 행만 넣는다 |

ai 쪽은 `alembic/env.py` 의 `MANAGED_TABLES`·`EXTERNAL_TABLES`, backend 쪽은
`backend/migrations/env.py` 의 `AI_MANAGED_TABLES` 가 이 표를 따른다. backend 의 이미 적용된
리비전은 고치지 않았다. 그래서 `news`·`source_card` 는 지금도 backend 첫 리비전이 만든다.

### 빈 DB 설치 순서

**backend 를 먼저 올린다.** ai 의 0020~0022 는 backend 가 만든 `news`·`channel`·`source_card` 를
고치므로, 그 표가 없으면 안내 문구와 함께 중단하고 아무것도 남기지 않는다(한 트랜잭션).
ai 가 그 표를 직접 만들면 나중에 backend 첫 리비전이 같은 표를 만들다 실패한다.

```bash
cd backend && uv run alembic upgrade head   # 배포에서는 backend 컨테이너가 시작할 때 한다
cd ../ai && uv run alembic upgrade head
uv run alembic check
```

### 기존 DB 인수 (news·source_card)

backend 가 쓰던 DB 에 그대로 올린다. 표를 새로 만들지 않고 기존 행·id 를 둔 채 칼럼만 더한다.

1. backend 뉴스 수집을 멈추고 DB 를 백업한다.
2. backend 를 이 브랜치로 배포한다. backend 가 `news`·`source_card` 를 비교하지 않게 된다.
3. `cd ai && uv run alembic upgrade head`
   - `news`: `published_at` NULL 허용. 기존 행의 본문 상태를 채운다 — 본문이 있으면 `ok`·
     `trafilatura`, 없거나 빈 문자열이면 `failed`·`unrecorded`(backend 는 사유를 남기지 않았다).
     `body_fetched_at` 은 `collected_at` 이다. backend 는 본문을 받은 직후 같은 실행에서 행을
     넣었으므로 받은 시각의 상한이다.
   - `source_card`: 이미 `news`·`pdf`·`message` 종류의 카드가 원문 FK 없이 있으면 새 제약을
     어기므로 중단한다. 그 카드를 backend 와 정리한 뒤 다시 실행한다. 카드를 고치거나 지우지 않는다.
4. `uv run alembic check`
5. `uv run python -m app.collectors.sources register`
   - 기존 뉴스의 `canonical_url` 을 채우고 기존 뉴스·PDF 에 공통 자료 ID 를 만든다.
   - 정규화 주소가 겹치는 기존 행(같은 기사가 두 행으로 들어가 있던 것)은 비워 두고 목록을
     보여준다. 합치지 않는다 — 사람이 확인한다.

downgrade 는 데이터를 지우지 않는 범위에서만 된다. 발행 시각이 없는 기사나 보관 정책으로
본문을 지운 기사가 있으면 0020 을, 원문을 가리키는 카드가 있으면 0022 를, 본문을 지운 PDF 가
있으면 0023 을 되돌리지 않고 중단한다. 지운 기록을 잃으면 예전 코드의 재수집이 본문을 되살린다.

### backend 뉴스 수집에서 전환

뉴스 수집 코드(`services/news`·`collectors/news`·`repositories/news`·`models/news`)와 테스트,
`trafilatura` 의존성, `NAVER_CLIENT_*` 설정은 backend 에서 지우고 여기로 옮겼다. backend 에는
뉴스를 쓰는 다른 코드가 없었다. 두 수집기가 같이 돌지 않도록 이 순서로 바꾼다.

1. backend 에서 `python -m app.collectors.news` 를 돌리던 작업(수동·스케줄)을 멈춘다.
2. 위 "기존 DB 인수" 를 마친다. 이 브랜치의 backend 에는 뉴스 수집기가 없다.
3. `ai/.env` 에 `NAVER_CLIENT_ID`·`NAVER_CLIENT_SECRET` 을 옮긴다(backend/.env 에서는 지워도 된다).
4. `cd ai && uv run python -m app.collectors.news <검색어>` 로 돌린다. 검색·본문 추출은 backend 와
   같고, 저장만 위 규칙(같은 기사 합치기·실패 본문 보완)으로 바뀌었다.

예전 backend 체크아웃으로 뉴스 수집을 돌리면 새 NOT NULL 칼럼(`body_status`) 때문에 저장이
실패한다. 조용히 섞여 들어가지 않고 멈추는 쪽이다.

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

**#26(종목 변동 요인 분석 적재)은 통합 완료.** 위 문단이 예고한 head 둘 문제는
`alembic merge` 대신 **#26 리비전의 부모를 바꿔서** 풀었다.

- #26의 리비전은 **어느 DB에도 적용된 적이 없다.** 그래서 부모를 바꿔도 안전하다.
  `0002(down=0001)` → `0019_stock_move_analysis(down=0018_source_category)`.
  빈 merge revision을 만들면 하는 일 없는 리비전이 하나 남고 `0001` 밑에 번호가
  겹치는 갈래가 그대로 보존되는데, 적용 이력이 없으니 그 대가를 치를 이유가 없다.
  **이미 적용된 리비전이었다면 반대로 `alembic merge`가 맞다.**
- 표 이름은 PR 리뷰에서 `stock_move_report*` → `stock_move_analysis*`로 바뀌었다.
  `analyst_report`(남이 쓴 원문)와 구분하기 위해서다. `MANAGED_TABLES`에 네 표를
  모두 넣었다.
- #26의 alembic 인프라(alembic.ini·env.py·baseline)는 이 PR 것으로 대체했다.
  `version_table="alembic_version_ai"`, ConfigParser를 거치지 않는 URL 전달,
  `include_name` 허용목록이 전부 이 PR 쪽이 맞다.
- #26의 오프라인 테스트는 CREATE TABLE만 비교하므로 `ALTER`로 진화한
  `analyst_reports`에는 쓸 수 없다. 그래서 그 테스트는 **`stock_move_analysis*` 네 표만**
  보도록 좁혀 `tests/test_migration_schema_sync.py`로 남겼다. DB가 없는 환경에서
  "모델만 고치고 마이그레이션을 안 만든" 실수를 잡는 용도다. 전체 스키마 검증은
  `tests/test_migrations.py`의 PostgreSQL 테스트가 그대로 담당한다.
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

테스트 DB 에는 실제 설치 순서대로 backend 첫 리비전의 표를 먼저 만든다
(`tests/backend_schema.py`, `database` 픽스처). 아무 표도 없는 DB 는 `empty_database` 다.
뉴스·메시지·공통 자료 ID 저장 규칙도 같은 방식으로 실제 DB 에서 본다
(`tests/test_*_db.py`).

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
