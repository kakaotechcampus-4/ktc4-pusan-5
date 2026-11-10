# E2E 테스트

Playwright로 브라우저를 띄워 화면 흐름을 검증한다. 단위 테스트(vitest, `src/**/*.test.ts`)와는 별개다.

## 실행

```bash
cd frontend
npx playwright install chromium   # 처음 한 번
npm run e2e:mock                  # 백엔드 없이 목업 시나리오만
npm run e2e                       # 전체 (@backend 포함, 백엔드를 먼저 띄운다)
npm run e2e:typecheck             # 목업과 src/lib/types.ts 계약이 맞는지
```

vite는 Playwright가 5174 포트로 직접 띄우고 직접 끈다. 평소 개발 서버(5173)와 겹치지 않는다.

### @backend 테스트용 백엔드

실제 로그인(`POST /api/auth/test-login`)을 쓰는 테스트는 백엔드가 8001에 떠 있어야 한다.

```bash
cd backend
docker compose up -d db           # DB가 꺼져 있을 때만
uv run alembic upgrade head
ENABLE_TEST_LOGIN=true COOKIE_SECURE=false CORS_ORIGINS='["http://localhost:5174"]' SENTRY_DSN= \
  uv run uvicorn app.main:app --host 127.0.0.1 --port 8001
```

- `ENABLE_TEST_LOGIN=true`: 테스트 로그인 엔드포인트를 켠다. 운영에서는 켜지 않는다.
- `SENTRY_DSN=`: 테스트 중 생긴 에러가 Sentry로 가지 않게 비운다.
- 테스트 로그인은 항상 같은 계정("테스트 계정")을 쓴다.

### 주소 바꾸기

| 환경변수 | 기본값 | 뜻 |
| --- | --- | --- |
| `E2E_API_URL` | `http://localhost:8001` | 백엔드 주소. 목업도 이 주소로 나가는 요청을 가로챈다 |
| `E2E_BASE_URL` | (없음) | 지정하면 vite를 띄우지 않고 그 프론트를 쓴다. 그 프론트는 `VITE_API_BASE_URL=E2E_API_URL`로 떠 있어야 한다 |

## 구조

코드가 자주 바뀌는 시기라, UI나 API가 바뀌어도 한 폴더만 고치면 되게 나눴다.

```
e2e/
├── specs/      시나리오. "무엇을 검증하나"만 쓴다. 선택자·URL·JSON을 직접 두지 않는다
├── screens/    화면별 요소 찾기와 동작. UI가 바뀌면 여기만 고친다
├── fixtures/   모든 테스트에 붙는 장치 (콘솔·네트워크 감시, API 목업, 테스트 로그인)
├── mocks/      API 경로 모음과 목업 빌더. API가 바뀌면 여기만 고친다
└── env.ts      앱·API 주소
```

| 시나리오 | 파일 | 개수 |
| --- | --- | --- |
| API 오류 처리 (500, 깨진 본문, 연결 끊김, 404) | `specs/api-errors.spec.ts` | 11 |
| 로딩 (응답 대기 중 → 본문 표시) | `specs/loading.spec.ts` | 3 |
| 로그인·세션·권한 | `specs/auth-session.spec.ts` | 3 (1개는 @backend) |
| 카카오 콜백 비정상 흐름 | `specs/kakao-callback.spec.ts` | 5 |
| 딥링크·404 | `specs/deep-link.spec.ts` | 4 (1개는 `test.fail`) |

`/no-such-path` 테스트는 404 라우트가 없어 본문이 비므로 `test.fail`로 표시해 뒀다. `App.tsx`에 404 라우트가 생기면 이 테스트가 "예상 밖 통과"로 실패한다. 그때 `test.fail`을 지운다.

## 자동으로 걸리는 검사

- **콘솔·네트워크 감시** (`fixtures/pageMonitor.ts`): `console.error`, 처리되지 않은 예외, 예상하지 못한 4xx/5xx가 생기면 테스트 끝에 실패한다. 목업이 일부러 보낸 오류는 자동으로 허용된다.
- **목업하지 않은 요청 차단** (`fixtures/apiMock.ts`): `@backend`가 아닌 테스트에서 목업하지 않은 `/api/` 요청이 나가면 501로 막고 실패시킨다. 목업을 빠뜨린 걸 바로 알 수 있다.
- **계약 검사** (`mocks/apiPaths.ts`): 엔드포인트마다 `src/lib/types.ts` 응답 타입이 붙어 있다. 백엔드 응답 형태가 바뀌어 타입이 바뀌면 `npm run e2e:typecheck`가 실패한다.

## 시나리오 추가하기

1. `specs/`의 spec은 `@playwright/test`가 아니라 `../fixtures/test`에서 `test`, `expect`, `TAG`를 가져온다.
2. 태그를 붙인다. 1단계 시나리오는 `TAG.core`, 실제 백엔드가 필요하면 `TAG.backend`도 붙인다.
3. API는 `api` fixture로 목업한다.
   - `api.guest()` / `api.signedIn()`: 로그인 상태 (`/api/auth/me`)
   - `api.homePage()` / `api.stockPage(code)`: 화면에 필요한 요청을 기본값으로 한 번에 목업
   - `api.reply(apiEndpoints.x, mockReply.ok(...))`: 엔드포인트 하나만 목업
   - `api.hold(...)` → `release()`: 응답을 붙잡아 뒀다가 원하는 시점에 보내기 (로딩 검증용)
4. 목업 값은 `mocks/`의 빌더로 만들고 필요한 필드만 덮어쓴다. 예: `mockStockOverview({ changeRate: 0 })`
5. 요소는 `screens/`의 화면 객체로 찾는다. 새 요소가 필요하면 화면 객체에 추가한다. 찾을 때는 `getByRole`/`getByLabel`을 먼저 쓰고, CSS 클래스에 기대지 않는다.
6. 테스트끼리 순서나 상태를 공유하지 않는다. 각 테스트가 필요한 상태를 스스로 만든다.
