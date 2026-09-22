# CLAUDE.md — backend

FastAPI + Python. BASIS의 API 서버.

루트 `../CLAUDE.md` 의 **API 규약**을 먼저 읽는다. 특히 숫자를 가공하지 않고 내려주는 규칙과
`asOf` 필드는 프론트 화면이 그것에 의존하고 있으므로 예외가 없다.

## 이번 스코프

프론트 화면 두 개가 필요한 만큼만 만든다.

- 홈: 지수 시세, 관심/최근 종목 목록
- 개별 종목: 종목 기본정보, 기간별 주가 시계열, 관련 뉴스, LLM 브리핑

## 실행

```bash
uv sync                          # .venv 생성 + 의존성 설치
docker compose up -d              # DB
uv run alembic upgrade head       # 스키마를 최신으로 (서버 기동 전에 먼저)
uv run uvicorn app.main:app --reload   # http://localhost:8000
uv run pytest
uv run ruff check .
```

## DB 스키마 변경

`app/models/` 를 고치면 그걸로 끝나지 않는다. 마이그레이션을 같이 만든다.

```bash
uv run alembic revision --autogenerate -m "설명"   # migrations/versions/ 에 파일 생성
uv run alembic upgrade head                          # 로컬 DB에 반영
```

생성된 마이그레이션 파일은 꼭 열어서 확인한다. autogenerate가 의도한 대로 diff를 잡았는지,
불필요한 항목(인덱스 이름 변경 등)이 끼어있지 않은지 본 뒤 커밋한다.

이미 `create_all` 로 테이블이 만들어져 있는 로컬 DB라면(이번 alembic 도입 이전),
`uv run alembic stamp head` 로 "이미 최신 상태"라고 표시만 하고 넘어간다.
새로 DB를 띄우는 경우엔 `alembic upgrade head` 로 처음부터 만든다.

## 구조

```
Dockerfile
docker-compose.yml
pyproject.toml / uv.lock
.env.example

app/
  main.py            # FastAPI 인스턴스, CORS, 라우터 등록
  core/
    config.py         # 설정 (환경변수, API 키)
    errors.py         # 에러 응답 형태 통일
    database.py       # DB 세션·커넥션 (필요해지면 추가)
    cache.py           # Redis 등 캐시 클라이언트 (필요해지면 추가)
    scheduler.py       # 배치 스케줄러 등록 (필요해지면 추가)
  models/            # DB 테이블 (SQLAlchemy)
  schemas/           # Pydantic 요청/응답 모델 — camelCase 직렬화
  services/          # 소스별 외부 API 클라이언트 (krx, dart, ecos, kis, fred, news, telegram)
  collectors/         # services/ 로 가져온 데이터 → 정규화 → DB 저장 (폴링 배치)
  skills/             # LLM 호출 (블록 생성, 이슈 판정 등)
    prompts/           # 프롬프트 템플릿 (코드 문자열에 인라인으로 박지 않는다)
  routers/            # API 엔드포인트 (/api/stocks/*, /api/briefs/*, /api/concepts/* 등)
  repositories/       # DB 접근 로직. 모델과 서비스 사이 계층
tests/
```

지금 당장 쓰지 않는 폴더는 `.gitkeep`으로 자리만 잡아두고, 실제 필요해질 때 파일을 채운다.

## 규칙

- 라우터는 얇게. 검증 + 호출 + 응답만. 로직은 `services/`·`collectors/`·`skills/`·`repositories/` 로 분리한다.
- 응답 모델은 전부 Pydantic으로 명시한다. `dict` 를 그대로 반환하지 않는다.
  camelCase 변환은 모델 설정(`alias_generator`)으로 한 곳에서 처리한다.
- 숫자를 문자열로 만들거나 반올림해서 내려주지 않는다. 원본 값 그대로 준다.
- 시각은 timezone-aware datetime. naive datetime 을 쓰지 않는다. 응답은 ISO 8601.
- 에러는 `core/errors.py` 의 형태로만 낸다. 라우터에서 임의 형태의 에러 JSON을 만들지 않는다.
- 외부 API(KRX·DART·KIS·뉴스) 호출은 `services/` 안에서만. 라우터가 직접 부르지 않는다.
  가져온 데이터를 정규화해서 DB에 쌓는 로직은 `services/` 가 아니라 `collectors/` 에 둔다.
- LLM 응답을 그대로 신뢰해 반환하지 않는다. Pydantic 으로 파싱·검증한 뒤 내려준다.
- 비밀키는 코드에 넣지 않는다. `core/config.py` 를 통해 환경변수로만 읽는다.

## LLM 브리핑

- 프롬프트는 `skills/prompts/` 에 파일로 둔다. 코드 문자열에 인라인으로 박지 않는다.
- 브리핑 응답에는 `generatedAt` 과 근거 출처 목록을 반드시 포함한다.
- 매수·매도 판단을 생성하지 않는다. 프롬프트에 이 제약을 명시한다. 화면의 가드레일 문구와 짝이다.

## 작업 규칙

- 요청받지 않은 파일을 건드리지 않는다.
- DB 스키마를 임의로 바꾸지 않는다. 마이그레이션이 필요하면 먼저 사람에게 묻는다.
- 확실하지 않으면 추측해서 만들지 말고 물어본다.
