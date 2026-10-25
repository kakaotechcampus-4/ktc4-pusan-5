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
    // "judge_layers"·"common_move" 는 넣지 않아도 된다. 러너가 계산해 덮어쓴다(아래)
  },
  "messages": [                               // 필수. 배열. 이미 종목·시간으로 걸러진 상태
    {
      "channel": "sample_channel_a",
      "url": "https://t.me/sample_channel_a/101",   // 출처 url 은 이 값만 쓸 수 있다
      "datetime_kst": "2026-09-18T08:10:00+09:00",
      "views": "1200",
      "text": "솔마루전자, 3분기 영업이익 잠정치 412억원… 시장 예상치 590억원 30% 하회",
      "match": "direct",                      // direct: 이 종목을 직접 다룸(여러 소식 중 한 줄이라도) | indirect: 업황·경쟁사·전방산업만
      "kind": "news",                         // flow_rank | market_recap | theme_recap | news_digest | disclosure | news | other
      "after_prev_close": false,              // true 면 직전 거래일 장을 정리한 시황(오늘 원인이 아님)
      "first_seen_kst": null,                 // 직전 구간에 같은 내용이 처음 나온 시각. 없으면 null
      "dup_channels": 1,                      // 같은 내용으로 묶인 메시지들의 채널 수. 묶인 게 없으면 1
      "link_bodies": [                        // 선택. 메시지 속 뉴스 링크를 cutoff 안에서 미리 연 것. 프롬프트는 설명하지 않는다(지금 입력에 없음), 검증은 excerpt 도 quote 원문으로 본다
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

- `kind`·`after_prev_close`·`first_seen_kst` 는 입력 생성 단계가 붙인다. 러너 `check_input()` 은 보지 않는다.
  그날 시장 시황·테마 동향 메시지가 종목과 상관없이 `match: indirect` 로 최대 3건 함께 들어온다.

### 러너가 모델에 보내는 입력 — `generate.model_input()`

받은 입력을 그대로 보내지 않는다. `inputs/` 사본은 받은 바이트 그대로이고, 같은 함수로 언제든 다시 만들 수 있다.
검증·출처 대조는 나누기 전 입력 전체로 한다.

- **메시지를 세 칸으로 나눈다**(`verify.split_messages`).

  | 칸 | 들어가는 메시지 | 프롬프트의 용도 |
  | --- | --- | --- |
  | `messages` | `news`·`news_digest`·`disclosure`·`other`·`theme_recap`, kind 없음 | 근거. theme_recap 은 이 종목 업종 단락만 sector 근거 |
  | `market_context` | `market_recap`, `after_prev_close: true`(kind 무관) | `summary.move` 의 시장 설명에만. 출처 금지. after_prev_close 는 참고만 |
  | `flow` | `flow_rank` | factor `detail`·`background` 보조 근거만 |

  `messages` 칸 메시지에는 입력 순서대로 `id`(`m1`…`mN`)를 붙인다(`verify.message_ids`). `issue_trace` 는
  이 칸만 `m1` 부터 순서대로 N개 나열하고, 누락 검사(`ISSUE_TRACE_MISSING_URL`)도 id 기준이다.
- **`market` 에 계산 칸을 넣는다**(`judge_layers`·`common_move`, 아래). 입력에 값이 있어도 덮어쓴다.
  `market` 이 null 이면 넣지 않는다. 계산은 verify 의 함수 한 곳이고 검증도 같은 함수를 본다.
- `move_case` 는 모델에 보내지 않는다. 래퍼 `move_case` 와 러너 집계에만 남긴다.

`judge_layers` — 층마다 이 입력에서 원인을 판단하는가. `false` 인 층에는 link 를 달지 않고 그 층 판정은 `no_clear_cause`.

| 키 | `true` 조건 |
| --- | --- |
| `move` | `abs(change_pct) > 1.00` |
| `relative` | `excess_pct` 가 있고 `abs(excess_pct) > 1.00` |

`common_move` — 대형주 전반이 같은 방향으로 함께 움직인 날. `change_pct` 와 `peer_median_pct` 부호가 같고
`abs(peer_median_pct) >= abs(change_pct) × 0.5` 이며 `judge_layers.relative` 가 `false`. `peer_median_pct` 가 null 이면 null.
`true` 면 그날은 등락 층 factor 를 세우지 않는다(`verdict` 는 `no_clear_cause`). 시장 사건(`relation: market`)은
`summary.main_cause` 의 배경 문장, 종목·업종 재료는 `background` 로 간다. `main_cause` 는 "대형주 전반이 함께 오른(내린) 날이었습니다."
+ (시장을 움직인 사건이 있으면) 배경 한 문장 + "이 종목만의 원인은 따로 확인되지 않았습니다." 다. 앞뒤 문장은 러너가 붙이고 모델은
배경 문장만 쓴다(`finalize.fix_main_cause`). 이날 시장 사건은 `summary.move` 에 쓰지 않는다. 어기면 경고 `COMMON_MOVE_WITH_MOVE_LINK`.

`universe_weight` — 대형주 유니버스 안 시총 비중(러너 종목 표 `stock_meta.json`, 스냅숏). **0.10 이상이면 시장을 움직이는
종목**으로 보고 `common_move` 를 false, `move_strength_cap` 을 null 로 둔다(`verify.is_market_mover`, 상수 `MARKET_MOVER_WEIGHT`).

모델 입력 맨 위 `main_cause_sentences` — `summary.main_cause` 에서 모델이 쓸 문장 수. common_move 날 1, market_led 날 2, 그 밖 3(`verify.main_cause_sentences`). 러너 고정 문장을 더해도 3문장 이하가 되게 한다. 넘으면 경고 `MAIN_CAUSE_TOO_LONG`.

모델 입력 맨 위 `sector` — 종목 업종 라벨 목록(`stock_meta.json`, 예: SK스퀘어 `["지주", "반도체"]`). 테마 동향의 업종 단락과
`relation: sector`("라벨 업종과 그 전방산업")를 가르는 기준이다. 표에 없는 종목은 null. 사업 설명 문장은 넣지 않는다.

**라벨 기준**: 테마 동향이 그 종목을 묶는 이름이거나, 그 사업의 수주·판매 소식이 주가를 움직인다고 시장이 보는 주요 사업.
한 종목 라벨은 많아야 3~4개. 이름은 테마 동향에서 실제로 쓰는 업종명에 맞춘다. 라벨 업종의 부품·납품 업체를 묶은 단락
(예: 「갤럭시 부품주」)은 그 업종 단락으로 보지 않는다(프롬프트 1부).

`market_led` — 시장을 움직이는 종목(`is_market_mover`)이 비중 예외가 없었다면 `common_move` 였을 날(부호 같음 + 대형주 몫 절반 이상 +
상대 층 판단 안 함). 이날 등락 층 factor 는 시장·업종 재료(relation market·sector)로만 세우고 종목 고유 재료(relation direct)는 background 로 둔다
(어기면 경고 `MARKET_LED_DIRECT_FACTOR`). `main_cause` 는 "대형주 전반이 함께 오른(내린) 날이었습니다."(러너가 붙임) → 시장·업종 사건(모델) 순서이고, 이날 시장 사건은
`summary.move` 에 쓰지 않는다. `verify.market_led`, `common_move` 와 같은 곳.

`move_comparison` — `summary.move` 비교 표현. 상대 층을 판단하지 않으면 "비슷하게", 종목·대형주 중간값 부호가 반대면 "반대로",
excess 가 종목 등락과 같은 방향이면 "더", 반대 방향이면 "덜". 값이 없으면 null(`verify.move_comparison`).

`move_strength_cap` — 등락 층 link strength 상한. 종목 등락 중 대형주 몫이 절반 이상이고 등락 층을 판단하는 날
`"partial"`, 그 밖 `null`. 검증 `MOVE_SUFFICIENT_STOCK_ONLY` 와 같은 함수(`verify.move_strength_cap`)이고, 어기면
judge 재시도 대상이다.

`move_case` — 래퍼 집계용 이름표(모델에 보내지 않음).

| 값 | 조건 |
| --- | --- |
| `null` | `market` 이나 `excess_pct` 가 null |
| `flat` | `abs(excess_pct) <= 1.00` |
| `opposite` | `abs(excess_pct) > 1.00` 이고 `change_pct` 와 `excess_pct` 부호가 반대 |
| `normal` | 그 밖 |

---

### 직접 언급·테마 동향이 0건이면 — 정형 보고서

`messages` 칸에 `match: "direct"` 메시지와 `kind: "theme_recap"` 메시지가 하나도 없으면(시장 시황·매매 순위만 있어도) LLM 을 부르지 않고
`generate.canned_report()` 로 정형 보고서를 낸다. 두 판정 `no_clear_cause`, `factors`·`background`·`terms`·`events` 는 비고,
`summary.move` 는 입력 숫자로 채운 문장, `main_cause` 는 "제공된 메시지에서 확인된 원인은 없습니다."(`common_move` 날은
앞에 "대형주 전반이 함께 오른/내린 날이었습니다."), `unexplained` 는 "이 종목을 직접 다룬 소식이 수집되지 않았습니다."
래퍼 `skipped_llm: "NO_DIRECT_MESSAGES"`, 비용 0. 테마 동향이 있으면 업종 단락이 sector 근거가 될 수 있어
LLM 을 부른다(`generate.needs_llm`).

## 2. 모델 출력 (보고서)

모델은 JSON 객체 하나만 낸다. 첫 키 `issue_trace` 는 러너가 떼어 래퍼에 따로 두고,
**나머지가 보고서**(래퍼의 `final_text`)다.

### 판정의 두 층

보고서는 두 질문에 따로 답한다.

| 층 | 질문 | 방향의 기준 | 판정 칸 | summary 칸 |
| --- | --- | --- | --- | --- |
| `move` (등락 층) | 오늘 왜 올랐나/내렸나 | `change_pct` 부호 | `verdict` | `main_cause` |
| `relative` (상대 층) | 다른 대형주와 왜 달랐나 | `excess_pct` 부호 | `relative_verdict` | `relative` |

입력 `market.judge_layers` 가 `false` 인 층(층의 값 절댓값이 1 이하, 상대 층은 `excess_pct` 가 null 일 때도)은
그 판정이 `no_clear_cause` 이고 그 층 link 는 없다. 어기면 러너가 같은 입력으로 한 번 다시 부른다(`judge_retry`). **factor 하나 = 사건 하나**이고, 어느 층에 답하는지는 factor 안 `links` 로 단다.

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
          "quote": "3분기 영업이익 잠정치 412억원",      // 메시지 text 글자 그대로, 40자 이내
          "match": "direct",                           // 입력 값 그대로
          "is_market_recap": false                     // 입력 kind 가 market_recap·theme_recap 이면 true. 검증은 입력 kind 를 본다
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

  "events": [                             // 검수용. 화면에 안 나감. REQUIRED 는 아님. factors·background 에 실제로 적은 사건만
    {
      "event": "사건 한 줄",
      "issue_ids": ["i1", "i3"],          // issue_trace 이슈 id
      "factor": 0,                        // placed 가 factors 일 때만
      "background": { "slot": "bearish", "index": 0 },  // placed 가 background 일 때만(필수). 그 사건을 담은 항목 자리
      "dup_channels": 2,                  // 숫자 | null
      "placed": "factors"                 // factors | background. dropped 는 러너만 쓴다(아래)
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
| `links[].strength` | `sufficient`, `partial`, `insufficient` | 출처 중 하나라도 direct 이고 방향이 맞으면 `sufficient`, direct 가 없으면 `partial`. 반대 재료는 낮추지 않는다(counter 로). `unconfirmed: true` 와 대형주 몫이 절반 이상인 날 등락 층 종목 고유 재료는 `partial` 이 상한 |
| `sources[].match` | `direct`, `indirect` | |
| `events[].placed` | `factors`, `background`, `dropped` | 모델은 `factors`·`background` 만. `dropped` 는 러너가 quote 실패로 뺀 항목 |
| `events[].reason` | `quote_verify_fail` | `dropped` 일 때만. 러너만 쓴다(repair) |

### `issue_trace` (래퍼로 옮겨짐)

모델 출력의 맨 앞 키. `messages` 칸 메시지마다 하나, `m1` 부터 순서대로(이슈가 없거나 전부 none 이어도 항목은 남긴다 — 누락 검사용).
예전 형식처럼 `id` 대신 `url` 로 적은 항목도 검증은 받는다.
`none` 이슈는 적지 않고 개수만 `none_count` 에 둔다. `issue_trace_stats.relations.none` 은 이 값을 더한 것이다.

```jsonc
"issue_trace": [
  {
    "id": "m1",
    "issues": [
      { "id": "i1", "issue": "3분기 영업이익 예상치 하회", "relation": "direct" }
      // relation: direct | sector | market
    ],
    "none_count": 2
  }
]
```

어느 칸에도 쓰지 않은 이슈는 `issue_trace` 에만 남는다(경고 아님). 쓰인 이슈 수는 `issue_trace_stats.issues_used`.

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
| `skipped_llm` | 정형 보고서일 때만 `"NO_DIRECT_MESSAGES"` (직접 언급·테마 동향 0건). 그 밖에는 칸이 없다 |
| `issue_trace` | 모델이 낸 이슈 목록 |
| `move_case` / `judge_layers` / `common_move` | 러너가 계산한 값(`market` 이 null 이면 null). `move_case` 는 모델에 보내지 않는다 |

### 검증 결과

| 키 | 뜻 |
| --- | --- |
| `verify_status` | `passed` / `failed`. 스키마·규칙·근거 중 하나라도 걸리면 failed |
| `verify_problems` | `"<코드>: <상세>"` 문자열 배열 (예: `QUOTE_NOT_IN_SOURCE: factors[0].sources[0] ...`) |
| `events_status` / `events_problems` | `events` 칸 검사. `passed` / `failed` / `missing`. 판정과 별개. 형식(`SCHEMA_*`, `EVENT_REASON_MISMATCH`)과 실제 칸 대조: `EVENT_BACKGROUND_REF_MISSING`·`_REF_DUPLICATE`·`_UNREFERENCED`(background 항목과 사건이 하나씩 짝), `EVENT_FACTOR_COUNT`·`_REF_MISSING`·`_DUPLICATE`, `ISSUE_ID_DUPLICATE` |
| `verify_warnings` | 실패는 아니지만 볼 것. `DUPLICATE_SOURCES`, `MAIN_CAUSE_STALE`, `COUNT_OVER_CAP`(background 6·칸당 3, watch 3·칸당 1, factors 4, terms 8), `FACTOR_RESULT_SOURCES_ONLY`(출처가 모두 입력 kind `flow_rank`·`market_recap`), `THEME_RECAP_NOT_SECTOR`(theme_recap 출처인데 그 메시지에서 묶인 이슈에 sector 가 없음), `QUOTE_MISSING_SUBJECT`(첫 quote 에 event 의 매매 주체·영문 고유명이 없음, 이 종목명·직함 CEO·CFO·CTO·COO 제외), `COMMON_MOVE_WITH_MOVE_LINK`(common_move 날 등락 층 link 가 있음), `MOVE_COMPARISON_ON_FLAT`(judge_layers.relative 가 false 인 날 summary.move 에 "더/덜" 비교), `DIRECT_SOURCE_MISSING`(factor 로 묶인 이슈가 direct 메시지에서 나왔는데 출처에 direct 가 없음), `MAIN_CAUSE_TOO_LONG`(최종 main_cause 가 러너 고정 문장 포함 3문장 초과. 자르지 않음), `STRENGTH_MISMATCH`(모델 strength 가 정의와 어긋남 — 사건 이슈가 direct(입력 match) 메시지에서 나왔는데 partial, 아닌데 sufficient. issue_trace 가 없으면 출처로 봄. 미확인·대형주 몫 상한은 예외) |
| `issue_trace_warnings` / `issue_trace_stats` | `ISSUE_TRACE_MISSING_URL`(messages 칸 누락)·`ISSUE_ID_UNKNOWN` 경고와 집계(`messages_traced`, `messages_total`, `relations`, `issues_used`) |

### 재시도·고쳐 쓰기 기록

| 키 | 뜻 |
| --- | --- |
| `json_retry` | `{"retried": false}` 또는 `{"retried": true, "first": {json_status, asked_question, raw_text, usage, cost, duration_ms}}`. 정상 종료인데 JSON 이 깨졌을 때만 1회 재호출 |
| `judge_retry` | `{"retried": false}` 또는 `{"retried": true, "first": {problems, final_text, json_retry, usage, cost, duration_ms}}`. 열린 보고서가 `judge_layers` 가 false 인 층에 link·판정을 달았을 때(`FLAT_*`) 같은 입력으로 1회 재호출. 비용은 `cost` 에 합친다 |
| `timeouts` | 시간 제한(`SUMMARY_TIMEOUT_SEC`, 기본 420초)에 걸린 시도마다 `{error, seconds}`. 스트림 끊김과 합쳐 1회 재시도하고, 다시 걸리면 `LLM_ERROR` |
| `stream_interruptions` | 끊긴 시도마다 `{partial_chars, error}`. 끊김은 1회 재전송 |
| `quote_repair` | quote 가 원문에 없던 factor·background 항목마다 `{kind, result: fixed\|dropped, failed, retry_failed, quotes, rejected, ...}`. repair 는 quote(sources)만 고친다. 다시 쓴 event(background 는 text)가 원래와 한 글자라도 다르면 `rejected: "event_changed"` 로 받지 않고 뺀다. 다시 써도 없으면 항목을 빼고 그 항목을 가리키던 `events` 사건을 `dropped`/`quote_verify_fail` 로 바꾼다(뒤 항목의 순번은 당긴다) |
| `main_cause_rewrite` | 뺀 factor 에 `move` link 가 있었을 때 `{result: rewritten\|failed, dropped, before, after, cost, error}` |

### 러너가 정하는 칸 (`finalize`)

quote 고쳐 쓰기 뒤, 검증 앞에서 러너가 다시 정한다. 정형 보고서(`skipped_llm`)는 하지 않는다. 검증·`final_text` 는 고친 값이다.

| 키 | 뜻 |
| --- | --- |
| `strength_recomputed` | link 마다 `{factor, layer, model, final, basis}`. 그 factor 사건의 이슈(`events.issue_ids` → `issue_trace`)가 하나라도 입력 match=direct 메시지에서 나왔으면 `sufficient`, 아니면 `partial`(`basis: "issues"`, DIRECT_SOURCE_MISSING 과 같은 판단 `verify.factor_has_direct`). issue_trace 가 없거나 사건에 issue_ids 가 없으면 출처로 본다(`basis: "sources"`). `unconfirmed: true` 와 `move_strength_cap` 이 partial 인 날 등락 층은 `partial`. `insufficient`·`direction_match: false` link 는 그대로 둔다. 경고 `STRENGTH_MISMATCH` 는 `model` 값을 같은 정의로 본다 |
| `verdict_recomputed` | `[{key: verdict\|relative_verdict, model, final}]`. `judge_layers` 가 false 인 층은 `no_clear_cause`, 판단하는 층은 그 층 link 에 `sufficient` 가 있으면 `explained`, link 가 있으면 `partially_explained`, 없으면 `no_clear_cause` |
| `main_cause_fixed` | `common_move`·`market_led` 날 `{before, after}`, 그 밖 null. 앞에 "대형주 전반이 함께 오른(내린) 날이었습니다.", `common_move` 날은 끝에 "이 종목만의 원인은 따로 확인되지 않았습니다." 를 붙인다. 모델이 같은 문장을 썼으면 지우고 한 번만 붙인다 |

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
  "warning_counts": { "issue_trace_warnings": 3, "events_problems": 1, "verify_warnings": 4 },  // 경고 건수 합
  "retried": { "json_retry": 0, "judge_retry": 1 },  // LLM 을 다시 부른 회차 수
  "skipped_llm": 1,                                  // 정형 보고서 회차 수
  "issue_trace_messages": { "traced": 30, "total": 31 },
  "loaded": null                                     // --load 면 적재 건수
}
```

보고서마다 찍는 줄 끝에 `issue_trace_warnings=… events_problems=… verify_warnings=…` 건수가 붙는다.

종료 코드: 호출 자체가 실패한 건(`errors`)이 있으면 1. 검증 실패는 데이터라 0.

---

## 알아둘 것

- **DB 적재는 아직 옛 형식 기준이다.** `stock_move_analyses` 에는 `relative_verdict`, `summary.relative`,
  `links` 를 담는 칼럼이 없다. 새 칸은 `raw_json` 에만 들어간다. 백엔드가 두 층을 화면에 내려면 적재 쪽 스키마 정리가 먼저 필요하다.
- 보고서 JSON 키는 **snake_case** 다. 루트 CLAUDE.md 의 camelCase 규약은 백엔드 응답 직렬화에서 맞춘다.
- `as_of` 는 `"HH:MM"` 문자열이다. 적재 시 `target_date` 와 합쳐 KST aware datetime 으로 저장한다.
- `not_found`, `events`, `sources[].match`, `sources[].is_market_recap` 은 검수용이라 화면에 내지 않는다.
