# CLAUDE.md — frontend

BASIS 프론트엔드. React + TypeScript + Vite + Tailwind CSS v4 + React Router

모노레포의 `frontend/` 패키지다. 루트 `../CLAUDE.md` 의 **API 규약**도 함께 적용된다.
특히 백엔드는 숫자를 가공하지 않은 원본 값으로 주고, 포맷은 프론트가 한다.
`toFixed` 를 화면에서 직접 부르지 말고 `lib/format.ts` 를 쓴다.

## 이번 스코프

화면 두 개만 만든다. 그 외 화면은 요청받기 전까지 만들지 않는다.

- 메인(홈) — `src/features/home`
- 개별 종목 브리핑 — `src/features/stock`

## 디자인 — 코드 쓰기 전에 반드시 읽는다

@DESIGN.md

아래 다섯 개는 어떤 경우에도 예외가 없다.

1. **Tailwind 임의값 금지.** `p-[15px]`, `text-[#ff0000]`, `bg-[rgb(...)]` 를 쓰지 않는다.
   `src/styles/theme.css` 의 `@theme` 에 정의된 토큰 유틸리티만 쓴다.
2. **상승 = 빨강, 하락 = 파랑, 보합 = 회색.** 등락 숫자는 반드시 `<Change />` 로 그린다.
   화면 코드에서 `text-up` / `text-down` 을 직접 쓰지 않는다.
3. UI를 만들기 전에 `src/components/ui` 에 있는지 확인한다. 있으면 그걸 쓰고, 없으면 거기에 추가한다.
   feature 폴더 안에 공용이 될 만한 UI를 만들지 않는다.
4. 숫자는 `<Change />` / `<Stat />` 또는 `num` 클래스. 포맷은 `lib/format.ts` 함수만 쓴다.
5. 데이터를 부르는 화면은 로딩·빈 상태·에러 3종을 함께 만든다. (`SkeletonText` / `Empty` / `ErrorBox`)

`src/styles/theme.css` 는 디자인 값의 진실이다. 화면 작업 중에 이 파일을 고치지 않는다.
바꿔야 하면 먼저 사람에게 묻는다.

## 코드 컨벤션 — 코드 쓰기 전에 함께 읽는다

@convention.md

- 컴포넌트는 작고 단일 책임으로 쪼갠다. 하나가 너무 많은 일을 하면 재사용 가능한 단위로 분리한다.
- 컴포넌트·프롭스·상태·함수 이름은 서술적으로 짓는다. 줄임말로 축약하지 않는다.
- 훅은 항상 함수형 컴포넌트의 최상위에서만 호출한다. 반복문·조건문·중첩 함수 안에서 호출하지 않는다.
- Context는 여러 컴포넌트 트리에 걸쳐 필요한 상태에 사용한다. 지역 상태로 충분하면 지역 상태를 쓴다.
- 여러 하위 값이 얽히거나 다음 상태가 이전 상태에 의존하는 복잡한 상태는 `useState` 여러 개 대신 `useReducer` 를 쓴다.

## Tailwind 사용 규칙

- 간격은 4의 배수 단계만: `p-1 p-2 p-3 p-4 p-6 p-8`. `p-5`, `p-7` 같은 홀수 단계를 쓰지 않는다.
- 색 유틸리티는 의미 이름으로: `bg-canvas` `bg-surface` `text-ink` `border-divider` `text-brand` `text-ai`.
  `text-blue-500` 같은 Tailwind 기본 팔레트를 쓰지 않는다. theme.css에 정의된 것만 존재한다고 생각한다.
- 클래스 문자열이 길어지면 `cn()` 으로 줄바꿈해서 묶는다. 조건부 클래스도 `cn()`.
- 공용 컴포넌트에 `className` 으로 색·여백을 덮어쓰지 않는다. 필요하면 컴포넌트에 variant를 추가한다.
- `@apply` 를 쓰지 않는다. 공통 스타일이 필요하면 컴포넌트로 만든다.
- 클래스 순서는 prettier-plugin-tailwindcss 가 정렬한다. 손으로 맞추지 않는다.
- 자간이 필요하면 `tracking-brand` / `tracking-kicker` / `tracking-wordmark` 를 쓴다.
  `tracking-[0.09em]` 처럼 임의값을 쓰지 않는다.

## 실행

```bash
npm install
npm run dev          # http://localhost:5173
npm run build
npm run lint
npm run lint         # eslint
npm run lint:fix     # 자동 수정
npm run format       # prettier
npm run check        # lint + 디자인 규칙 — 커밋 전에 돌린다
```

## 구조

```
src/
  main.tsx                 # 엔트리, theme.css 로드
  App.tsx                  # 라우팅
  components/
    ui/                    # 공용 UI — Button, Card, Change, Tag, Stat, State
    layout/                # PageShell, Header, GuardrailNote
  features/
    home/                  # 홈 화면
    stock/                 # 종목 브리핑 화면
  lib/
    format.ts              # 숫자·날짜 포맷 (여기서만)
    cn.ts                  # className 합치기
    types.ts               # API 응답 타입      ← TODO
    api.ts                 # fetch 래퍼          ← TODO
  styles/
    theme.css              # Tailwind @theme 토큰 — 값의 진실
scripts/
  check-design.mjs       # 디자인 규칙 검사 (Node, 크로스 플랫폼)
eslint.config.js
.prettierrc.json
DESIGN.md
```

- `toFixed`, `toLocaleString` 을 화면에서 직접 부르지 않는다. 전부 `lib/format.ts`.
- API 응답 타입은 `lib/types.ts` 에 모은다.

## 작업 규칙

- 요청받지 않은 파일을 건드리지 않는다.
- 목업 데이터에는 `mock` 접두사를 붙여 실제 연동과 구분한다.
- 커밋 메시지: `feat: 종목 브리핑 차트 추가` 형식, 한국어.
- 확실하지 않으면 추측해서 만들지 말고 물어본다.

## 백엔드 연동

- API 베이스 URL은 `.env` 의 `VITE_API_BASE_URL` 로만 읽는다. 코드에 URL을 박지 않는다.
- 응답 타입은 `lib/types.ts` 에 모은다. 컴포넌트 안에서 인라인 타입을 만들지 않는다.
- 시세·브리핑 응답의 `asOf` 는 화면에 반드시 표시한다. `formatAsOf()` 를 쓴다.
- 개발 중 백엔드가 준비 안 됐으면 `mockStock` 같은 `mock` 접두사 데이터로 진행한다.

## 참고

- `../prototype/Stock_Explorer_v2.html` — 디자인 목업. 레이아웃과 정보 구조 참고용.
  인라인 스타일 덩어리이므로 **코드를 복사하지 않는다.** 토큰과 컴포넌트로 다시 짠다.
  목업의 등락 색(파랑 상승 / 청록 하락)은 폐기됐다. 빨강 상승 / 파랑 하락이 맞다.
