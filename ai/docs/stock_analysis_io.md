# 종목 변동 요인 에이전트 — 입출력 형태

종목이 기준 시각까지 **왜 그렇게 움직였는지** 텔레그램 메시지만 근거로 설명하는 보고서 에이전트다.
이 문서는 에이전트에 무엇을 넣고 무엇이 나오는지만 정리한다. 판단 규칙(어떤 사건을 어느 칸에
쓰는지 등)은 시스템 프롬프트가 기준이다.

| 무엇 | 어디 |
| --- | --- |
| 시스템 프롬프트 (입력·출력 형식의 원본) | [app/llm/prompts/stock_analysis_system.md](../app/llm/prompts/stock_analysis_system.md) |
| 생성·래핑 | [app/services/stock_analysis/generate.py](../app/services/stock_analysis/generate.py) |
| quote 고쳐 쓰기·main_cause 재작성 | [app/services/stock_analysis/repair.py](../app/services/stock_analysis/repair.py) |
| 스키마·규칙·근거 검증 | [app/services/stock_analysis/verify.py](../app/services/stock_analysis/verify.py) |
| 러너(CLI) | [app/collectors/stock_analysis.py](../app/collectors/stock_analysis.py) |
| 샘플 입력 | [tests/fixtures/stock_analysis/](../tests/fixtures/stock_analysis/) |

> 이 문서와 프롬프트가 어긋나면 프롬프트가 맞다. 프롬프트를 고치면 `verify.py` 상수와 이 문서를 같이 고친다.

---

## 전체 흐름

```
입력 JSON ──▶ ③ generate ──▶ ④ 래퍼 ──▶ repair ──▶ ⑤ verify ──▶ parsed/<run_id>.json ──▶ (--load) ⑥ DB
            (LLM 1회,          (실행 기록)  (quote 실패 항목만
             JSON 깨지면 1회 재시도)          다시 쓰게 함)
```

```bash
uv run python -m app.collectors.stock_analysis --input tests/fixtures/stock_analysis
uv run python -m app.collectors.stock_analysis --input case.json --load
```

| 옵션 | 뜻 |
| --- | --- |
| `--input` | 입력 JSON 파일 하나, 또는 폴더(바로 아래 `*.json` 전부) |
| `--load` | 검증 결과와 함께 DB(`stock_move_analyses`)에 적재 |
| `--concurrency` | 동시 호출 수 (기본 2) |
| `--out` | 실행 디렉터리의 부모 (기본 `runs`) |

실행 하나가 디렉터리 하나다.

```
runs/<YYYYMMDD-HHMMSS>/
  inputs/<run_id>.json   받은 입력 바이트 그대로
  parsed/<run_id>.json   실행 기록 래퍼 (아래 「래퍼」)
```

`run_id` 는 `<종목명>-<target_date>-<cutoff HHMM>__r<반복>` (예: `솔마루전자-2026-09-18-1530__r1`).

---

## 1. 입력

종목·기준 시각 하나당 JSON 객체 하나.

```jsonc
{
  "stock": "솔마루전자",                       // 필수. 종목명
  "code": "999990",                           // 필수. 6자리 종목코드
  "target_date": "2026-09-18",                // 필수. YYYY-MM-DD
  "cutoff": "2026-09-18T15:30:00+09:00",      // 필수. 기준 시각. 이 시각까지의 메시지만 넣는다
  "change_pct": -4.2,                         // 필수. 숫자. 기준 시각의 등락률, 하락은 음수
  "market": {                                 // 없으면 null
    "index": "코스피",
    "change_pct": -0.5,                       // 지수 등락률
    "as_of": "15:30",                         // 지수 수치의 시각 HH:MM. cutoff 와 같으면 종가
    "url": "",
    "peer_median_pct": -0.6,                  // 이 종목을 뺀 비교 대형주 등락률 중간값. 없으면 null
    "peer_up": 5, "peer_down": 13, "peer_total": 19,
    "excess_pct": -3.6                        // change_pct − peer_median_pct. 없으면 null
    // "move_case" 는 넣지 않아도 된다. 러너가 계산해 덮어쓴다(아래)
  },
  "messages": [                               // 필수. 배열. 이미 종목·시간으로 걸러진 상태
    {
      "channel": "sample_channel_a",
      "url": "https://t.me/sample_channel_a/101",   // 출처 url 은 이 값만 쓸 수 있다
      "datetime_kst": "2026-09-18T08:10:00+09:00",
      "views": "1200",
      "text": "솔마루전자, 3분기 영업이익 잠정치 412억원… 시장 예상치 590억원 30% 하회",
      "match": "direct",                      // direct: 이 종목을 직접 다룸 | indirect: 업황·경쟁사·전방산업만
      "dup_channels": 1,                      // 같은 내용으로 묶인 메시지들의 채널 수. 묶인 게 없으면 1
      "link_bodies": [                        // 선택. 메시지 속 뉴스 링크를 cutoff 안에서 미리 연 것
        {
          "url": "https://example.com/s/a1b2c3",        // 메시지에 적힌 주소
          "final_url": "https://news.example.com/article/1001",  // 단축 URL 을 푼 주소
          "domain": "news.example.com",
          "title": "솔마루전자 3분기 영업이익 412억원, 예상치 크게 밑돌아",
          "excerpt": "기사 본문 앞 3문장 원문 그대로",  // 없으면 본문을 못 읽은 것(대개 리서치 PDF)
          "fetched_at": "2026-09-18T08:30:00+09:00"
        }
      ]
    }
  ]
}
```

### 러너가 호출 전에 보는 것

`generate.check_input()` — 하나라도 걸리면 **한 건도 호출하지 않고** 멈춘다.

- `stock`, `code`, `target_date`, `cutoff`, `change_pct`, `messages` 가 있어야 한다.
- `change_pct` 는 숫자(bool 제외), `messages` 는 배열.

### 러너가 입력에 덧붙이는 것 — `market.move_case`

모델에 보내기 직전 `excess_pct` 로 계산해 넣는다(입력에 값이 있어도 덮어쓴다). `inputs/` 사본에는 없다.

| 값 | 조건 |
| --- | --- |
| `null` | `market` 이나 `excess_pct` 가 null |
| `flat` | `abs(excess_pct) <= 1.00` |
| `opposite` | `abs(excess_pct) > 1.00` 이고 `change_pct` 와 `excess_pct` 부호가 반대 |
| `normal` | 그 밖 |

---

## 2. 모델 출력 (보고서)

모델은 JSON 객체 하나만 낸다. 첫 키 `issue_trace` 는 러너가 떼어 래퍼에 따로 두고,
**나머지가 보고서**(래퍼의 `final_text`)다.

### 판정의 두 층

보고서는 두 질문에 따로 답한다.

| 층 | 질문 | 방향의 기준 | 판정 칸 | summary 칸 |
| --- | --- | --- | --- | --- |
| `move` (등락 층) | 오늘 왜 올랐나/내렸나 | `change_pct` 부호 | `verdict` | `main_cause` |
| `relative` (상대 층) | 다른 대형주와 왜 달랐나 | `excess_pct` 부호 | `relative_verdict` | `relative` |

층의 값 절댓값이 1 이하면(상대 층은 `excess_pct` 가 null 일 때도) 그 층 판정은 `no_clear_cause` 이고
그 층 link 는 없다. **factor 하나 = 사건 하나**이고, 어느 층에 답하는지는 factor 안 `links` 로 단다.

### 전체 형태

```jsonc
{
  "ticker": "999990",
  "name": "솔마루전자",
  "date": "2026-09-18",
  "as_of": "15:30",                       // cutoff 의 HH:MM
  "change_pct": -4.2,                     // 입력 값을 옮긴 것 (0.01 차이까지 허용)
  "verdict": "explained",                 // explained | partially_explained | no_clear_cause
  "relative_verdict": "partially_explained",

  "summary": {
    "move": "오후 3시 30분 장 마감 기준 ...",   // 비울 수 없음
    "main_cause": "...",                       // 비울 수 없음. 최대 3문장
    "relative": "... 또는 null",
    "counter": "... 또는 null",               // 방향이 어긋나는 재료. background 에 있는 것만
    "unexplained": "..."                       // 비울 수 없음
  },

  "factors": [                            // 최대 4개, 중요도 순. 두 판정이 모두 no_clear_cause 면 []
    {
      "event": "사건 한 문장",              // 비울 수 없음
      "detail": "출처에서 확인되는 부연 1~2문장. 없으면 \"\"",
      "stance": "bearish",                // bullish | bearish | neutral — 사건 자체의 성질
      "unconfirmed": false,               // 출처 스스로 미확인이라 밝힌 정보에 기댔으면 true
      "sources": [                        // 최소 1개, 최대 3개
        {
          "channel": "sample_channel_a",
          "url": "https://t.me/sample_channel_a/101",  // 입력 messages[].url 그대로
          "datetime_kst": "2026-09-18T08:10:00+09:00",
          "quote": "3분기 영업이익 잠정치 412억원",      // text 또는 link_bodies[].excerpt 글자 그대로, 40자 이내
          "match": "direct",                           // 입력 값 그대로
          "is_market_recap": false                     // 시황 메시지면 true
        }
      ],
      "links": [                          // 최소 1개, 층마다 최대 1개
        {
          "layer": "move",                // move | relative
          "note": "이 층의 질문에 대한 답 1~2문장",   // 비울 수 없음
          "direction_match": true,        // stance 가 층 방향과 맞는가. true 인 link 만 단다
          "strength": "sufficient"        // sufficient | partial | insufficient
        }
      ]
    }
  ],

  "terms": [                              // 최대 8개
    { "plain": "본문에 쓴 풀어 쓴 표현(글자 그대로)", "term": "원래 전문용어" }
  ],

  "background": {                         // 세 칸 모두 있어야 함. 빈 칸은 []. 전체 최대 6개, 칸당 3개
    "bullish": [ { "text": "...", "sources": [ /* factors 의 sources 와 같은 형식 */ ] } ],
    "bearish": [],
    "neutral": [ { "text": "...", "sources": [ ... ], "watch": true } ]  // watch 는 붙일 때만
  },

  "not_found": ["검수용 문자열"],          // 화면에 안 나감

  "events": [                             // 검수용. 화면에 안 나감. REQUIRED 는 아님
    {
      "event": "사건 한 줄",
      "issue_ids": ["i1", "i3"],          // issue_trace 이슈 id
      "factor": 0,                        // placed 가 factors 일 때만
      "dup_channels": 2,                  // 숫자 | null
      "placed": "factors",                // factors | background | summary.move | dropped
      "reason": "over_cap"                // dropped 이거나 over_cap 일 때만
    }
  ]
}
```

### 칸별 값 목록

| 칸 | 허용 값 | 비고 |
| --- | --- | --- |
| `verdict`, `relative_verdict` | `explained`, `partially_explained`, `no_clear_cause` | 그 층 link 중 `sufficient` 1개 이상 → `explained`, link 는 있으나 전부 `partial`/`insufficient` → `partially_explained`, link 없음 → `no_clear_cause` |
| `factors[].stance` | `bullish`, `bearish`, `neutral` | |
| `links[].layer` | `move`, `relative` | |
| `links[].strength` | `sufficient`, `partial`, `insufficient` | 간접(`match: indirect`)만 근거이거나 `unconfirmed: true` 면 `partial` 이 상한 |
| `sources[].match` | `direct`, `indirect` | |
| `events[].placed` | `factors`, `background`, `summary.move`, `dropped` | |
| `events[].reason` | `no_change`, `mechanism_only`, `schedule_only`, `off_topic`, `over_cap`, `quote_verify_fail` | `quote_verify_fail` 은 러너만 쓴다(repair 에서 뺀 항목) |

### `issue_trace` (래퍼로 옮겨짐)

모델 출력의 맨 앞 키. 입력 메시지마다 하나.

```jsonc
"issue_trace": [
  {
    "url": "https://t.me/sample_channel_a/101",
    "issues": [
      { "id": "i1", "issue": "3분기 영업이익 예상치 하회", "relation": "direct" }
      // relation: direct | sector | market | none
    ]
  }
]
```

`direct`·`sector` 이슈 id 는 모두 `events[].issue_ids` 어딘가에 있어야 한다. 빠지면 경고(`ISSUE_UNREFERENCED`)만 남는다.

### 이전 형식 호환

옛 보고서처럼 factor 에 `links` 대신 `layer`·`size_fit`·`direction_match`·`claim` 이 직접 있으면,
검증 전에 `normalize_report()` 가 `links` 하나로 옮긴다(`note: null`, `converted: true`).

---

## 3. 래퍼 — `runs/.../parsed/<run_id>.json`

보고서 + 실행 기록. 적재 모듈이 읽는 파일이다.

### 보고서와 상태

| 키 | 뜻 |
| --- | --- |
| `run_id` | 위 형식 |
| `final_text` | 보고서 JSON 문자열(`issue_trace` 제외, repair 반영 후). 열리지 않은 회차는 원문 |
| `json_status` | `clean` 그대로 열림 · `stripped` 코드펜스·머리말을 벗겨야 열림 · `invalid` 안 열림 |
| `raw_text` | `clean` 이 아닐 때만 모델 원문 |
| `schema_problems` | `check_schema()` 결과 |
| `is_error` / `error_code` / `error` | 호출 자체 실패. `error_code`: `LLM_ERROR`, `STREAM_INTERRUPTED`, `OUTPUT_TRUNCATED`, `EMPTY_RESPONSE` |
| `asked_question` | JSON 이 안 열렸고 응답이 `?` 로 끝남 |
| `issue_trace` | 모델이 낸 이슈 목록 |
| `move_case` | 입력에 넣은 값과 같음 |

### 검증 결과

| 키 | 뜻 |
| --- | --- |
| `verify_status` | `passed` / `failed`. 스키마·규칙·근거 중 하나라도 걸리면 failed |
| `verify_problems` | `"<코드>: <상세>"` 문자열 배열 (예: `QUOTE_NOT_IN_SOURCE: factors[0].sources[0] ...`) |
| `events_status` / `events_problems` | `events` 칸 검사. `passed` / `failed` / `missing`. 판정과 별개 |
| `verify_warnings` | 실패는 아니지만 볼 것 (`DUPLICATE_SOURCES`, `MAIN_CAUSE_STALE` 등) |
| `issue_trace_warnings` / `issue_trace_stats` | 메시지 누락·이슈 미참조 경고와 집계 |

### 재시도·고쳐 쓰기 기록

| 키 | 뜻 |
| --- | --- |
| `json_retry` | `{"retried": false}` 또는 `{"retried": true, "first": {json_status, asked_question, raw_text, usage, cost, duration_ms}}`. 정상 종료인데 JSON 이 깨졌을 때만 1회 재호출 |
| `stream_interruptions` | 끊긴 시도마다 `{partial_chars, error}`. 끊김은 1회 재전송 |
| `quote_repair` | quote 가 원문에 없던 factor·background 항목마다 `{kind, result: fixed\|dropped, failed, retry_failed, quotes, ...}`. 다시 써도 없으면 항목을 빼고 `events` 에 `dropped`/`quote_verify_fail` |
| `main_cause_rewrite` | 뺀 factor 에 `move` link 가 있었을 때 `{result: rewritten\|failed, dropped, before, after, cost, error}` |

### 운영 지표

`provider`, `model`, `stream`, `max_completion_tokens`, `reasoning_effort`, `usage`, `input_tokens`,
`cost`, `cost_currency`, `cost_basis`(`provider`|`token_rates`|`unavailable`), `cost_rates`,
`truncation`(잘렸을 때만), `duration_ms`, `prompt_name`, `prompt_sha256`, `generated_at`(KST ISO 8601),
`input_path`, `input_original_path`, `input_sha256`.

---

## 4. 러너 요약 출력

`run()` 이 돌려주고 콘솔에 찍는 실행 단위 집계.

```jsonc
{
  "run_dir": "runs/20261015-101500",
  "total": 9, "passed": 7, "failed": 2, "errors": 0,
  "cost": 0.42, "currency": "USD",
  "reasons": { "QUOTE_NOT_IN_SOURCE": 1, "FLAT_MOVE": 1 },  // 보고서 기준·계열 단위 건수
  "move_cases": { "flat": 3, "opposite": 1, "normal": 4, "null": 1 },
  "opposite_with_counter": 1,
  "events": { "passed": 8, "failed": 1, "missing": 0 },
  "warned": 2,
  "issue_trace_messages": { "traced": 30, "total": 31 },
  "loaded": null                                     // --load 면 적재 건수
}
```

종료 코드: 호출 자체가 실패한 건(`errors`)이 있으면 1. 검증 실패는 데이터라 0.

---

## 알아둘 것

- **DB 적재는 아직 옛 형식 기준이다.** `stock_move_analyses` 에는 `relative_verdict`, `summary.relative`,
  `links` 를 담는 칼럼이 없다. 새 칸은 `raw_json` 에만 들어간다. 백엔드가 두 층을 화면에 내려면 적재 쪽 스키마 정리가 먼저 필요하다.
- 보고서 JSON 키는 **snake_case** 다. 루트 CLAUDE.md 의 camelCase 규약은 백엔드 응답 직렬화에서 맞춘다.
- `as_of` 는 `"HH:MM"` 문자열이다. 적재 시 `target_date` 와 합쳐 KST aware datetime 으로 저장한다.
- `not_found`, `events`, `sources[].match`, `sources[].is_market_recap` 은 검수용이라 화면에 내지 않는다.
