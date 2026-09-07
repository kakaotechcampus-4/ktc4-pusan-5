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
# TODO: 확정되면 채운다
uv sync                       # 또는 pip install -r requirements.txt
uvicorn app.main:app --reload # http://localhost:8000
pytest
ruff check .
```

## 구조

```
app/
  main.py            # FastAPI 인스턴스, CORS, 라우터 등록
  api/
    stocks.py        # /api/stocks/*
    briefs.py        # /api/briefs/*
    concepts.py      # /api/concepts/*
  schemas/           # Pydantic 응답/요청 모델 — camelCase 직렬화
  services/          # 비즈니스 로직. 라우터에 로직을 넣지 않는다
  repositories/      # DB 접근
  llm/               # 프롬프트, LLM 호출 래퍼
  core/
    config.py        # 설정 (환경변수)
    errors.py        # 에러 응답 형태 통일
tests/
```

## 규칙

- 라우터는 얇게. 검증 + 서비스 호출 + 응답만. 로직은 `services/`.
- 응답 모델은 전부 Pydantic으로 명시한다. `dict` 를 그대로 반환하지 않는다.
  camelCase 변환은 모델 설정(`alias_generator`)으로 한 곳에서 처리한다.
- 숫자를 문자열로 만들거나 반올림해서 내려주지 않는다. 원본 값 그대로 준다.
- 시각은 timezone-aware datetime. naive datetime 을 쓰지 않는다. 응답은 ISO 8601.
- 에러는 `core/errors.py` 의 형태로만 낸다. 라우터에서 임의 형태의 에러 JSON을 만들지 않는다.
- 외부 API(KRX·DART·KIS·뉴스) 호출은 `services/` 안에서만. 라우터가 직접 부르지 않는다.
- LLM 응답을 그대로 신뢰해 반환하지 않는다. Pydantic 으로 파싱·검증한 뒤 내려준다.
- 비밀키는 코드에 넣지 않는다. `core/config.py` 를 통해 환경변수로만 읽는다.

## LLM 브리핑

- 프롬프트는 `llm/prompts/` 에 파일로 둔다. 코드 문자열에 인라인으로 박지 않는다.
- 브리핑 응답에는 `generatedAt` 과 근거 출처 목록을 반드시 포함한다.
- 매수·매도 판단을 생성하지 않는다. 프롬프트에 이 제약을 명시한다. 화면의 가드레일 문구와 짝이다.

## 작업 규칙

- 요청받지 않은 파일을 건드리지 않는다.
- DB 스키마를 임의로 바꾸지 않는다. 마이그레이션이 필요하면 먼저 사람에게 묻는다.
- 확실하지 않으면 추측해서 만들지 말고 물어본다.
