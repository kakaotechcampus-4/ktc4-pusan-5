# 데이터 스키마 레퍼런스

eval 세트의 파일 4종(`case.json`, `provenance.json`, `gold.json`, `gold.lock.json`)의 필드·타입·허용 값을 정리함. 값의 **의미와 라벨링 기준**은 `../rubric.md`, **검증 규칙**은 `../validate_gold.md` 에 있고, 이 문서는 "어떤 칸이 있고 어떤 값이 들어가는가" 만 다룸.

- 위치: `ai/evals/cases/<case_id>/` (`gold.lock.json` 은 `ai/evals/`)
- 케이스 id: `c<번호>_<종목코드>_<대상일>` (예: `c09_009150_2026-10-28`)
- 시각은 모두 ISO 8601(KST, `+09:00`). 비율은 소수 둘째 자리 숫자(`-1.63`, 퍼센트 기호 없음).
- JSON 은 들여쓰기 2칸, 한글을 이스케이프하지 않음(`ensure_ascii=False`), 파일 끝에 줄바꿈 1개.

| 파일 | 모델에 주는가 | 누가 쓰나 | 해시(잠금) 대상 |
|---|---|---|---|
| `case.json` | 줌 | 조립 | 예 |
| `provenance.json` | 안 줌 | 조립 | 예 |
| `gold.json` | 안 줌 | 사람(시장 칸은 코드 값) | 예(`verification`, `status` 제외) |
| `gold.lock.json` | 안 줌 | `lock_set.py` | 해당 없음 |

## 1. `case.json` — 모델 입력

파이프라인 입력과 같은 형태(`tests/fixtures/stock_analysis` 와 같은 스키마)임. 모델은 이 파일만 봄.

| 필드 | 타입 | 설명 |
|---|---|---|
| `stock` | string | 종목명 |
| `code` | string | 종목코드 6자리(문자열, 앞자리 0 유지) |
| `target_date` | string(YYYY-MM-DD) | 대상일. 확정일만 씀(당일은 KRX `no_data`) |
| `cutoff` | string(ISO) | 누수 판정선. 대상일 18:45 KST |
| `change_pct` | number | KRX 종목 등락률(%). 러너가 마감 후 KRX 값으로 다시 덮어씀 |
| `market` | null | 항상 `null`. 러너가 KRX 로 시장 비교를 계산함 |
| `messages` | array | 아래 표. `datetime_kst` 오름차순 |

`messages[]`

| 필드 | 타입 | 설명 |
|---|---|---|
| `channel` | string | 텔레그램 채널 이름(URL 의 채널 부분) |
| `url` | string | `https://t.me/<채널>/<번호>`. gold 의 `supporting_sources` 가 이 값만 참조할 수 있음 |
| `datetime_kst` | string(ISO) | 최초 게시 시각(`telegram_messages.posted_at`) |
| `text` | string | 본문 원문 |
| `mention` | string | `mentioned`(본문에 종목명·별칭이 있음). 이 세트의 78건은 모두 이 값 |

규칙
- 메시지는 직전 거래일 15:30 초과 ~ `cutoff` 이하임. 예외는 누수 함정으로 일부러 섞은 `cutoff` 이후 메시지(현재 c09 의 2건)이고, 이것은 `case.json` 에 들어 있지만 `provenance.json` 의 `injected_after_cutoff` 에 따로 기록하며 `provenance.json` 의 `messages` 에는 넣지 않음.
- 섞은 메시지는 gold 의 근거(`supporting_sources`)로 쓸 수 없음(검증 스크립트가 오류로 처리). 모델 입력에는 일반 메시지와 구분 없이 들어감.
- 공시는 `case.json` 에 넣지 않음(접수 시각을 확인한 뒤 판단, 현재 세트는 전부 `in_case_json: false`).

## 2. `provenance.json` — 자료별 공개 시각 근거

| 필드 | 타입 | 설명 |
|---|---|---|
| `case_id` | string | 폴더 이름과 같아야 함 |
| `status` | string | 조립 상태. 현재 `draft_unverified` |
| `assembly` | object | 조립 규칙 기록(아래) |
| `messages` | array | `case.json` 메시지마다 공개 시각 근거(`injected_after_cutoff` 로 섞은 것은 제외) |
| `injected_after_cutoff` | array | 누수 함정으로 `case.json` 에 섞은 `cutoff` 이후 메시지. 없으면 `[]` |
| `disclosures_pending_time_check` | array | 공시 목록과 접수 시각 |
| `notes` | array of string | 조립 중 메모 |

`assembly`

| 필드 | 설명 |
|---|---|
| `cutoff_rule` | `cutoff` 와 `asOf` 기준 설명 |
| `window` | 입력 창. `직전 거래일(YYYY-MM-DD) 15:30 초과 ~ cutoff 이하`. 이 괄호 안 날짜를 `lock`·보강 스크립트가 파싱하므로 형식을 유지 |
| `message_filter` | 메시지 선별 규칙 설명 |
| `aliases` | 메시지 검색에 쓴 종목명·별칭 목록(한글, 영문, 약칭) |
| `change_pct_source` | 등락률 출처 설명 |
| `market` | `market` 이 `null` 인 이유 설명 |

`messages[]`

| 필드 | 설명 |
|---|---|
| `url` | `case.json` 의 URL 과 같음 |
| `datetime_kst` | `case.json` 의 시각과 같음 |
| `time_source` | 시각 출처. 현재 `telegram_messages.posted_at` |
| `verified_by_human` | 사람이 시각을 확인했는지(현재 전부 `false`) |

`injected_after_cutoff[]`: `url`, `datetime_kst`(cutoff 이후), `why`(예: "함정 9: cutoff 이후 자료를 일부러 섞음"). 보고서가 이 자료를 쓰면 `HF_LEAKAGE`.

`disclosures_pending_time_check[]`

| 필드 | 설명 |
|---|---|
| `rcept_no` | DART 접수번호(14자리) |
| `report_nm`, `flr_nm` | 공시 제목, 제출인 |
| `rcept_dt` | 접수일(날짜만) |
| `rcept_time_kst` | 접수 시각(ISO). 확인하지 못하면 `null` |
| `in_case_json` | `case.json` 에 넣었는지(현재 전부 `false`) |
| `time_source` | 시각 출처 설명(예: `KIND 접수번호 8→0 대응, 회사·제목 일치`). 시각이 `null` 이면 생략 가능 |

`rcept_time_kst` 가 `null` 인 공시는 gold 사건의 근거로 쓰지 않음.

## 3. `gold.json` — 정답지

### 3-1. 최상위

| 필드 | 타입 | 설명 |
|---|---|---|
| `case_id` | string | 폴더 이름과 같아야 함 |
| `status` | string | `skeleton`(미작성) 이외의 값이면 전체 검증. 현재 `labeled`. 값 이름은 루브릭에 정의 없음 |
| `label_source` | string | 라벨 출처. 현재 `human` |
| `trap_ids` | array of int | 노리는 함정 번호(아래 3-9) |
| `market_expectation` | object | 3-2. 파이프라인 코드가 계산한 값 |
| `time_expectation` | object | 3-3 |
| `expected_verdict` | object | `move`, `relative` 각각 판정값 |
| `confidence_level` | string | `partial` \| `none` |
| `events` | array | 3-4 |
| `acceptable_alternatives` | array | 이번 세트에서는 쓰지 않음(`[]`) |
| `forbidden_claims` | array | 3-5 |
| `unconfirmed_items` | array of string | 입력에 있으나 미확인(풍문·정정 전)인 항목 |
| `unknowns` | array of string | 입력으로 알 수 없는 영역 |
| `beginner_terms` | array of string | 초보자 설명이 필요한 용어 |
| `verification` | object | 3-6. 검증 기록 |

### 3-2. `market_expectation` — 코드 계산 값(사람이 쓰지 않음)

| 필드 | 타입 | 출처·설명 |
|---|---|---|
| `data_source` | string | `krx_close`(KRX 마감 확정값) |
| `stock_change_pct` | number | 종목 등락률. `market_compare.kospi.stock_change_rate_pct` |
| `kospi_change_pct` | number | 코스피 등락률. `market_compare.kospi.kospi_change_rate_pct` |
| `kospi_basis` | string | 코스피 비교 기준(`market_compare.kospi.kospi_basis`) |
| `excess_vs_basis_pp` | number | 코스피 대비 초과분(%p). 보고서의 코스피 비교 문장용 |
| `kospi_relation` | string | 코스피와의 관계(`market_compare.kospi.kospi_relation`, 예: `follows`, `diverges`) |
| `peer_relations` | object | 이번 세트에서는 `{}` |
| `common_move` | bool | `verify.common_move` |
| `market_led` | bool | `verify.market_led` |
| `relative_direction` | string | `verify.move_comparison`. `더` \| `덜` \| `반대로` \| `비슷하게`(코드 출력값 그대로, 한글) |
| `peer_median_pct` | number | 대형주 유니버스 중간값(%) |
| `excess_vs_peers_pp` | number | `market.excess_pct` = 종목 등락 − 대형주 중간값(%p). `relative` 층의 기준 |
| `judge_layers` | object | `{move: bool, relative: bool}`. `verify.judge_layers`(절댓값 1 이하면 false, 경계 포함) |
| `move_strength_cap` | string\|null | `partial` 또는 `null`(상한 없음). `verify.move_strength_cap` |
| `_note` | string | 값의 출처 안내 문구 |

값의 의미와 `gold` 에 미치는 영향은 `../rubric.md` §2-1. 재계산 방법은 `add_case.md` 의 시장 칸 절을 봄.

### 3-3. `time_expectation`

| 필드 | 설명 |
|---|---|
| `cutoff` | `case.json` 의 `cutoff` 와 같음 |
| `display_is_close` | 화면 기준 시각이 마감인지 |
| `display_as_of` | 화면 기준 시각(`asOf`). 마감이면 대상일 15:30 |

### 3-4. `events[]` — 사건

| 필드 | 타입 | 허용 값 |
|---|---|---|
| `id` | string | `e1`, `e2`, … (케이스 안에서 유일) |
| `summary` | string | 사건 요약(수치·주체 포함) |
| `importance` | string | `must` \| `should` \| `optional` (`must` 는 케이스당 0~2개) |
| `layer` | array | `move`, `relative` 중 해당하는 것. 원인이 아닌 맥락이면 `[]` |
| `expected_mention` | string | `factors` \| `background` \| `either` |
| `stance` | string | `bullish` \| `bearish` \| `neutral` (주가에 대한 방향) |
| `max_causal_strength` | string | `coincident` \| `possible_contributor` \| `likely_cause` |
| `supporting_sources` | array | `{url, tier}`. `url` 은 `case.json` 에 있는 것만, `tier` 는 `primary` \| `secondary` |
| `key_facts` | array of string | 근거 본문에 실제로 있어야 하는 사실(수치·주체·방향) |
| `rationale` | string | 판단 근거 한두 줄 |

공개 시각 필드는 없음(근거 메시지·공시 시각에서 계산). `direct_cause`, `definitive` 는 쓰지 않음.

### 3-5. `forbidden_claims[]` — 금지 주장

| 필드 | 허용 값 |
|---|---|
| `id` | `f1`, `f2`, … (케이스 안에서 유일, 권장 2~3개) |
| `type` | `false_cause` \| `direction_flip` \| `fabricated_cause` \| `result_as_cause` \| `market_direction` \| `advice` |
| `subject` | 주장의 주체(짧은 명사구). 유사 표현까지 같은 대상으로 봄 |
| `relation_min` | `none` \| `coincident` \| `possible_contributor` \| `likely_cause`. 이 세기 이상이면 금지 |
| `object` | 주장이 향하는 대상(`주가`, `move`, `relative` 등) |
| `direction` | `up` \| `down` \| `null` |
| `example` | 사람이 읽는 예시 문장(대조에 쓰지 않음) |

보고서 쪽 주장의 `relation` 에는 위 값 외에 `asserted`(헤지 없는 단정)가 더 있음. 대조 방법은 `../rubric.md` §5-2.

### 3-6. `verification` — 검증 기록

| 필드 | 설명 |
|---|---|
| `checklist` | `time`, `sources`, `market`, `verdict`, `forbidden` 각각 `null`(미검증) 또는 검증 결과 값 |
| `relabel` | `{done: bool, mismatches: []}`. 블라인드 재라벨링 결과 |
| `low_confidence` | 정하기 어려워 점수·개선 판정에서 제외할 항목 |
| `verified_by` | 검증자(`null` 이면 미검증) |
| `verified_at` | 검증 시각(`null` 이면 미검증) |

이 칸이 비어 있는 gold 는 정식 잠금을 하지 못함. `lock_set.py` 는 이 칸을 해시에서 뺌.

### 3-7. 판정값 요약

| 필드 | 값 |
|---|---|
| `expected_verdict.*` | `explained` \| `partially_explained` \| `no_clear_cause` |
| `confidence_level` | `partial`(적어도 한 층이 `explained`·`partially_explained`) \| `none`(두 층 모두 `no_clear_cause`) |

### 3-8. 칸 사이 일관성(검증 스크립트가 확인)

- `none` 이면 `must` 는 0개. 판단하지 않는 층(`judge_layers` false)에는 사건과 설명 판정을 두지 않음.
- `common_move` 가 true 면 `move` 는 `no_clear_cause`.
- `move_strength_cap` 이 `partial` 이면 `move` 층 사건에 `likely_cause` 를 쓰지 않음.
- `stance` 가 층의 부호와 반대인 사건의 상한은 `coincident`. 대상일 15:30 이후 공개된 근거만 있는 사건의 상한도 `coincident`.
- 근거 URL 은 `case.json` 에 있어야 하고 `key_facts` 가 그 본문에 있어야 함(표기 차이 허용).

### 3-9. `trap_ids` 번호표(이번 세트에서 쓴 것)

| 번호 | 함정 |
|---|---|
| 1 | 사후 정보 누수(`cutoff` 이후 자료를 일부러 섞음) |
| 2 | 원인 없는 급등락 |
| 4 | 시장 몫이 대부분인 날 |
| 5 | 덜 내린 하락일 / 더 내린 상승일(방향어 오류 유도) |
| 7 | 풍문·미확인·정정 |
| 8 | 상충·복수 재료 |
| 9 | 유사 종목 혼동 |
| 11 | 장중 종가 누출(이번 세트에서는 제외) |
| 17 | 호재 공시인데 주가는 급락(방향 불일치) |

## 4. `gold.lock.json` — 잠금 기록

`lock_set.py --write` 가 만듦. 사람이 직접 고치지 않음.

| 필드 | 설명 |
|---|---|
| `set_version` | 세트 버전(예: `v0`) |
| `lock_status` | `provisional`(잠정) \| `locked`(정식) |
| `locked_at` | 기록 시각(KST) |
| `set_hash` | 케이스별 해시 전체를 정규화해 구한 세트 해시(sha256) |
| `n_cases` | 케이스 수 |
| `note` | 상태 안내 문구 |
| `hash_scope` | 해시 범위 설명 |
| `cases` | 케이스 id → `{case_json, provenance_json, gold_json}` 해시 |

해시는 JSON 을 키 정렬로 정규화한 뒤 sha256 으로 구함(들여쓰기·줄바꿈 차이 무시). `gold_json` 해시는 `verification`, `status` 를 뺀 내용임. 사용법은 `../validate_gold.md` 9장과 `../README.md` 6-2.

## 5. 새 값을 추가해야 할 때

- enum 값이나 칸을 추가하면 `../rubric.md`, 이 문서, `../validate_gold.py` 의 상수(`IMPORTANCE`, `STRENGTH`, `CLAIM_TYPE` 등)를 **같이** 고침. 셋 중 하나만 고치면 검증과 문서가 어긋남.
- gold 칸을 바꾸면 해시가 달라지므로 세트 버전을 올리고 `lock_set.py --write` 로 다시 기록함.
