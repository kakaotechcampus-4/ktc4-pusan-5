# 분류 DB 설계 초안

- 작성일: 2026-10-09 (같은 날 리뷰 반영해 1차 수정 — 12절)
- 상태: **초안.** 아직 구현하지 않았다. 산업 세분화의 검증은 [INDUSTRY_REVIEW.md](INDUSTRY_REVIEW.md) 로 받는다.
- 구현할 브랜치: `feature/data-classification` (`feature/data-collection` 병합 뒤 develop 에서 생성)
- 근거: 아래 0절의 전제(팀 결정과 멘토 피드백을 옮겨 적은 것), [DB_SCHEMA.md](DB_SCHEMA.md)(이미 있는 표)
- 범위: 자료를 종목·산업·시장으로 분류해 저장하는 표와, 종목별 후보 자료를 조회하는 규칙

---

## 0. 이 설계의 전제

설계보다 먼저 정해진 것들이다. 본문에서는 `(전제 P1)` 처럼 가리킨다.

| # | 전제 | 출처 |
| --- | --- | --- |
| P1 | 기업용·산업용 LLM 을 따로 두지 않고 **문장 추출 → scope(company / industry / macro) + 대상 분류 → 종목별 조립** 순서로 처리한다. 산업 문장은 산업 문장으로 보존하고, 어느 종목에 붙일지는 DB 의 회사–산업 관계로 정한다. 그러면 LLM 이 기사에 없는 관계를 지어내는 일이 줄어든다 | 멘토 피드백 |
| P2 | LLM 은 사건마다 **근거 문장 번호, 역할(원인·등락·전망 …), 시점(일어남·전망), 기사 속 대상 표기**를 낸다. 앞 문장이 있어야 뜻이 통하면 그 번호도 따로 낸다. 문장을 옮겨 쓰지 않고 번호만 낸다(지어낼 수 없는 구조) | 팀 결정 |
| P3 | LLM 은 **기사마다 한 번** 불러 사건 목록을 뽑고, 종목별 조립은 코드가 한다. 추출 단계는 원인 후보를 넓게 남기고, 좁히는 건 조립·생성 단계에서 한다 | 팀 결정 |
| P4 | **기업 연결은 LLM 이 아니라 데이터가 한다.** 표기 → 종목코드는 별칭 JSON, 산업 → 기업은 DB. 산업 연결로 가져온 사건은 "배경 후보" 로 표시하고 원인으로 확정하지 않는다 | 팀 결정 |
| P5 | "정말 주가를 움직였나" 는 시세가 있는 생성 단계에서 판단한다. 분류는 원인 후보까지만 만든다 | 팀 결정 |
| P6 | 종목 기준 JSON 은 종목코드·공식명·별칭·산업을 구분해 담는다. "삼성" 처럼 여러 회사를 가리킬 수 있는 표기는 문맥 없이 특정 회사로 확정하지 않는다. 산업 표현을 기업 별칭에 넣지 않는다 | 팀 결정 |
| P7 | 분류 결과는 원문과 분리해 저장하고 원문을 덮어쓰지 않는다. 모델·프롬프트·기준 버전, 분류 시각과 처리 상태를 남긴다. 재분류해도 이전 결과를 보존하고 조회에 쓸 회차를 고른다. 실패와 미분류를 구분한다 | 팀 결정 |
| P8 | 보관 정책으로 원문을 지울 때는 발췌·분류 근거 같은 **사본도 삭제 범위에 넣어** 검토한다. 원문이 지워진 뒤에는 원문을 다시 확인한 것처럼 처리하지 않는다 | 팀 결정 |
| P9 | 다시 만들 수 없는 분류 결과를 저장하기 시작하면 마이그레이션 downgrade 를 막는다 | 팀 결정 |
| P10 | 사건 형식은 실험으로 확정한다. E2(역할을 나눈 출력)로 원인 재현율이 오르는지 보고, E3(기사 단위 사건 추출 → 종목별 조립)이 기존 종목별 문장 선택만큼 기업 직접 원인을 잡으면서 업황 배경 후보를 더 얻으면 채택한다. 역할 목록의 최종안과 증권사 의견(`analyst_view`)을 원인으로 볼지는 아직 정하지 않았다 | 팀 결정 |

---

## 1. 한 줄 요약

**LLM 은 문장이 어느 레벨(종목·산업·거시·시장) 이야기인지와 기사 속 표기만 정한다. 그 문장을 어느 종목에 붙일지는 DB 가 정한다.**

멘토 피드백(전제 P1)을 표 구조로 옮긴 것이다.

```
문장 추출 → scope(company / industry / macro / market) + entity 분류 → 종목별 조립
```

산업 문장은 산업 문장으로 저장한다. 어느 종목에 붙일지는 조회할 때 `stock_industries`(회사–산업 관계)로 정한다.
그래서 기사가 말하지 않은 회사 연결을 LLM 이 만들어 저장하는 일이 없다.

## 2. 이번에 정한 것

| 항목 | 결정 |
| --- | --- |
| scope 값 | `company` · `industry` · `macro` · `market` 4개 (전제 P1 의 3개에 시황 `market` 을 더함) |
| 거시·시장 문장 | 모든 종목에 똑같이 배경으로 붙인다. 주제별로 특정 산업에만 붙이는 표는 두지 않는다 |
| 종목 하나가 여러 산업 | 허용한다 (예: 삼성전자 = 메모리반도체 + 가전 + …) |
| 산업 목록 형태 | 계층. 맨 위는 KRX 업종(BE 화면 섹터와 같은 값), 아래는 뉴스 연결용 세부 산업 |
| 화면 섹터와 뉴스용 산업 | 달라도 된다 (예: SK스퀘어 화면 섹터 = 금융, 뉴스 연결 = 지주회사 + 메모리반도체) |
| 관련성(direct/indirect) | 따로 저장하지 않는다. 조회할 때 **어느 경로로 찾았는지**가 곧 관련성이다 (5절) |
| 거시·시장 주제 표(`market_topics`) | 만들지 않는다. 조립에 쓰이지 않는다. 기사 속 표기는 사건의 `mentions` 에 남는다 |

---

## 3. 전체 구조

### 3-1. 표 개수

데이터 파이프라인과 관련된 표만 센다(BE 의 시세·재무·사용자 표 제외).

| 상태 | 개수 | 표 |
| --- | --- | --- |
| develop 에 이미 있음 | 9 | `news`, `analyst_reports`, `source_card`, `stock_move_analyses` 외 3개, 참조용 `channel`·`stock`(BE) |
| `feature/data-collection` 에서 만듦 | 4 | `telegram_messages`, `telegram_message_links`, `source_card_stocks`, `dart_disclosures`(0025, 작업 중) |
| **이 설계로 만들 것** | **5** | 기준표 2개 + 결과표 3개 (아래) |

### 3-2. 단계

```
① 원문 (5개) ──▶ ② 공통 번호 (2개) ──▶ ③ 분류 (5개, 이 문서) ──▶ ④ 보고서 (4개)
```

### 3-3. 분류 표 5개

**기준표 2개 — 사람이 만든다. 작고 거의 안 바뀐다.**

| 표 | 한 행 | 대략 행 수 |
| --- | --- | --- |
| `industries` | 산업 하나 (계층) | 20여 개 |
| `stock_industries` | (종목, 산업) 연결 하나 | 30여 개 |

**결과표 3개 — LLM 이 쌓는다. 기사가 들어올 때마다 는다.**

| 표 | 한 행 | 위 표와의 관계 |
| --- | --- | --- |
| `classification_runs` | 자료 1건을 1번 분류한 기록 | 자료 1 → 회차 N (재분류) |
| `classification_events` | 그 회차의 사건 하나 | 회차 1 → 사건 N |
| `classification_event_entities` | 사건의 표기 하나를 종목·산업으로 바꾼 결과 | 사건 1 → 대상 N |

"하나에 여러 개" 가 세 번 겹쳐서 결과표가 3단이다. 한 표로 합치면 칸 수를 미리 정할 수 없어 빈칸이 생긴다.

```
source_card.id
   ↑ classification_runs.source_card_id          (지워지지 않게 막음)
classification_runs.id
   ↑ classification_events.run_id                (CASCADE)
classification_events.id
   ↑ classification_event_entities.event_id      (CASCADE)
     classification_event_entities.industry_code → industries.code
                                stock_industries.industry_code → industries.code
```

기존 `source_card_stocks` 는 칼럼을 바꾸지 않고 `tagged_by = 'classification'` 행만 더한다(4-6).

표 소유는 모두 ai(`alembic_version_ai`)다. ai `alembic/env.py` 의 `MANAGED_TABLES` 에 더한다.

---

## 4. 표별 칼럼

표기: 타입은 PostgreSQL 기준, `NN` = NOT NULL. 기존 표의 관례를 따른다.
(ID 는 bigint, 종목코드는 BE `stock.code` 와 같은 varchar(6), 해시는 varchar(64), 시각은 timestamptz)

### 4-1. `industries` — 산업 목록

| 칼럼 | 타입 | NULL | 설명 |
| --- | --- | --- | --- |
| `code` | varchar(32) | NN, PK | 산업 식별자 (예: `memory`). **한 번 정하면 바꾸지 않는다** — 분류 결과가 이 값을 FK 로 가리킨다 |
| `name` | varchar(100) | NN | 표시 이름. 맨 위 산업은 BE `sector` 값과 글자까지 같다 (예: `전기전자`) |
| `parent_code` | varchar(32) | NULL | FK → `industries.code`. NULL 이면 맨 위(KRX 업종) |
| `aliases` | jsonb | NN, 기본 `[]` | 기사에서 이 산업을 가리키는 표기 문자열 목록 (예: `["D램", "낸드", "HBM"]`) |
| `retired_at` | timestamptz | NULL | 기준에서 빠진 시각. 빠진 산업도 지우지 않는다(과거 분류 결과가 가리키므로) |
| `basis_version` | varchar(64) | NN | 마지막으로 이 행을 넣은 기준 JSON 의 버전(7절) |
| `created_at` | timestamptz | NN, 기본 `now()` | |

- 제약: `CHECK(parent_code IS NULL OR parent_code <> code)`, `CHECK(jsonb_typeof(aliases) = 'array')`
- 계층이 고리를 이루지 않는지, 맨 위 이름이 BE `sector` 값과 같은지는 기준 JSON 을 넣는 코드가 검사한다(CHECK 로는 못 한다).
- 작은 분류 하나는 큰 분류 하나에만 속한다(`parent_code` 하나).

### 4-2. `stock_industries` — 종목 ↔ 산업

| 칼럼 | 타입 | NULL | 설명 |
| --- | --- | --- | --- |
| `id` | bigint | NN | PK |
| `stock_code` | varchar(6) | NN | 종목코드. BE `stock` 을 FK 로 걸지 않는다(`source_card_stocks` 와 같은 관례: 마스터에 없어도 저장이 막히지 않게) |
| `industry_code` | varchar(32) | NN | FK → `industries.code` |
| `note` | text | NULL | 연결 이유가 사업 내용이 아닐 때 (예: "SK하이닉스 지분") |
| `basis_version` | varchar(64) | NN | 이 행을 넣은 기준 JSON 의 버전 |
| `created_at` | timestamptz | NN, 기본 `now()` | |

- 제약: `UNIQUE(stock_code, industry_code)`
- 인덱스: `(industry_code)` — 5절 산업 경로에서 "이 산업의 종목" 을 찾는다
- 종목은 **가장 작은 분류**에 연결한다. 상위 산업은 계층을 따라 올라가서 얻는다.
- 은퇴한 산업(`retired_at` 있음)에는 연결하지 않는다. 기준 JSON 을 넣는 코드가 검사한다.
- 이 표는 **지금 기준만** 담는다. 기준이 바뀌면 행을 통째로 바꾸고, 예전 기준은 버전별 JSON 파일로 남는다(7절).

### 4-3. `classification_runs` — 분류 회차

한 행 = 자료 하나를 한 번 분류한 기록. 다시 분류하면 새 행이 생기고 이전 회차는 남는다(전제 P7).

| 칼럼 | 타입 | NULL | 설명 |
| --- | --- | --- | --- |
| `id` | bigint | NN | PK |
| `source_card_id` | bigint | NN | FK → `source_card.id`. **CASCADE 아님** — 자료를 지우려 하면 막힌다. 돈 들여 만든 분류 기록이 조용히 사라지지 않게 |
| `status` | varchar(16) | NN, CHECK | `ok` \| `failed`(호출·응답 형식 실패) \| `no_body`(본문 없음·보관 정책으로 삭제) \| `skipped`(분류 대상 아님) |
| `model` | varchar(64) | NULL | 사용한 모델 |
| `prompt_sha256` | varchar(64) | NULL | 프롬프트 파일 해시 |
| `criteria_version` | varchar(32) | NULL | 분류 기준(라벨 기준) 버전 |
| `basis_version` | varchar(64) | NN | 표기 → 종목·산업 연결에 쓴 기준 JSON 의 버전(7절) |
| `splitter_version` | varchar(32) | NULL | 문장 분리 규칙 버전. 사건의 문장 번호는 이 규칙으로 나눈 번호다 |
| `input_sha256` | varchar(64) | NULL | 분류에 넣은 본문의 해시. 원문이 그때와 같은지 맞춰 본다 |
| `sentence_count` | integer | NULL | 나눈 문장 수. 사건의 번호가 범위 안인지 저장 전에 검사할 때 쓴다 |
| `raw_response` | text | NULL | 모델 응답 원문. 형식이 깨진 응답도 남긴다 |
| `error` | text | NULL | 실패 사유 |
| `usage` | jsonb | NN, 기본 `{}` | 토큰 수·비용 |
| `is_current` | boolean | NN, 기본 false | 조회에 쓰는 회차인지 |
| `classified_at` | timestamptz | NN, 기본 `now()` | |

- 제약
  - `CHECK(status IN ('ok','failed','no_body','skipped'))`
  - `CHECK(NOT is_current OR status = 'ok')` — 실패한 회차는 조회에 쓸 수 없다
  - `CHECK(status <> 'ok' OR (splitter_version IS NOT NULL AND input_sha256 IS NOT NULL AND sentence_count IS NOT NULL))` — 성공한 회차는 문장 번호를 다시 풀 수 있어야 한다
  - 부분 UNIQUE `(source_card_id) WHERE is_current` — 자료마다 지금 쓰는 회차는 하나
- 인덱스: `(source_card_id)`
- **현재 회차 교체와 `source_card_stocks` 갱신은 한 트랜잭션으로 한다(4-6).** 중간에 실패하면 이전 상태 그대로 남는다.
- 본문이 없으면 `no_body` 로 남기고 사건을 만들지 않는다. 네이버 요약(`news.summary`) 같은 다른 글로 대신 분류하지 않는다.

### 4-4. `classification_events` — 사건

전제 P2·P3 의 사건 항목을 칼럼으로 옮겼다.

| 칼럼 | 타입 | NULL | 설명 |
| --- | --- | --- | --- |
| `id` | bigint | NN | PK |
| `run_id` | bigint | NN | FK → `classification_runs.id` (ON DELETE CASCADE) |
| `order_index` | integer | NN | 사건 순서(1부터) |
| `scope` | varchar(16) | NN, CHECK | `company` \| `industry` \| `macro` \| `market` |
| `role` | varchar(16) | NN, CHECK | `cause` \| `price_move` \| `outlook` \| `context` \| `analyst_view` |
| `tense` | varchar(16) | NN, CHECK | `happened`(이미 일어남) \| `expected`(전망) |
| `sentence_indices` | integer[] | NN | 근거 문장 번호(1부터). 떨어진 문장도 담는다 (예: `{2,15}`) |
| `context_indices` | integer[] | NN, 기본 `{}` | 근거 문장을 읽으려면 함께 필요한 앞 문장 번호(전제 P2) |
| `mentions` | text[] | NN, 기본 `{}` | LLM 이 낸 기사 속 표기 그대로. 코드가 원문에 있는지 검사하고, 없는 표기는 빼고 저장한다 |
| `reason` | text | NULL | 판단 이유 |

- 제약
  - `UNIQUE(run_id, order_index)`
  - `scope`·`role`·`tense` 의 `IN (...)` CHECK
  - `CHECK(cardinality(sentence_indices) > 0 AND (0 < ALL(sentence_indices)) IS TRUE AND array_ndims(sentence_indices) = 1)` — 근거 문장이 하나 이상, 번호는 1 이상, 1차원
  - `CHECK((0 < ALL(context_indices)) IS TRUE AND coalesce(array_ndims(context_indices), 1) = 1)`
  - `CHECK(('' <> ALL(mentions)) IS TRUE AND coalesce(array_ndims(mentions), 1) = 1)` — 빈 문자열·NULL 표기 금지
  - **`IS TRUE` 를 붙이는 이유:** 배열 칼럼의 `NOT NULL` 은 배열 **안의** NULL 을 막지 않는다. `{2,NULL}` 이면 `0 < ALL(...)` 의 결과가 거짓이 아니라 NULL 이고, CHECK 는 NULL 을 통과시킨다. `IS TRUE` 는 NULL 을 거짓으로 바꾼다. 빈 배열은 `ALL` 의 결과가 참이라 그대로 통과한다.
  - `coalesce(array_ndims(...), 1) = 1` — PostgreSQL 의 `integer[]` 는 `{{1,2},{3,4}}` 같은 2차원 배열도 받는다. 빈 배열은 차원이 NULL 이라 1 로 본다.
  - 번호가 `sentence_count` 이하인지, 번호가 겹치지 않는지는 CHECK 로 못 한다(다른 표의 값·부분 질의). 저장하는 코드가 정렬·중복 제거·범위 검사를 한다.
- 인덱스: `(run_id)` — PostgreSQL 은 FK 에 인덱스를 자동으로 만들지 않는다. 조인과 CASCADE 삭제에 필요하다.
- **근거 위치:** 원문은 한 번 확보하면 바뀌지 않으므로 "회차의 `splitter_version` 으로 원문을 나눈 뒤 이 번호의 문장" 이 곧 근거 위치다. 글자 위치 칼럼은 두지 않는다. 원문이 바뀌었는지는 `input_sha256` 으로 확인한다.
- **근거 구절 원문을 복사해 두지 않는다.** 복사하면 보관 정책으로 원문을 지워도 사본이 남는다(전제 P8). 원문이 지워진 뒤에는 "원문 없음" 으로 표시한다.

### 4-5. `classification_event_entities` — 표기 → 종목·산업

한 행 = 사건의 표기 하나를 종목 또는 산업 하나로 바꾼 결과.

| 칼럼 | 타입 | NULL | 설명 |
| --- | --- | --- | --- |
| `id` | bigint | NN | PK |
| `event_id` | bigint | NN | FK → `classification_events.id` (ON DELETE CASCADE) |
| `stock_code` | varchar(6) | NULL | 종목이면 채운다 |
| `industry_code` | varchar(32) | NULL | FK → `industries.code`. 산업이면 채운다 |
| `mention` | text | NN | 이 연결의 근거가 된 표기. 사건의 `mentions` 중 하나 |
| `linked_by` | varchar(16) | NN, CHECK | `alias`(별칭 사전). 나중에 `manual`(사람)·`llm_code`(LLM 이 코드 목록에서 고름)를 더할 수 있다 |

- 제약
  - `CHECK(num_nonnulls(stock_code, industry_code) = 1)` — 종목이든 산업이든 하나만. `telegram_message_links` 의 `ck_telegram_message_link_target` 과 같은 방식
  - `UNIQUE(event_id, stock_code, mention)`, `UNIQUE(event_id, industry_code, mention)` — 같은 표기로 같은 대상을 두 번 넣지 않는다. 표기가 다르면 같은 대상이라도 행이 따로 생긴다(예: 한 사건에 "삼성전자" 와 "Samsung Electronics" → 같은 종목 2행). 그래야 사건의 `mentions` 와 비교할 때 연결된 표기를 미연결로 잘못 보지 않는다. NULL 끼리는 겹치지 않으므로 두 제약이 서로 막지 않는다
  - `CHECK(mention <> '')`
  - `CHECK(linked_by IN ('alias'))`
- 인덱스: `(event_id)`, `(stock_code)`, `(industry_code)`
- 같은 사건이 한 종목에 여러 행으로 걸릴 수 있으므로, 조회(5절)와 `source_card_stocks` 갱신(4-6)은 (사건, 종목) 또는 (자료, 종목)으로 중복을 없앤다.
- 어느 별칭에도 안 걸린 표기(예: "삼성")는 이 표에 행이 없다. 사건의 `mentions` 와 비교하면 찾을 수 있고, 사람이 보고 별칭을 더한 뒤 재분류한다.
- 거시·시장 사건은 대개 이 표에 행이 없다. 모든 종목에 붙으므로 대상이 필요 없다.

### 4-6. `source_card_stocks` — 기존 표, 칼럼 변경 없음

- 현재 회차의 종목 대상(`stock_code` 있는 행)을 `tagged_by = 'classification'` 으로 넣는다. 사건의 scope 는 따지지 않는다.
- 이미 `report_item_code` 로 연결된 (자료, 종목)은 고유 제약 때문에 넣지 않고 건너뛴다(그 연결은 이미 있다).
- 현재 회차가 바뀌면 그 자료의 `classification` 행만 지우고 다시 넣는다. `report_item_code` 행은 건드리지 않는다. 4-3 의 회차 교체와 같은 트랜잭션.
- 이 표는 종목에 **직접** 연결된 자료만 담는다. 산업·거시·시장 자료는 여기 없다(5절).

---

## 5. 종목별 조립 규칙 (조회, 표 없음)

입력: 종목 X, 기준 시각 T, 조회 기간.
**세 갈래로 따로 찾아서 합친다.** 기존 `stock_card_ids()` 는 `source_card_stocks` 만 보므로 회사 직접 자료만 나온다. 그것만 출발점으로 삼으면 회사 이름이 없는 산업·거시·시장 자료가 빠진다.

| 경로 | 찾는 조건 | 의미 |
| --- | --- | --- |
| `company` | 현재 회차 사건의 대상에 `stock_code = X` (scope 무관) | 기사가 X 를 직접 말함 |
| `industry` | `scope = 'industry'` 이고, 대상 산업이 X 의 산업 **자신이거나 그 상위** | X 가 속한 산업 이야기. 배경 후보 |
| `macro` | `scope = 'macro'` | 모든 종목 공통 배경 |
| `market` | `scope = 'market'` | 모든 종목 공통 배경 |

- 세 갈래 모두 시각 조건은 `stock_card_ids()` 와 같은 규칙을 쓴다: `source_card.available_at <= T`(기준 시각과 같은 시각의 자료는 포함), 공개 시각을 모르면 `event_date` 가 T 의 날짜(KST)보다 앞선 날. 이 조건 부분을 함수로 떼어 세 갈래가 같이 쓴다.
- 현재 회차(`is_current`)의 사건만 본다. 분류하지 않은 자료, 실패만 있는 자료는 "미분류" 로 따로 센다.
- 한 사건이 여러 경로에 걸리면 위쪽 경로 하나로 낸다(`company` > `industry` > `macro`·`market`).
- `industry` 경로는 `scope = 'industry'` 인 사건만 탄다. "삼성전자, 메모리 가격 상승에 실적 개선" 처럼 회사 사건에 산업 표기가 섞였다고 다른 메모리 회사에 퍼지지 않게 한다.
- 상위 산업 매칭: X 의 산업과 그 조상 산업 목록을 먼저 구한다(산업 표가 수십 행이라 코드에서 계산하거나 `WITH RECURSIVE` 한 번). "반도체 업황" 기사(`semiconductor`)는 그 아래 `memory`·`foundry` 종목에 모두 붙고, "D램" 기사(`memory`)는 메모리 종목에만 붙는다.
- `company` 외 경로로 온 사건은 원인으로 확정하지 않는다. "배경 후보" 로 표시해서 넘긴다(전제 P4).

반환 항목: 자료 ID, 경로, 사건(scope·role·tense·문장 번호), 분류 회차 ID, 출처, `available_at`, 본문 상태(`ok`/`purged` 등).

보고서 생성 입력과의 대응 (생성 담당과 맞출 것)

| 경로 | `stock_analysis_system.md` 의 칸 |
| --- | --- |
| `company` | `match: "direct"` |
| `industry` | `match: "indirect"` (업황·경쟁사·전방산업) |
| `market` | `is_market_recap: true` |
| `macro` | 정해지지 않음. 프롬프트에 대응하는 칸이 없다 → 11절 |

### 예시 (가상의 기사)

> ① D램 가격이 급등했다. ② 메모리 품귀로 TV 제조사 원가 부담이 커졌다. ③ LG전자 주가는 3% 내렸다. ④ 미국 금리 인하 기대에 코스피는 1% 올랐다.

저장되는 것 — 회차 1행, 사건 4행, 대상 3행

| 사건 | scope | role | sentence_indices | mentions | 대상 행 |
| --- | --- | --- | --- | --- | --- |
| ① | industry | cause | `{1}` | `{D램}` | `industry_code = memory` |
| ② | industry | cause | `{2}` | `{TV 제조사}` | `industry_code = home_appliance` |
| ③ | company | price_move | `{3}` | `{LG전자}` | `stock_code = 066570` |
| ④ | macro | cause | `{4}` | `{미국 금리, 코스피}` | 없음 |

조회할 때 조립되는 것

| 종목 | company | industry (배경) | macro·market (배경) |
| --- | --- | --- | --- |
| LG전자 | ③ | ② | ④ |
| SK하이닉스 | — | ① | ④ |
| 삼성전자 | — | ①, ② | ④ |

②를 LG전자에 붙인 것은 LLM 이 아니라 `stock_industries` 의 (LG전자, 가전) 행이다.

---

## 6. 표기 → 대상 연결 (전제 P4)

- LLM 은 사건마다 기사 속 표기(`mentions`)만 낸다. 코드가 원문에 그 표기가 있는지 검사한다.
- 표기 → 종목코드: 기준 JSON 의 종목 별칭. 표기 → 산업: `industries.aliases`.
- 어느 별칭에도 안 걸리면 대상 행을 만들지 않는다. 사람이 보고 별칭을 더한 뒤 재분류한다.

알려진 약점: 산업 표기는 "TV 제조사", "메모리 업체들" 처럼 형태가 다양해서 별칭으로 다 잡히지 않을 수 있다.
대안은 LLM 에게 산업 코드 목록을 주고 코드로 고르게 하는 것이다(`linked_by = 'llm_code'`) → 11절.

## 7. 기준 JSON 과 버전

- 종목·별칭·산업·종목–산업 연결을 담은 **기준 JSON 파일 하나**가 원본이다. DB 의 `industries`·`stock_industries` 는 이 파일에서 넣는다. 종목 별칭은 JSON 에만 둔다(전제 P6).
- 버전 = 파일 내용의 sha256. `basis_version` 칼럼(varchar(64))에 이 값을 적는다.
- **버전마다 파일을 새로 만들고, 만든 파일은 고치지 않는다.** 예: `ai/app/data/classification_basis/<날짜>.json`. 이 파일들이 예전 기준의 기록이다.
- DB 의 기준표에는 지금 기준만 있다. 예전 회차가 어떤 기준으로 연결됐는지는 회차의 `basis_version` 으로 해당 파일을 찾아 본다.
- 기준을 바꿨을 때 예전 회차의 대상 행(4-5)은 그대로 둔다. 새 기준으로 다시 연결하려면 재분류한다(새 회차).
- 조립(5절)은 항상 **지금 기준**의 `stock_industries` 를 쓴다. 이미 만든 보고서가 무엇을 썼는지는 보고서 쪽이 저장한다(생성 담당과 맞출 것).

## 8. 구현·마이그레이션 메모

- 다음 ai 리비전으로 한 번에 만든다. `0025` 는 `dart_disclosures` 가 쓰므로 그 뒤 번호다. 정확한 번호는 구현할 때 develop 기준으로 정한다.
- 기존 표의 칼럼은 바꾸지 않는다.
- `classification_runs` 에 행이 있으면 downgrade 를 막는다. 분류 결과는 다시 만들려면 LLM 비용이 들고, 원문이 지워졌으면 다시 만들 수 없다(전제 P9). 기준표는 JSON 에서 다시 넣으면 되므로 막지 않는다.
- 문장 분리 코드(`app/services/news_link/sentence.py`)에는 지금 버전 값이 없다. 분리 규칙을 **버전별 함수로 남긴다.**
  - 예: `SPLITTERS = {"v1": split_sentences_v1, "v2": split_sentences_v2}`, 새 분류는 최신 버전을 쓴다.
  - 예전 회차의 문장을 꺼낼 때는 회차의 `splitter_version` 으로 함수를 골라 부른다. 버전 값만 올리고 기존 함수를 고치면 예전 회차의 "15번 문장" 을 다시 찾을 수 없다.
  - **한 번 배포한 버전의 함수는 고치지 않는다.** 고쳐야 하면 새 버전을 만든다. 버전마다 고정 입력·기대 출력 테스트를 둬서 실수로 바뀌면 깨지게 한다.
  - `classification_runs` 에 그 버전의 회차가 남아 있는 동안은 함수를 지우지 않는다.
- `raw_response`·`reason` 에 원문 일부가 들어갈 수 있다. 보관 정책 삭제(`python -m app.collectors.sources purge`) 범위에 넣을지 정한다 → 11절.
- `dart_disclosures` 는 아직 `source_card` 에 연결되지 않았다. 공시를 분류 대상에 넣을지는 별도로 정한다.

---

## 9. 산업 목록 초안

맨 위는 KRX 업종(BE `feature/be-stock-sector` 의 `sector` 값). 반도체만 한 단계 더 둔다("반도체 업황" 기사가 흔해서).
검증 중인 내용이라 회사별 연결은 [INDUSTRY_REVIEW.md](INDUSTRY_REVIEW.md) 3절이 원본이다.

| code | name | parent_code |
| --- | --- | --- |
| `krx_electronics` | 전기전자 | — |
| `semiconductor` | 반도체 | `krx_electronics` |
| `memory` | 메모리반도체 | `semiconductor` |
| `foundry` | 파운드리 | `semiconductor` |
| `smartphone` | 스마트폰 | `krx_electronics` |
| `home_appliance` | 가전 | `krx_electronics` |
| `electronic_parts` | 전자부품 | `krx_electronics` |
| `battery` | 2차전지 | `krx_electronics` |
| `krx_transport_equip` | 운송장비·부품 | — |
| `auto` | 자동차 | `krx_transport_equip` |
| `shipbuilding` | 조선 | `krx_transport_equip` |
| `defense_aerospace` | 방산·항공우주 | `krx_transport_equip` |
| `krx_pharma` | 제약 | — |
| `biopharma` | 바이오의약품 | `krx_pharma` |
| `krx_finance` | 금융 | — |
| `bank` | 은행 | `krx_finance` |
| `holding` | 지주회사 | `krx_finance` |
| `krx_insurance` | 보험 | — |
| `life_insurance` | 생명보험 | `krx_insurance` |
| `krx_machinery` | 기계·장비 | — |
| `power_equipment` | 발전설비 | `krx_machinery` |
| `krx_construction` | 건설 | — |
| `construction` | 건설 | `krx_construction` |

---

## 10. 데이터 타입 점검 결과

| 대상 | 타입 | 판단 |
| --- | --- | --- |
| ID | bigint | 기존 표(`source_card`, `source_card_stocks` 등)와 같다 |
| 종목코드 | varchar(6) | BE `stock.code`, `source_card_stocks.stock_code` 와 같다 |
| 산업 코드 | varchar(32) 자연키 | 사람이 읽는 값이라 FK 로 걸어도 조회 결과를 바로 읽을 수 있다. 대신 코드를 바꾸지 않는다(은퇴는 `retired_at`) |
| 상태값 | varchar + CHECK | 기존 `news.body_status`, `telegram_messages.collected_via` 와 같다. 값 목록이 바뀌면 CHECK 를 고치는 작은 마이그레이션이 필요하다 |
| 해시·버전 | varchar(64) | 기존 `source_file_sha256`, `pdf_sha256` 과 같다 |
| 시각 | timestamptz | 모든 기존 표와 같다 |
| 문장 번호 목록 | integer[] | 정수 목록만 담으므로 jsonb 보다 명확하다. 1 이상·비어 있지 않음을 CHECK 로 건다. ai 코드에서 배열 타입은 처음 쓴다(SQLAlchemy `ARRAY(Integer)`) |
| 표기 목록 | text[] | 위와 같은 이유 |
| 별칭 목록 | jsonb | 기준 JSON 에서 그대로 옮기는 값이다. 배열인지 CHECK 로 건다 |
| 토큰·비용 | jsonb | 모델마다 항목이 달라 고정 칼럼으로 두지 않는다 |
| 모델 응답 원문 | text | 형식이 깨진 응답도 남겨야 하므로 jsonb 가 아니라 text |

---

## 11. 아직 정하지 않은 것

| # | 항목 | 선택지 | 초안의 권장 |
| --- | --- | --- | --- |
| 1 | 지금 쓰는 회차 정하는 법 | 사람이 고름 / 최신 성공 회차 자동 | 최신 `ok` 회차 자동, 사람이 바꿀 수 있게 |
| 2 | 산업 표기 연결 방법 | 별칭 사전 / LLM 이 코드 목록에서 고름 | 별칭 사전으로 시작, 연결 안 된 표기 비율을 보고 판단 |
| 3 | 자회사 지분으로 산업 연결 | 허용 범위 | INDUSTRY_REVIEW 4절에서 의견 받음 |
| 4 | 20개 종목에 우선주 포함 | 삼성전자우 유지 / LG전자로 교체 | INDUSTRY_REVIEW 4절에서 의견 받음 |
| 5 | 바이오의약품 분리 | 하나 / 위탁생산·바이오시밀러 | INDUSTRY_REVIEW 4절에서 의견 받음 |
| 6 | `macro` 경로를 생성 입력에 넘기는 법 | `indirect` / 시황 / 새 칸 | 생성 담당과 결정 |
| 7 | `role` 최종안, `analyst_view` 를 원인으로 볼지 | 전제 P10 | 실험 E2 결과 보고 결정 |
| 8 | 전망(`outlook`) 사건을 후보로 넘길지 | 넘김 / 뺌 | 넘기되 role 로 구분 |
| 9 | `raw_response`·`reason` 을 보관 정책 삭제 범위에 넣을지 | 넣음 / 안 넣음 | 넣음(원문 일부가 섞일 수 있다) |
| 10 | 공시(`dart_disclosures`)를 분류 대상에 넣을지 | — | 공시를 `source_card` 에 연결할지 먼저 정한다 |
| 11 | 마이그레이션 시점 | 지금 / 실험 E3 채택 뒤 | E3 채택 뒤(전제 P10). 사건 형식이 바뀔 수 있다 |

---

## 12. 변경 이력

### 2026-10-09 1차 수정 — 외부 리뷰 반영

| 지적 | 반영 |
| --- | --- |
| 근거가 떨어진 문장(2번·15번)이면 `char_start`/`char_end` 한 쌍으로 표현 못 함 | 글자 위치 칼럼 삭제. `splitter_version` + 문장 번호 + `input_sha256` 으로 위치를 다시 구한다 |
| `sentence_count` 만으로는 분리 규칙이 바뀐 걸 알 수 없음 | `splitter_version` 추가 |
| 기준표를 고치면 예전 기준이 사라짐 | 버전별 기준 JSON 을 고치지 않고 보존(7절). 회차에 `basis_version` NN |
| 실패한 회차도 현재 회차로 지정 가능 | `CHECK(NOT is_current OR status = 'ok')`. 회차 교체와 색인 갱신을 한 트랜잭션으로 |
| `stock_card_ids()` 는 회사 직접 자료만 찾음 | 5절에 세 갈래 조회와 시각 조건 공유를 명시 |
| 번호 목록은 integer[] 가 명확 | integer[] 로 변경, 범위 CHECK 추가 |
| `is_krx_sector` 는 `parent_code IS NULL` 과 중복 | 삭제 |
| `market_topics` 는 조립에 필수 아님 | 삭제. 표기는 사건의 `mentions` 에 남김 (6개 → 5개) |

### 2026-10-09 1차 수정 — 자체 점검

| 문제 | 반영 |
| --- | --- |
| FK 칼럼에 인덱스가 없음. PostgreSQL 은 FK 인덱스를 자동으로 만들지 않아 조인·CASCADE 삭제가 느려진다 | `classification_events(run_id)`, `classification_event_entities(event_id)`, `stock_industries(industry_code)` 인덱스 추가 |
| 산업을 기준에서 빼면 과거 분류 결과가 FK 로 가리키고 있어 지울 수 없음 | 지우지 않고 `industries.retired_at` 으로 표시 |
| 대상 표의 `entity_type` 은 어느 칸이 채워졌는지와 같은 정보 | `entity_type` 삭제, `num_nonnulls(...) = 1` CHECK. `unresolved` 행 대신 사건의 `mentions` 와 비교해서 찾는다 |
| 같은 사건에 같은 종목이 두 번 들어갈 수 있음 | `UNIQUE(event_id, stock_code)`, `UNIQUE(event_id, industry_code)` |
| 성공한 회차인데 문장 번호를 다시 풀 정보가 비어 있을 수 있음 | `status = 'ok'` 이면 `splitter_version`·`input_sha256`·`sentence_count` 필수 CHECK |
| 본문이 없을 때 요약으로 대신 분류할 여지 | 4-3 에 "다른 글로 대신 분류하지 않는다" 명시 |

### 2026-10-09 2차 수정 — 외부 리뷰 반영

| 지적 | 반영 |
| --- | --- |
| 한 사건에 같은 종목의 별칭이 둘 나오면(`삼성전자`·`Samsung Electronics`) 고유 제약 때문에 하나를 버려야 하고, 버린 표기가 미연결로 보임 | 고유 제약에 `mention` 포함. 조회·색인 갱신에서 중복 제거 (4-5) |
| 배열 안의 NULL(`{2,NULL}`)은 CHECK 를 통과함 | 배열 CHECK 에 `IS TRUE` (4-4) |
| 버전 값만으로는 예전 문장 번호를 재현할 수 없음 | 버전별 분리 함수 보존, 배포한 버전은 고치지 않음 (8절) |
| 문서는 `available_at < T`, 코드는 `<= T` | 코드에 맞춰 `<= T` (5절) |

같은 수정 중 자체 점검으로 더한 것: `mentions`(text[])에도 NULL·빈 문자열 금지 CHECK, 세 배열 모두 1차원 CHECK, 대상 표 `mention <> ''`.

### 2026-10-09 PostgreSQL 실행 확인

일회용 PostgreSQL 17.11 컨테이너(CI 와 같은 주 버전)에 4절의 표 5개를 그대로 만들고 확인했다. 확인 뒤 컨테이너는 지웠다.

- **제약 시험 33개 모두 의도대로 동작.** 막아야 할 23개는 모두 거부되고, 허용해야 할 10개는 모두 저장됐다.
  - 거부된 것: 배열 안 NULL·0번·빈 배열·2차원 배열, 표기 NULL·빈 문자열, 허용 밖 scope·status, 같은 표기 중복, 종목·산업 둘 다 채움·둘 다 비움, 실패 회차를 현재로, 자료당 현재 회차 2개, `ok` 인데 분리 버전 없음, 회차 있는 자료 삭제, 분류 결과가 가리키는 산업 삭제, 자기 자신을 상위로 둔 산업, 없는 산업 코드 FK
  - 저장된 것: 떨어진 문장 `{2,15}`, 문맥 빈 배열, 같은 종목·다른 표기 2행, 종목 1행 + 산업 1행, 현재 아닌 두 번째 회차, 한 트랜잭션 안의 현재 회차 교체, 분리 버전 없는 `failed` 회차, 한 종목에 산업 여러 개, 회차 삭제 시 사건·대상 CASCADE
- **`IS TRUE` 가 필요한 것도 확인.** `0 < ALL('{2,NULL}')` 의 결과는 NULL(CHECK 통과), `IS TRUE` 를 붙이면 false(거부).
- **5절 조립 규칙을 예시 기사 + "반도체 업황" 문장(⑤)으로 실행한 결과가 문서와 같다.**

  | 종목 | company | industry | 거시·시장 |
  | --- | --- | --- | --- |
  | LG전자 | ③ | ② | ④ |
  | SK하이닉스 | — | ①, ⑤ | ④ |
  | 삼성전자 | — | ①, ②, ⑤ | ④ |
  | SK스퀘어 | — | ①, ⑤ | ④ |
  | 현대차 | — | — | ④ |

  ⑤(`semiconductor`)는 상위 산업 매칭으로 메모리 종목에 붙고, 가전만 있는 LG전자에는 붙지 않았다.

남은 범위: Alembic 마이그레이션·SQLAlchemy 모델로 옮긴 뒤의 확인(upgrade/downgrade, `alembic check`)은 구현 브랜치에서 한다. 시험에 쓴 `source_card` 는 FK 대상 확인용 최소 표였다.
