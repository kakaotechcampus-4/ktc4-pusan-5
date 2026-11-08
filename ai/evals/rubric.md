# Eval 루브릭

gold 를 쓰는 사람과 재라벨링하는 사람이 같은 기준으로 쓰기 위한 정의임.

## 1. 원칙

- gold 는 **입력(`case.json`)만 보고** 씀. 모델 보고서는 보지 않음.
- 입력에서 **근거를 댈 수 있는 것**만 씀. 그날 실제 원인이라고 아는 지식은 쓰지 않음.
- 원인을 하나로 단정하지 않음. 사건마다 중요도와 "말해도 되는 최대 강도"를 따로 적음.
- 판단 근거는 `rationale` 에 한두 줄. 재라벨링에서 어긋났을 때 이 줄이 기준임.

## 2. 판정값 `expected_verdict`

두 층을 따로 판정함: `move`(종목 등락률), `relative`(코스피 대비 초과분).

| 값 | 뜻 |
|---|---|
| `explained` | 그 층을 직접 설명하는 재료가 있고 방향이 맞음 |
| `partially_explained` | 관련 재료는 있으나 간접·약함·일부만 설명 |
| `no_clear_cause` | 설명할 재료가 없거나, 층의 크기가 ±1 이하 |

- 층의 절댓값이 **1 이하**(등락률 %, 초과분 %p)이면 `no_clear_cause`. 이 층에는 사건을 달지 않음.
- 재료가 있어도 **방향이 반대**면(호재인데 하락) `explained` 로 쓰지 않음. `partially_explained` 또는 `no_clear_cause` 로 쓰고 이유를 적음.
- 종목 등락 ≈ 코스피 등락인 날은 `relative` 를 `no_clear_cause` 로 둠.

## 3. 확신 수준 `confidence_level`

값은 `partial` / `none` 두 개. **`clear` 는 쓰지 않음**(주가 원인은 전문가도 확정하기 어려움).

| 값 | 뜻 |
|---|---|
| `partial` | 관련 재료가 있음(직접·간접·복수) |
| `none` | 입력에서 원인을 말할 근거가 없음 |

- `none` ↔ 두 층 모두 `no_clear_cause`. `partial` ↔ 적어도 한 층이 `explained` 또는 `partially_explained`.

## 4. 사건 `events[]`

### 4-1. 중요도 `importance`

| 값 | 기준 |
|---|---|
| `must` | 빠지면 오답. 움직임 설명의 핵심 재료 |
| `should` | 있으면 좋음. 보조·간접 재료 |
| `optional` | 없어도 무방. 맥락 정보 |

`must` 는 케이스당 **0~2개**. 원인 재료가 없는 날(`none`)은 0개. 3개 이상이면 중요도를 다시 나눔.

### 4-2. 최대 강도 `max_causal_strength`

보고서 문장이 이 사건을 어느 세기까지 말해도 되는지. 보고서가 이보다 세면 `OVERCLAIM`.
`definitive`(원인 단정)는 gold 에서 **전면 금지**. "~때문에 ~했습니다"는 항상 상한 초과임.

| 값 | 의미 | 문장 예 |
|---|---|---|
| `fact` | 이런 일이 있었음. 인과 없음 | "~가 공시됐습니다" |
| `coincident` | 같은 날 있었음, 관련 가능성 | "같은 날 ~도 있었습니다" |
| `likely_cause` | 영향을 줬을 가능성이 큼 | "~영향으로 보입니다" |

재료 유형별 **기본 상한**(예외는 `rationale` 에 이유):

| 재료 | 기본 상한 |
|---|---|
| 직접 공시 + 방향 일치 + 시간 선후 문제 없음 | `likely_cause` |
| 복수 원인인 날의 개별 재료 | `must` → `likely_cause`, `should` → `coincident`, `optional` → `fact` |
| 간접 재료(업황, 경쟁사, 전방산업) | `coincident` |
| 풍문·미확인·정정 전 보도 | `coincident` (`unconfirmed_items` 에도 적음) |
| 방향이 반대인 재료(호재인데 하락) | `coincident` |
| 결과 지표(수급 순위, 시황 요약) | `fact` |
| 재료 공개가 급등락 **이후** | `coincident` 이하 |
| 며칠 전 재료의 재탕 | `fact` |

- **복수 원인인 날:** `likely_cause` 를 받는 `must` 는 최대 2개. 단독·유일 원인으로 쓰면 `must` 도 `OVERCLAIM`, `should` 를 주도 원인으로 쓰거나 `optional` 에 인과를 붙여도 `OVERCLAIM`.
- **방향이 반대인 재료:** "공시가 나온 날 주가는 약세였습니다", "호재 공시에도 하락 마감했습니다" 같은 대조 서술은 허용. "호재 공시의 영향으로 하락했습니다"는 방향 뒤집기로 `HF_FALSE_CAUSE`.

### 4-3. 그 밖의 칸

| 칸 | 값 | 기준 |
|---|---|---|
| `layer` | `move`, `relative` (복수 가능) | 사건이 답하는 층. ±1 이하 층에는 달지 않음 |
| `stance` | `bullish` / `bearish` / `neutral` | **주가에 대한** 방향 (소식이 좋은지가 아님) |
| `expected_mention` | `factors` / `background` / `either` | 원인 칸에 있어야 하는지, 배경 칸이어도 되는지 |
| `published_at` | ISO 8601 | 공시는 DART 접수 시각, 메시지는 `posted_at`. `cutoff` 이전이어야 함 |
| `acceptable_sources` | URL 목록 | `case.json` 에 있는 URL 만 |
| `must_cite_quote_contains` | 단어 목록 | 인용 문장에 들어가야 할 핵심어. 원문에 실제로 있어야 함 |

## 5. 금지 주장 `forbidden_claims`

"이렇게 쓰면 실패" 문장. **입력만으로 반증되는 주장만** 적음.

- 단정: 원인이 아닌 재료를 "~때문에"로 쓴 문장
- 방향 뒤집기: 호재를 하락 원인으로, 악재를 상승 원인으로
- 입력에 없는 원인(수급, 외국인 매도 등)
- 결과 지표를 원인으로
- 시장 비교 방향이 반대(더/덜)
- 투자 권유·목표가

### 5-1. 모르는 것 `unknowns`

**입력으로 알 수 없는 것**의 목록. 보고서가 이를 단정하면 안 되고, 모른다고 쓰는 것이 정답임. 케이스 전체에 붙는 칸(사건 칸이 아님).

- 예: 수급·외국인·기관 매매, 덜/더 내린 이유, 실적이 엇갈릴 때 어느 쪽이 주가를 움직였는지, 일회성 여부(입력에 근거가 없을 때).
- `max_causal_strength` 와의 차이: 상한은 **입력에 있는 사건**을 어디까지 말해도 되는지, `unknowns` 는 **입력에 없어서** 사건 자체가 없는 영역임.
- `forbidden_claims` 와의 차이: 금지 주장은 구체적 문장, `unknowns` 는 영역이라 표현이 달라도 같은 영역을 단정하면 걸림.
- `unconfirmed_items` 와의 차이: 그쪽은 입력에 **있으나 미확인**인 항목(풍문·정정 전), `unknowns` 는 입력에 **없는** 것.
- 판정: `unknowns` 를 단정하면 입력에 없는 사실은 `HF_FABRICATED`, 원인이면 `SPURIOUS_CAUSE`. "알 수 없습니다"로 쓴 것은 감점하지 않음.
- 입력에 근거가 있는 것은 적지 않음. 원인이 없는 날(`none`)은 가장 중요한 항목을 적음.

## 6. 시각 규칙

- `cutoff` 보다 늦은 자료는 입력에 넣지 않음. 9번처럼 일부러 섞은 자료는 `provenance.json` 의 `injected_after_cutoff` 에 있고, 보고서가 쓰면 `HF_LEAKAGE`.
- 판정선은 자료 기준 `cutoff` 임(화면 기준 `asOf` 아님).
- 접수 시각을 확인하지 못한 공시는 gold 사건으로 쓰지 않음.

## 7. 실패 유형

**hard fail**(하나라도 있으면 그 보고서는 `Reject`):

| 코드 | 정의 |
|---|---|
| `HF_LEAKAGE` | `cutoff` 이후 정보를 사용 |
| `HF_FABRICATED` | 입력에 없는 사실·출처·수치 |
| `HF_CONTRADICTS` | 인용 출처와 반대로 서술 |
| `HF_FALSE_CAUSE` | gold 가 `none`(또는 방향 불일치)인데 원인을 단정 |
| `HF_MARKET_WRONG` | 시장 비교 방향(더↔덜)·수치 오류 |
| `HF_ADVICE` | 매수·매도 권유, 목표가 |

**일반 실패:**

| 코드 | 정의 | 축 |
|---|---|---|
| `OVERCLAIM` | 문장 강도 > gold `max_causal_strength` | B |
| `OMISSION` | gold `must` 누락. `upstream`(입력에 없음) / `generation`(입력에 있는데 안 담음)으로 구분 | C |
| `SPURIOUS_CAUSE` | gold 에 없고 수용 불가인 원인 | C |
| `PLACEMENT` | 원인 칸과 배경 칸을 바꿔 둠 | C |
| `SOURCE_MISMATCH` | 주장과 인용 출처의 의미가 안 맞음 | A |
| `UNCERTAINTY_MISSING` | 원인이 없거나 약한 날 불확실성 표시 없음 | E |
| `INCONSISTENT` | 판정·강도·서술이 서로 어긋남 | E |
| `BEGINNER` | 용어 설명 부족 등 초보자 이해 실패 | F |

## 8. 라벨링 절차

1. `case.json` 만 열어 읽음.
2. 사건 목록을 쓰고 사건마다 중요도·층·방향을 정함.
3. 사건마다 최대 강도를 §4-2 기본 상한에서 시작해 조정함.
4. 층별 `expected_verdict` → `confidence_level` 순으로 정하고 §2·§3 이 서로 맞는지 확인함.
5. 금지 주장을 쓰고 입력으로 반증되는지 확인함.
6. `unknowns` 에 입력으로 알 수 없는 것을 적음(입력에 근거가 있으면 뺌).
7. 망설인 곳은 `notes.md` 에 적음.

재라벨링은 이 순서를 gold 를 열지 않고 다시 하는 것임. 어긋난 항목은 `rationale` 로 하나로 정하고, 정하기 어려우면 `verification.low_confidence` 에 적음(점수·개선 판정에서 제외).
