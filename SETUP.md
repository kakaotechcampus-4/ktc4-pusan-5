# SETUP.md

클론 후 한 번만 하는 세팅. 팀원 전원 동일하게 맞춘다.

## 0. git hook 연결 (필수)

```bash
git config core.hooksPath .githooks
```

브랜치 규칙(main 직접 커밋 금지, `feature/*`·`refactor/*` 이름 규칙)과
프론트 디자인 검사·eslint 를 커밋 시점에 돌린다. 안 걸어두면 규칙은 문서로만 존재한다.

**Windows 사용자**: 훅은 Git Bash 로 실행되므로 Git for Windows 가 설치돼 있으면 그대로 동작한다.
`bad interpreter` 에러가 나면 줄바꿈이 CRLF 로 바뀐 경우다. `.gitattributes` 가 막아주지만
이미 받은 파일이 문제면 아래로 다시 받는다.

```bash
git rm --cached -r . && git reset --hard
```

## 1. frontend 프로젝트 생성

`frontend/` 에는 이미 `src/`, 설정 파일, CLAUDE.md, DESIGN.md 가 들어있다.
Vite 프로젝트 골격만 얹으면 된다.

```bash
cd frontend
npm create vite@latest . -- --template react-ts
# "현재 폴더에 파일이 있다" → 기존 파일 유지(Ignore files and continue) 선택
```

생성 후 이 저장소에 들어있던 `src/`, `vite.config.ts`, `eslint.config.js`,
`.prettierrc.json` 이 남아있는지 확인한다. Vite 가 덮어썼으면 git 에서 되살린다.

```bash
git checkout -- src vite.config.ts eslint.config.js .prettierrc.json
```

## 2. 의존성

```bash
cd frontend
npm install
npm i react-router-dom
npm i -D tailwindcss @tailwindcss/vite
npm i -D prettier prettier-plugin-tailwindcss eslint-config-prettier
```

`npm create vite` 가 eslint, typescript-eslint, eslint-plugin-react-hooks,
eslint-plugin-react-refresh, globals 는 이미 넣어준다. 위에 추가한 건 prettier 연동뿐이다.

## 3. package.json 스크립트

생성된 `frontend/package.json` 의 `scripts` 를 아래로 맞춘다.

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "lint": "eslint .",
    "lint:fix": "eslint . --fix",
    "format": "prettier --write .",
    "check:design": "node scripts/check-design.mjs",
    "check": "npm run lint && npm run check:design"
  }
}
```

## 4. tsconfig 경로 별칭

`frontend/tsconfig.app.json` 의 `compilerOptions` 에 추가한다. `@/lib/format` 같은 import 가 이걸 쓴다.

```json
{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] }
  }
}
```

## 5. 확인

```bash
cd frontend
npm run dev            # http://localhost:5173
npm run check          # lint + 디자인 규칙
```

## 6. VSCode

`.vscode/extensions.json` 에 권장 확장이 들어있다. VSCode 가 알림으로 물어보면 설치한다.

- ESLint
- Prettier
- Tailwind CSS IntelliSense — 토큰 유틸리티(`bg-surface`, `text-h2`)를 자동완성해준다. 이거 없으면 토큰 이름을 외워야 한다.

저장 시 자동 포맷·자동 수정은 `.vscode/settings.json` 에 이미 설정돼 있다.
