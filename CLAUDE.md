# CLAUDE.md

BASIS — 주식 초보자를 위한 시장 이해 서비스.
종목이 왜 움직였는지 브리핑으로 설명하고, 모르는 개념은 그 자리에서 학습으로 연결한다.

모노레포다. 작업할 폴더 안에서 세션을 연다.

```
frontend/   React + TypeScript + Vite + Tailwind   → 세부 규칙: frontend/CLAUDE.md, frontend/DESIGN.md
backend/    FastAPI + Python                        → 세부 규칙: backend/CLAUDE.md
prototype/  디자인 목업 (Stock_Explorer_v2.html)
SOURCES.md  데이터 소스 정리
```

- 화면 작업은 `frontend/` 안에서, API 작업은 `backend/` 안에서 세션을 연다.
  그러면 해당 폴더의 CLAUDE.md와 이 파일이 함께 적용된다.
- 루트에서 작업하는 건 API 연동처럼 양쪽을 같이 건드릴 때만이다.

## 이번 스코프

화면 두 개. 이 밖의 화면은 요청받기 전까지 만들지 않는다.

- 메인(홈)
- 개별 종목 브리핑

## 양쪽이 지켜야 하는 API 규약

프론트와 백엔드가 어긋나면 가장 먼저 깨지는 게 숫자 표기다. 아래를 고정한다.

- **백엔드는 가공하지 않은 값을 준다.** 포맷은 프론트가 한다.
  - 주가 `62400` (문자열 `"62,400"` 아님)
  - 등락률 `-1.08` (`"−1.08%"` 아님)
  - 등락액 `-680`
  - 시가총액 `372000000000000` (`"372조"` 아님)
- **시각은 ISO 8601 문자열.** 표시 문구는 프론트가 만든다.
  - `"asOf": "2026-08-21T15:30:00+09:00"`
  - 시세·브리핑 응답에는 `asOf` 를 반드시 포함한다. 화면에 기준 시각을 띄워야 한다.
- **JSON 키는 camelCase.** 백엔드 내부는 snake_case를 쓰되 응답 직렬화에서 변환한다.
- **에러는 형태를 고정한다.** 프론트가 에러 화면을 하나로 처리할 수 있어야 한다.
  ```json
  { "error": { "code": "STOCK_NOT_FOUND", "message": "종목을 찾을 수 없습니다" } }
  ```
- **LLM 생성 필드는 표시가 필요하다.** 브리핑·요약 응답에 `generatedAt` 과 출처 목록을 함께 준다.
  화면에서 AI 생성임을 표시하고 가드레일 문구를 노출한다.

## 브랜치 전략

```
main                    보호. PR merge만 허용. 직접 push 금지
 ↑ 수요일 · 토요일 PR    멘토 코드리뷰. approve 되면 main으로 merge
develop                 기본 브랜치. 팀에서 자유롭게 관리
 ↑ 기능별 PR             feature/* → develop, 팀 내 리뷰
 ↑ 핫픽스                간단한 리팩토링은 develop에 직접 push 가능
feature/<이슈명>         각자 기능 단위. develop에서 생성
refactor/<내용>          멘토 피드백 반영. develop에서 생성
```

작업을 시작하기 전에 항상 확인한다.

1. `git branch --show-current` 로 현재 브랜치를 확인한다.
2. `main` 이면 즉시 멈춘다. main에서 커밋하지 않는다.
3. 새 기능이면 `git switch develop && git pull && git switch -c feature/<이슈명>`.
4. 브랜치 이름은 `feature/` 또는 `refactor/` 로 시작한다. 그 외 이름을 만들지 않는다.

커밋·푸시를 요청받았을 때 현재 브랜치가 규칙에 맞지 않으면, 그대로 진행하지 말고 사람에게 먼저 알린다.

`.githooks/pre-commit` 이 이걸 기계적으로 막는다. 클론 후 한 번 실행한다.

```bash
git config core.hooksPath .githooks
```

## 작업 규칙

- 요청받지 않은 파일을 건드리지 않는다.
- 목업 데이터에는 `mock` 접두사를 붙여 실제 연동과 구분한다.
- 커밋 메시지: `feat(frontend): 종목 브리핑 차트 추가` 형식, 한국어. scope는 `frontend` / `backend`.
- 확실하지 않으면 추측해서 만들지 말고 물어본다.
