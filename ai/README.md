# ai/

증권사 애널리스트 리포트를 모아 DB에 넣는 수집 파이프라인. 나중에 에이전트도 여기 들어온다.

`backend/` 와 **같은 Postgres 를 쓰지만 별개 프로젝트다.** 각자 `pyproject.toml` 과
가상환경을 갖는다. 모노레포 규칙대로 작업할 때 이 폴더 안에서 세션을 연다.

```
ai/
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
여기 둘로 갈라진다. 그래서 backend 의 `create_all` 은 `analyst_reports` 를 모르고,
여기 `create_all` 은 `news` 를 모른다. 각자 자기 표만 만든다 — 같은 DB 라도 충돌하지 않는다.
나중에 API 가 리포트를 읽어야 하면 그때 `AnalystReport` 모델을 backend 에서
import 하거나 읽기 전용 쿼리를 쓴다.

## 실행

```bash
cd ai
uv sync

# Postgres 는 backend/docker-compose.yml 것을 같이 쓴다
cd ../backend && docker compose up -d db && cd ../ai

# 최근 7일 리포트 수집 (표가 없으면 처음 한 번 만든다)
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
