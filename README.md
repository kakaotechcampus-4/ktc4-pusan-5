# ktc4-team-15

카카오테크 캠퍼스 4기 2단계 팀 프로젝트 — 부산대 5팀

| 폴더         | 내용                                 | 규칙 문서                                  |
| ------------ | ------------------------------------ | ------------------------------------------ |
| `frontend/`  | React + TypeScript + Vite + Tailwind | `frontend/CLAUDE.md`, `frontend/DESIGN.md` |
| `backend/`   | FastAPI + Python                     | `backend/CLAUDE.md`                        |
| `prototype/` | 디자인 목업 HTML                     | —                                          |

## 시작하기

### frontend

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
npm run check    # eslint + 디자인 규칙 검사
```

### backend

```bash
cd backend
# TODO
```

## 클론 후 한 번만

```bash
git config core.hooksPath .githooks
```

브랜치 규칙(main 직접 커밋 금지, `feature/*` · `refactor/*` 이름 규칙)과 프론트 검사를
커밋 시점에 돌린다. 안 걸어두면 규칙은 문서로만 존재한다.

나머지 세팅(Vite 생성, 의존성, 스크립트, tsconfig 별칭)은 **`SETUP.md`** 를 따른다.

## 작업 방식

- 화면 작업은 `frontend/` 안에서, API 작업은 `backend/` 안에서 Claude Code 세션을 연다.
  그래야 해당 폴더의 CLAUDE.md가 루트 CLAUDE.md와 함께 적용된다.
- 디자인은 문서만으로 지켜지지 않으므로, 등락 색·숫자 포맷·상태 3종은 컴포넌트와
  `check-design.mjs` 로 강제해뒀다. 자세한 내용은 `frontend/DESIGN.md`.
