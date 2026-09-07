# DESIGN.md

BASIS 프론트엔드 디자인 규칙. `frontend/` 안에서만 적용된다. 화면을 만들거나 고칠 때 이 문서를 따른다.

값 자체는 `src/styles/theme.css` 의 `@theme` 블록이 진실이다.
이 문서는 **언제 무엇을 쓰는지**만 정한다. 값이 문서와 코드가 다르면 코드가 맞다.

---

## 0. 절대 규칙 5개

1. Tailwind 임의값(`p-[15px]`, `text-[#ff0000]`) 금지. `@theme` 토큰 유틸리티만 쓴다.
2. 간격은 4의 배수 단계만: `1 2 3 4 6 8`.
3. UI를 새로 만들기 전에 `src/components/ui` 를 먼저 본다.
4. 숫자에는 `num` 클래스. 포맷은 `lib/format.ts`.
5. 상승 = 빨강, 하락 = 파랑. 예외 없음.

`npm run check:design` 이 1·4·5번을 자동으로 잡는다. 커밋 훅에서도 돌아간다.

---

## 1. 색을 쓰는 자리

| 역할 | 유틸리티 | 쓰는 곳 |
|---|---|---|
| 페이지 배경 | `bg-canvas` | 페이지, 헤더 |
| 한 단계 들어간 면 | `bg-surface` | 카드, 통계 박스, 인풋 |
| 본문 | `text-ink` | 기본 텍스트 |
| 보조 텍스트 | `text-neutral-600` / `700` | 설명, 캡션 |
| 구분선 | `border-divider` | 테두리, 구분선 |
| 브랜드 파랑 | `text-brand` `bg-brand` | 링크, 주요 버튼, 진행률, 활성 탭, kicker |
| 청록 | `text-ai` `bg-ai-100` | AI 브리핑·챗봇·개념 학습 표시 전용 |
| 상승 빨강 | `text-up` | `<Change />` 내부 전용 |
| 하락 파랑 | `text-down` | `<Change />` 내부 전용 |

- Tailwind 기본 팔레트(`blue-500`, `red-600` 등)를 쓰지 않는다. theme.css에 있는 것만 존재한다고 본다.
- 하락 파랑(`#2f6fe4`)과 브랜드 파랑(`#1b4fd8`)은 다른 값이다. 등락에 브랜드 파랑을 쓰지 않는다.
- 청록을 등락에 쓰지 않는다. (프로토타입 `../prototype/` 은 하락이 청록이었다. 폐기됨)
- 빨강은 등락 상승과 에러 이외에 쓰지 않는다. 경고 배지에 빨강을 끌어 쓰면 상승과 섞인다.

## 2. 등락 표기 — 가장 자주 틀리는 부분

```tsx
<Change value={-1.08} />                  // −1.08%   파랑
<Change value={2.41} display="arrow" />   // ▲ 2.41%  빨강
<Change value={0} />                      // 0.00%    회색
<Change value={-350} unit="price" />      // −350
```

- 표·리스트는 부호(`+`/`−`), 카드·지수 타일은 화살표(`▲`/`▼`). 둘을 같이 쓰지 않는다.
- 마이너스는 하이픈이 아니라 U+2212(`−`). 하이픈은 숫자보다 좁아서 표에서 자릿수가 안 맞는다.
- 등락률 소수점 둘째 자리, 주가는 정수에 천단위 콤마, 큰 금액은 `12조 4,300억`.
- 보합(0.00%)은 회색. 빨강도 파랑도 아니다.
- 차트 영역 채우기는 `bg-up-100` / `bg-down-100`.

**이 문서에서 하나만 지킨다면 이것이다. 등락 색을 화면 코드에서 직접 지정하지 않는다.**
`<Change />` 밖에서 `text-up` / `text-down` 을 쓰는 코드는 리뷰에서 막는다.

## 3. 타이포

- 폰트는 `IBM Plex Sans KR` 하나. 제목 `font-bold`, 강조 `font-semibold`, 본문 기본.
- 크기는 토큰 유틸리티만: `text-display`(홈 히어로 1곳 전용) `text-h1` `text-h2` `text-h3`
  `text-base` `text-sm` `text-xs` `text-kicker` `text-micro`.
- 자간도 토큰만: `tracking-brand` `tracking-kicker` `tracking-wordmark`.
- 한글은 `word-break: keep-all`. base 레이어에 전역으로 걸려 있으니 `break-all` 로 덮지 않는다.
- 라벨은 마침표 없음, 설명문은 마침표 있음. 섞지 않는다.

## 4. 레이아웃

- 모든 페이지는 `<PageShell>` 안에 들어간다. 최대 폭(`max-w-page` 1260px)·좌우 여백·헤더가 여기서 정해진다.
  페이지마다 헤더를 새로 만들거나 `max-w` 를 다시 지정하지 않는다.
- 본문 + 우측 패널 구조는 `<SplitLayout main={} side={} />`. 우측 348px 고정, `lg` 미만에서 1열.
- 섹션 제목은 `<SectionHead />` (아래 2px 실선). 카드 안 소제목은 `<Kicker />`.
- 이번 스코프에서 모바일 전용 디자인은 하지 않되, 가로 스크롤은 생기지 않게 한다.

## 5. 컴포넌트 사용 규칙

| 상황 | 쓸 것 |
|---|---|
| 등락 숫자 | `<Change />` |
| 버튼 | `<Button variant="primary" \| "secondary" \| "ghost">` |
| 카드 | `<Card>` (회색 면) / `<Card tone="plain">` (흰 면 + 테두리) |
| 수치 나열 | `<StatGrid><Stat label="시가총액" value={...} /></StatGrid>` |
| 태그 | `<Tag tone="neutral" \| "brand" \| "ai">` |
| 로딩 | `<SkeletonText lines={3} />` / `<Skeleton className="h-40" />` |
| 빈 상태 | `<Empty title description action />` |
| 에러 | `<ErrorBox onRetry />` |
| 페이지 | `<PageShell>` / `<SplitLayout />` / `<SectionHead />` |
| AI 영역 | `<GuardrailNote />` |
| 숫자·날짜 | `lib/format.ts` |

- 한 화면에 `variant="primary"` 버튼은 하나만.
- 카드 배경은 두 종류뿐이다. 새로 만들지 않는다.
- 그림자는 `shadow-sm` 까지 기본. `shadow-md` 이상은 떠 있는 것(다이얼로그, 도크)에만.
- 새 UI가 필요하면 feature 폴더가 아니라 `components/ui` 에 추가하고, 위 표에 한 줄 적는다.

## 6. 상태 — 화면마다 반드시 3종을 만든다

프로토타입에 없는 부분이다. 여기가 비면 사람마다 다른 화면이 나온다.

- **로딩**: 스피너 대신 스켈레톤. 실제 콘텐츠와 같은 자리·같은 높이로 깔아 레이아웃이 튀지 않게 한다.
- **빈 상태**: 다음 행동을 적는다. "데이터 없음"만 쓰지 않는다.
  예: `아직 관심 종목이 없습니다 / 검색해서 추가해보세요`
- **에러**: 무엇이 실패했고 무엇을 하면 되는지. 사과하지 않고 모호하게 쓰지 않는다.
  예: `시세를 불러오지 못했습니다 / 잠시 후 다시 시도해주세요` + 다시 시도 버튼
- 시세·브리핑에는 항상 기준 시각을 붙인다. `formatAsOf(date)` → `2026. 08. 21 (금) · 장 마감 기준`

## 7. AI 출력 화면 규칙

- LLM 생성 텍스트에는 `<Tag tone="ai">` 로 AI 생성임을 표시하고 생성 기준 시각을 붙인다.
- 챗봇·브리핑 영역 상단에 `<GuardrailNote />` 를 항상 노출한다.
  `초보 가드레일 ON · 매수·매도 판단은 하지 않습니다`
- 목표주가·투자의견 같은 외부 수치는 출처를 함께 적는다.
- 스트리밍 중에는 커서만 깜빡이고 레이아웃을 흔들지 않는다.

## 8. 하지 말 것

- Tailwind 임의값, `@apply`, `!important`
- Tailwind 기본 색 팔레트 (`bg-blue-500` 등)
- 컴포넌트마다 다른 `rounded-*`, 카드마다 다른 `shadow-*`
- 새 폰트, 새 아이콘 세트 추가
- 스크롤할 때 나타나는 fade-in. 모션은 사용자 행동에 대한 반응에만.
- 공용 컴포넌트를 `className` 으로 색·여백 덮어쓰기

## 9. PR 전 체크리스트

- [ ] `npm run check` 통과 (eslint + 디자인 규칙)
- [ ] 등락 숫자가 전부 `<Change />`
- [ ] 로딩·빈 상태·에러 3종 다 있음
- [ ] 기준 시각 표기 있음
- [ ] 키보드 Tab으로 조작 가능, 포커스 링 보임
- [ ] 1280px / 1024px / 768px 에서 가로 스크롤 없음
