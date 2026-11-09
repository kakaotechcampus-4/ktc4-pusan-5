# Eval 루브릭

gold 를 쓰는 사람과 재라벨링하는 사람이 같은 기준으로 쓰기 위한 정의임.

## 1. 원칙

- gold 는 **입력(`case.json`)만 보고** 씀. 모델 보고서는 보지 않음.
- 입력에서 **근거를 댈 수 있는 것**만 씀. 그날 실제 원인이라고 아는 지식은 쓰지 않음.
- 원인을 하나로 단정하지 않음. 사건마다 중요도와 "말해도 되는 최대 강도"를 따로 적음.
- 판단 근거는 `rationale` 에 한두 줄. 재라벨링에서 어긋났을 때 이 줄이 기준임.

## 2. 판정값 `expected_verdict`

두 층을 따로 판정함: `move`(종목 등락률), `relative`(대형주 유니버스 중간값 대비 초과분, 파이프라인 `market.excess_pct`). 코스피가 아니라 대형주 기준임. 코스피 비교는 보고서의 별도 비교 문장에만 쓰임.

| 값 | 뜻 |
|---|---|
| `explained` | 그 층을 직접 설명하는 재료가 있고 방향이 맞음 |
| `partially_explained` | 관련 재료는 있으나 간접·약함·일부만 설명 |
| `no_clear_cause` | 설명할 재료가 없거나, 층의 크기가 ±1 이하 |

- 층의 절댓값이 **1 이하**(등락률 %, 초과분 %p)이면 `no_clear_cause`. 이 층에는 사건을 달지 않음.
- 재료가 있어도 **방향이 반대**면(호재인데 하락) `explained` 로 쓰지 않음. `partially_explained` 또는 `no_clear_cause` 로 쓰고 이유를 적음.
- 종목 등락이 대형주 전반과 같은 몫인 날은 아래 시장 칸 규칙을 따름.

### 2-1. 시장 칸 (`market_expectation`)은 파이프라인 값을 따름

`gold.json` 의 시장 칸은 사람이 정하지 않고 파이프라인 코드(`verify.py`)가 같은 입력으로 계산한 값을 옮기고 검수만 함.

| 칸 | 뜻 | gold 에 미치는 영향 |
|---|---|---|
| `judge_layers` | 층마다 원인을 판단하는지(절댓값 1 이하면 false, 경계 포함) | false 인 층은 `no_clear_cause`, 사건을 달지 않음 |
| `common_move` | 대형주 전반이 종목과 함께 움직인 날 | true 면 `move` 판정은 `no_clear_cause`, 등락 층 원인을 세우지 않음 |
| `market_led` | 시장을 움직이는 종목(시총 비중 10% 이상: 삼성전자, SK하이닉스)이 대형주와 함께 움직인 날 | true 면 `move` 층은 시장·업종 재료를 중심으로 봄 |
| `move_strength_cap` | `partial` 이면 등락 층 인과 상한이 낮아짐 | `move` 층 사건은 `likely_cause` 를 쓰지 않고 `possible_contributor` 이하 |
| `relative_direction` | 종목과 대형주 비교 문구(`더`/`덜`/`반대로`/`비슷하게`) | 보고서의 비교 방향과 맞는지 확인 |

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
인과가 전혀 없는 사실 서술("~가 공시됐습니다")은 어느 사건에나 허용하므로 값이 아님(별도 `fact` 단계 없음, `coincident` 아래).

| 값 | 의미 | 문장 예 |
|---|---|---|
| `coincident` | 같은 시기에 발생했다 | "같은 날 ~도 있었습니다", "함께 거론됐습니다" |
| `possible_contributor` | 영향을 줬을 가능성이 있다 | "~영향을 줬을 수 있습니다" |
| `likely_cause` | 주요 원인으로 지목된다 | "~가 주된 요인으로 풀이됩니다" |


재료 유형별 **기본 상한**(예외는 `rationale` 에 이유):

| 재료 | 기본 상한 |
|---|---|
| 직접 공시 + 방향 일치 + 시간 선후 문제 없음 | `likely_cause` |
| 복수 원인인 날의 개별 재료 | `must` → `likely_cause`, `should` → `possible_contributor`, `optional` → `coincident` |
| 간접 재료(업황, 경쟁사, 전방산업) | `coincident` |
| 풍문·미확인·정정 전 보도 | `coincident` (`unconfirmed_items` 에도 적음) |
| 방향이 반대인 재료(호재인데 하락) | `coincident` |
| 결과 지표(수급 순위, 시황 요약) | `coincident` (원인 자리에 쓰지 않음) |
| 재료 공개가 급등락 **이후** | `coincident` |
| 며칠 전 재료의 재탕 | `coincident` (이미 반영된 재료라 당일 인과 부여 금지) |

- **복수 원인인 날:** `likely_cause` 를 받는 `must` 는 최대 2개. `must` 를 헤지 없이 단독·유일 원인으로 단정하면 `OVERCLAIM`, `should` 를 주된 요인으로 쓰거나 `optional` 에 영향 가능성 이상을 붙여도 `OVERCLAIM`.
- **방향이 반대인 재료:** "공시가 나온 날 주가는 약세였습니다", "호재 공시에도 하락 마감했습니다" 같은 대조 서술은 허용. "호재 공시의 영향으로 하락했습니다"는 방향 뒤집기로 `HF_FALSE_CAUSE`.

### 4-3. 그 밖의 칸

| 칸 | 값 | 기준 |
|---|---|---|
| `layer` | `move`, `relative` (복수 가능) | 사건이 답하는 층. ±1 이하 층에는 달지 않음 |
| `stance` | `bullish` / `bearish` / `neutral` | **주가에 대한** 방향 (소식이 좋은지가 아님) |
| `expected_mention` | `factors` / `background` / `either` | 원인 칸에 있어야 하는지, 배경 칸이어도 되는지 |
| `supporting_sources` | `{url, tier}` 목록 | 그 사건을 뒷받침하는 **입력 안의 source 전부**. `case.json` 에 있는 URL 만. `tier` 는 `primary`(공시·원문에 가까움) / `secondary`(증권사 요약·재인용), 기록용이고 감점 기준 아님 |
| `key_facts` | 사실 목록(수치·주체·방향) | source 가 이 사건을 증명하려면 **그 본문에** 들어 있어야 하는 사실. 원문에 실제로 있어야 함 |

**인용 판정(축 A):** URL 이 gold 의 것과 같은지가 아니라 그 source 가 사실을 증명하는지 봄.

| 조건 | 판정 |
|---|---|
| URL 이 `supporting_sources` 에 있음 | 통과 |
| URL 이 `case.json` 에 있고 본문에 사건의 `key_facts` 가 들어 있음 | 통과(gold 에 없던 근거). `supporting_sources` 에 추가 |
| URL 이 `case.json` 에 있으나 `key_facts` 를 담지 않음 | `SOURCE_MISMATCH` |
| URL 이 `case.json` 에 없음 | `HF_FABRICATED` 후보(입력 밖, 평가자가 확인할 수 없음) |

"동일 사실을 독립적으로 증명"은 출처 계보의 독립성이 아니라 그 source 본문이 사실을 직접 담고 있는지로 봄. 판정은 §5-2 처럼 의미로 대조하고 걸린 건 사람이 인용으로 확인함.

## 5. 금지 주장 `forbidden_claims`

"이렇게 쓰면 실패"인 주장. **입력만으로 반증되는 주장만** 적음. 문자열이 아니라 **구조화된 조건**으로 적고, 의미로 대조함(§5-2).

### 5-0. 적는 형식

```json
{
  "id": "f1",
  "type": "fabricated_cause",
  "subject": "외국인 매도",
  "relation_min": "none",
  "object": "주가",
  "direction": "down",
  "example": "외국인 매도가 하락 원인이다"
}
```

| 칸 | 값 | 뜻 |
|---|---|---|
| `type` | `false_cause` / `direction_flip` / `fabricated_cause` / `result_as_cause` / `market_direction` / `advice` | 금지 유형 (아래 목록) |
| `subject` | 짧은 명사구 | 주장의 주체. 유사 표현까지 같은 대상으로 봄("외국인 매도세", "외국인 순매도") |
| `relation_min` | `none` / `coincident` / `possible_contributor` / `likely_cause` | **이 세기 이상**으로 쓰면 금지. 입력에 없는 사건은 `none`(언급만 해도 지어낸 것), 원인이 아닌 재료는 `possible_contributor`(영향 가능성까지 엮으면 금지) |
| `object` | 짧은 명사구 | 주장이 향하는 대상. 대개 `주가`, 또는 `move`/`relative` 층 |
| `direction` | `up` / `down` / `null` | 주장이 말하는 주가 방향. 방향 뒤집기나 시장 비교(더/덜)에 씀 |
| `example` | 문장 | 사람이 읽기 위한 예시. **대조에 쓰지 않음** |

유형:
- `false_cause`: 원인이 아닌 재료를 인과로 단정
- `direction_flip`: 호재를 하락 원인으로, 악재를 상승 원인으로
- `fabricated_cause`: 입력에 없는 원인(수급, 외국인 매도 등)
- `result_as_cause`: 결과 지표를 원인으로
- `market_direction`: 시장 비교 방향이 반대(더/덜)
- `advice`: 투자 권유·목표가

### 5-2. 의미로 대조하는 방법

문자열 일치는 쓰지 않음. "외국인 매도가 하락 원인이다"가 gold 에 있어도 보고서가 "외국인 매도세 역시 약세에 영향을 미쳤습니다"라고 쓰면 의미가 같음.

**1단계. 보고서 주장 구조화:** 보고서의 문장마다 주장을 뽑아 `{subject, relation, object, direction, negated, quote}` 로 만듦.
- `relation` 은 `none` / `coincident` / `possible_contributor` / `likely_cause` / `asserted` 중 하나. 앞의 넷은 §4-2 척도이고, `asserted` 는 **보고서 주장에만 있는 값**(gold 라벨이 아님)이라 `likely_cause` 보다 센 단정을 가리킴.
  - `none`: 일어났다고만 씀("~가 공시됐습니다"). `coincident`: 같은 날·함께 거론.
  - `possible_contributor`: "~영향을 줬을 수 있습니다"처럼 헤지된 영향 가능성.
  - `likely_cause`: "주된 요인"처럼 원인으로 지목하되 헤지가 있음.
  - `asserted`: 헤지 없이 "~때문에", "~로 올랐습니다"처럼 인과를 단정. 어느 사건이든 상한을 넘으므로 `OVERCLAIM`.
- `negated` 는 "~때문이 아닙니다", "~는 확인되지 않았습니다" 같은 부정·모른다는 서술이면 true.
- `quote` 는 보고서 원문 문장. 모든 판정에 인용을 남김.

**2단계. gold 조건과 비교:** 아래를 모두 만족하면 그 주장이 금지 조건에 걸림.
- `subject` 가 같은 대상(동의어·상위/하위 표현 포함, 판단은 의미 기준)
- `relation` 이 `relation_min` 이상
- `object`·`direction` 이 서로 어긋나지 않음(방향이 반대로 쓰였으면 `direction_flip` 에 걸림)
- `negated` 가 아님(모른다고 쓴 문장은 걸리지 않음)

**3단계. 사람 확인:** 의미 일치 판정은 judge 가 하더라도 걸린 주장은 사람이 `quote` 로 확인함. 안 걸린 것도 `forbidden_claims`·`unknowns` 대상 주제가 보고서에 나왔는지 사람이 한 번 훑음.

이 대조는 `max_causal_strength` 의 `OVERCLAIM` 판정과 같은 `relation` 척도를 씀. 보고서 주장의 `relation` 이 해당 사건의 상한보다 세면 `OVERCLAIM`.

### 5-1. 모르는 것 `unknowns`

**입력으로 알 수 없는 것**의 목록. 보고서가 이를 단정하면 안 되고, 모른다고 쓰는 것이 정답임. 케이스 전체에 붙는 칸(사건 칸이 아님).

- 예: 수급·외국인·기관 매매, 덜/더 내린 이유, 실적이 엇갈릴 때 어느 쪽이 주가를 움직였는지, 일회성 여부(입력에 근거가 없을 때).
- `max_causal_strength` 와의 차이: 상한은 **입력에 있는 사건**을 어디까지 말해도 되는지, `unknowns` 는 **입력에 없어서** 사건 자체가 없는 영역임.
- `forbidden_claims` 와의 차이: 금지 주장은 주체·관계·방향이 정해진 조건, `unknowns` 는 영역(주제)임. 둘 다 §5-2 의 의미 대조로 판정하고, `unknowns` 는 보고서 주장의 `subject` 가 그 영역에 속하고 `relation` 이 `none` 이상(언급만 해도)이면 걸림.
- `unconfirmed_items` 와의 차이: 그쪽은 입력에 **있으나 미확인**인 항목(풍문·정정 전), `unknowns` 는 입력에 **없는** 것.
- 판정: `unknowns` 를 단정하면 입력에 없는 사실은 `HF_FABRICATED`, 원인이면 `SPURIOUS_CAUSE`. "알 수 없습니다"로 쓴 것은 감점하지 않음.
- 입력에 근거가 있는 것은 적지 않음. 원인이 없는 날(`none`)은 가장 중요한 항목을 적음.

## 6. 시각 규칙

- `cutoff` 보다 늦은 자료는 입력에 넣지 않음. 9번처럼 일부러 섞은 자료는 `provenance.json` 의 `injected_after_cutoff` 에 있고, 보고서가 쓰면 `HF_LEAKAGE`.
- 판정선은 자료 기준 `cutoff` 임(화면 기준 `asOf` 아님).
- 접수 시각을 확인하지 못한 공시는 gold 사건으로 쓰지 않음.
- **사건의 공개 시각은 gold 에 쓰지 않음.** `supporting_sources` 의 시각(메시지는 `case.json` 의 `datetime_kst`, 공시는 `provenance.json` 의 `rcept_time_kst`)에서 계산함. 가장 이른 직접 근거가 기준이고, 장 마감(15:30) 이후 공개된 재료는 상한이 `coincident` 이하임.

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
| `SOURCE_MISMATCH` | 인용한 source 본문이 사건의 `key_facts` 를 담지 않음(입력 안 source) | A |
| `UNCERTAINTY_MISSING` | 원인이 없거나 약한 날 불확실성 표시 없음 | E |
| `INCONSISTENT` | 판정·강도·서술이 서로 어긋남 | E |
| `BEGINNER` | 용어 설명 부족 등 초보자 이해 실패 | F |

## 8. 라벨링 절차

1. `case.json` 만 열어 읽음.
2. 사건 목록을 쓰고 사건마다 중요도·층·방향을 정함.
3. 사건마다 최대 강도를 §4-2 기본 상한에서 시작해 조정함.
4. 층별 `expected_verdict` → `confidence_level` 순으로 정하고 §2·§3 이 서로 맞는지 확인함.
5. 금지 주장을 §5-0 형식(주체·관계·방향)으로 쓰고 입력으로 반증되는지 확인함.
6. `unknowns` 에 입력으로 알 수 없는 것을 적음(입력에 근거가 있으면 뺌).
7. 망설인 곳은 `notes.md` 에 적음.

재라벨링은 이 순서를 gold 를 열지 않고 다시 하는 것임. 어긋난 항목은 `rationale` 로 하나로 정하고, 정하기 어려우면 `verification.low_confidence` 에 적음(점수·개선 판정에서 제외).
