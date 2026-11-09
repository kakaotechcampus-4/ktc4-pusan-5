# gold 검증 스크립트 (`validate_gold.py`)

gold 를 쓰는 중에 **규칙 위반과 근거 대조를 기계적으로 확인**하는 스크립트임. 값 정의와 판단 기준은 `rubric.md` 에 있고, 이 문서는 스크립트가 무엇을 어떤 방식으로 검증하는지 정리함.

## 1. 쓰는 법

`ai/` 폴더에서 실행함. 표준 라이브러리만 써서 설치가 필요 없음.

```
python3 evals/validate_gold.py                # 전체 케이스
python3 evals/validate_gold.py c07 c10        # 케이스 id 앞부분으로 골라서
python3 evals/validate_gold.py --strict       # 아직 안 쓴(skeleton) 케이스도 오류로 처리
python3 evals/validate_gold.py --root DIR     # 케이스 폴더 위치 지정(기본 evals/cases)
```

| 표시 | 뜻 | 종료 코드 |
|---|---|---|
| ✗ 오류 | 규칙 위반. 고쳐야 함 | 하나라도 있으면 1 |
| ! 경고 | 사람이 확인할 것. 틀렸다는 뜻은 아님 | 영향 없음 |
| · 정보 | 참고(가장 이른 근거 시각, 작성 전 상태 등) | 영향 없음 |

## 2. 읽는 파일

케이스 폴더마다 세 파일을 함께 봄.

| 파일 | 쓰는 곳 |
|---|---|
| `gold.json` | 검증 대상 |
| `case.json` | 근거 메시지의 존재·본문·시각, cutoff, 대상일, 종목 등락률 |
| `provenance.json` | `injected_after_cutoff`(cutoff 이후 삽입 자료) |

## 3. 작성 단계에 따른 동작

`gold.json` 의 `status` 가 `skeleton` 인지에 따라 검증 범위가 달라짐.

| 상태 | 동작 |
|---|---|
| `skeleton`(기본) | 공통 검사(§4-1)만 하고, 비어 있는 칸 목록(`expected_verdict`, `confidence_level`, `events`, `forbidden_claims`, `unknowns`)을 정보로 알려 줌. 오류로 보지 않음 |
| `skeleton` + `--strict` | 작성하지 않은 것을 오류로 처리 |
| 그 밖의 값(예: `labeled`) | 전체 검증(§4-2~4-5) |

쓰기를 끝낸 케이스는 `status` 를 `skeleton` 이 아닌 값으로 바꿔야 전체 검증이 시작됨. 값 이름은 루브릭에 정의가 없음.

## 4. 검증 항목

### 4-1. 공통(뼈대 포함)

| 검사 | 수준 |
|---|---|
| `case_id` 가 폴더 이름과 같은가 | 오류 |
| `time_expectation.cutoff` 가 `case.json` 의 cutoff 와 같은가 | 오류 |
| 시장 칸(`judge_layers`, `common_move`, `market_led`, `relative_direction`, `excess_vs_peers_pp`)이 비어 있지 않은가 | 오류 |
| `stock_change_pct` 가 `case.json` 의 `change_pct` 와 같은가 | 경고 |

시장 칸의 값이 맞는지는 다시 계산하지 않음. 비어 있는지만 봄.

### 4-2. 판정과 확신 수준

| 검사 | 수준 | 근거 |
|---|---|---|
| `expected_verdict`, `confidence_level` 이 허용 값인가 | 오류 | §2, §3 |
| `confidence_level` 이 `none` 인데 `no_clear_cause` 가 아닌 층이 있음 | 오류 | §3 |
| `confidence_level` 이 `partial` 인데 두 층 모두 `no_clear_cause` | 오류 | §3 |
| `judge_layers` 가 false 인 층의 판정이 `no_clear_cause` 가 아님 | 오류 | §2-1 |
| `common_move` true 인데 `move` 판정이 `no_clear_cause` 가 아님 | 오류 | §2-1 |
| `explained` 인데 그 층 방향과 맞는 stance 이고 `likely_cause` 인 사건이 없음 | 오류 | §2 |
| `explained`·`partially_explained` 인데 그 층에 달린 사건이 없음 | 경고 | |
| `no_clear_cause` 인데 그 층에 `must` 사건이 있음 | 경고 | |

### 4-3. 사건(`events[]`)

| 검사 | 수준 | 근거 |
|---|---|---|
| `importance`, `stance`, `expected_mention`, `max_causal_strength`, `layer` 가 허용 값인가 | 오류 | §4 |
| 사건 id 중복, `summary` 비어 있음 | 오류 | |
| `must` 가 3개 이상 | 오류 | §4-1 |
| `confidence_level` 이 `none` 인데 `must` 가 있음 | 오류 | §4-1 |
| `judge_layers` 가 false 인 층에 사건을 담 | 오류 | §2-1 |
| `common_move` true 인 날 `move` 층에 사건을 담 | 오류 | §2-1 |
| `move_strength_cap` 이 `partial` 인데 `move` 층 사건의 상한이 `likely_cause` | 오류 | §2-1 |
| 사건의 `stance` 가 층 방향(종목 등락·초과분의 부호)과 반대인데 상한이 `coincident` 가 아님 | 오류 | §4-2 |
| 복수 원인인 날(사건 2개 이상) 중요도별 상한 초과: `must` ≤ `likely_cause`, `should` ≤ `possible_contributor`, `optional` ≤ `coincident` | 오류 | §4-2 |
| `must` 인데 `layer` 가 비어 있음 | 경고 | |

층의 방향은 `move` 는 `stock_change_pct`, `relative` 는 `excess_vs_peers_pp` 의 부호임. `stance` 가 `neutral` 이면 방향 검사를 하지 않음.

### 4-4. 근거(`supporting_sources`, `key_facts`)

| 검사 | 수준 | 근거 |
|---|---|---|
| `supporting_sources` 나 `key_facts` 가 비어 있음 | 오류 | §4-3 |
| `tier` 가 허용 값(`primary`/`secondary`)인가 | 오류 | §4-3 |
| 근거 URL 이 `case.json` 메시지에 없음(입력 밖 source) | 오류 | §4-3 |
| 근거 URL 이 `injected_after_cutoff` 삽입 자료임 | 오류 | §6 |
| 근거 메시지 시각이 cutoff 이후 | 오류 | §6 |
| 근거가 대상일 장 마감(15:30) 이후에 공개됐는데 상한이 `coincident` 가 아님 | 오류 | §4-2 |
| `key_facts` 를 어느 근거 본문에서도 못 찾음 | 오류 | §4-3 |
| `key_facts` 를 일부 토큰만 찾음 | 경고 | |
| `key_facts` 를 일부 근거에서만 못 찾음 | 경고 | `SOURCE_MISMATCH` 후보 |

- **공개 시각**은 gold 에 쓰지 않으므로, 사건의 근거 메시지 중 **가장 이른 시각**을 계산해 정보로 출력함. 장 마감 이후 판정도 이 시각을 씀.
- 장 마감 판정은 **대상일 당일** 15:30 이후만 봄. 전날 장 마감 이후부터 대상일 장 시작 전까지 나온 재료는 정상 근거임.
- 공시는 `case.json` 에 원문이 없어 근거로 쓸 수 없음. 공시 URL 을 넣으면 "case.json 에 없음" 오류가 남.

### 4-5. 금지 주장·모르는 것

| 검사 | 수준 | 근거 |
|---|---|---|
| `type`, `relation_min` 이 허용 값인가(`relation_min`: `none`/`coincident`/`possible_contributor`/`likely_cause`), `direction` 이 `up`/`down`/`null` 인가 | 오류 | §5-0 |
| `subject` 가 비어 있음, 금지 주장 id 중복 | 오류 | |
| `example` 이 없음 | 경고 | |
| `fabricated_cause` 의 `subject` 가 입력 메시지에 나옴 | 경고 | §5 |
| `forbidden_claims` 가 4개 이상(권장 2~3개) | 경고 | |
| `unknowns` 가 비어 있음 | 경고 | §5-1 |

`fabricated_cause` 는 입력에 없는 원인이어야 하므로, 입력 메시지에 그 주체가 나오면 금지가 아닐 수 있다는 경고를 냄. 비교는 공백·구두점을 빼고 하는 단순 포함 검사임.

## 5. `key_facts` 대조 방식

글자가 그대로 같아야 하는 방식은 너무 엄격해서, 표기 차이를 허용하는 단계별 대조를 씀. 본문과 `key_facts` 모두 공백·쉼표·콜론·가운뎃점을 빼고 소문자로 바꿔 비교함.

| 결과 | 조건 | 처리 |
|---|---|---|
| `exact` | 위 처리 후 글자가 그대로 들어 있음 | 통과 |
| `fuzzy` | `key_facts` 를 공백으로 나눈 토큰이 모두 의미상 일치 | 통과 |
| `partial` | 일부 토큰만 일치 | 경고(표기 차이인지 확인) |
| `none` | 하나도 일치하지 않음 | 근거 어디에도 없으면 오류 |

`fuzzy` 의 토큰 일치 기준은 아래와 같음.

| 토큰 종류 | 일치 기준 | 예 |
|---|---|---|
| 금액(조·억·만) | 원 단위로 환산해 비교. 적힌 마지막 자리의 반올림 폭을 허용 오차로 씀. `83조 3,338억원` 처럼 붙은 단위는 합침 | `83.3조원` = `83조 3,338억원`, `2만원` = `20,000원` |
| 퍼센트 | 값으로 비교(부호 무시, 반올림 폭 허용) | `8.3%` = `+8.3%` |
| 일반 숫자 | 쉼표를 뺀 값으로 비교, 끝의 단위(원·주·배 등)는 무시 | `4,601원` = `4601` |
| 낱말 | 본문에 포함되는지, 3글자 이상이면 끝 한 글자를 뺀 앞부분도 허용 | `컨센` → `컨센서스` |

오류와 경고를 나누는 기준은 **사건 단위**임. 사건의 근거 메시지 중 하나라도 `exact` 나 `fuzzy` 면 그 사건은 통과이고, 못 찾은 근거 메시지는 "그 source 를 인용하면 `SOURCE_MISMATCH` 후보"라는 경고만 냄. 묶은 메시지마다 담은 내용이 달라서 생기는 정상적인 경우가 많기 때문임.

## 6. 출력 예

```
== c09_009150_2026-10-28
  ✗ confidence_level `none` 인데 `no_clear_cause` 가 아닌 층이 있음
  ✗ e1: https://t.me/merITz_tech/19238 는 cutoff 이후 삽입 자료(injected_after_cutoff)라 근거로 쓸 수 없음
  ✗ e3: key_facts `존재하지않는사실` 가 근거 본문 어디에도 없음
  ! relative 가 `no_clear_cause` 인데 그 층에 must 사건이 있음
  · e3: 가장 이른 근거 10-28 12:01

--------------------------------------------------
케이스                            오류   경고
c09_009150_2026-10-28          11    3
합계: 오류 11건
```

## 7. 하지 않는 것(사람이 확인)

- **의미 판단:** 사건이 정말 원인인지, `max_causal_strength` 가 적절한지, `importance` 가 맞는지.
- **금지 주장이 입력으로 반증되는지:** 주체가 입력에 나오는지만 단순 포함으로 봄. 동의어나 영문 표기는 못 잡음.
- **시장 칸 값의 정확성:** KRX 를 다시 조회하지 않음. 생성 전에 파이프라인 값과 다시 대조해야 함.
- **재라벨링 결과 비교:** 두 번째로 쓴 라벨과의 비교는 하지 않음(`verification.relabel` 은 사람이 채움).
- **`key_facts` 의 줄임말:** `지배순이익` 과 `지배주주순이익` 처럼 본문과 줄임말이 다르면 `partial` 경고로만 나옴.

## 8. 자주 나는 오류와 해결

| 메시지 | 원인 | 해결 |
|---|---|---|
| `case.json 에 없음(입력 밖 source)` | 공시 URL 이나 다른 케이스의 메시지를 넣음 | 같은 사실을 담은 `case.json` 메시지 URL 로 바꿈 |
| `key_facts ... 어디에도 없음` | 본문에 없는 수치·표현을 씀 | 본문에 있는 표현 그대로 옮김 |
| `방향 반대인데 상한이 ...` | 호재인데 하락 같은 재료에 `likely_cause`·`possible_contributor` 를 줌 | 상한을 `coincident` 로 내림 |
| `근거가 대상일 장 마감 이후...` | 대상일 15:30 이후 공개된 재료에 높은 상한을 줌 | 상한을 `coincident` 로 내림 |
| `judge_layers false ...` | 판단하지 않는 층(절댓값 1 이하)에 사건이나 판정을 둠 | 그 층 사건을 빼고 `no_clear_cause` 로 둠 |
| `must 가 3개` | 핵심 사건이 너무 많음 | 중요도를 다시 나눔 |

## 9. 잠금 스크립트(`lock_set.py`)와의 관계

`validate_gold.py` 는 gold 가 규칙에 맞는지 보고, 잠금 스크립트는 **확정한 뒤에 바뀌었는지** 봄. 역할이 달라 따로 돌림.

```
python3 evals/lock_set.py --check                              # 기록과 현재 파일 비교
python3 evals/lock_set.py --write --version v0 --provisional   # 잠정 잠금 기록
python3 evals/lock_set.py --write --version v1                 # 정식 잠금 기록
```

- 기록 파일: `ai/evals/gold.lock.json`(세트 버전, `lock_status`, 기록 시각, 세트 해시, 케이스별 해시).
- 해시 대상: 케이스마다 `case.json`, `provenance.json`, `gold.json`. JSON 을 키 정렬로 정규화한 뒤 sha256 을 구함(들여쓰기·줄바꿈 차이는 무시).
- `gold.json` 에서 `verification`, `status` 는 해시에서 뺌. 검증 기록을 채우거나 상태를 바꿔도 잠금이 깨지지 않게 하기 위함.
- `provisional` 은 체크리스트·블라인드 재라벨링·`verification` 이 끝나기 전의 잠정 기록이고, 끝난 뒤 `--provisional` 없이 `--write` 하면 `locked` 가 됨.
- `--check` 는 바뀐 케이스와 파일을 출력하고, 변경이 있으면 종료 코드 1 을 냄. 정상 변경이면 세트 버전을 올리고 `--write` 로 다시 기록함.
- 권장 순서: `validate_gold.py` 오류 0건 확인 → `lock_set.py --write` → 이후 평가 전에 `lock_set.py --check`.
