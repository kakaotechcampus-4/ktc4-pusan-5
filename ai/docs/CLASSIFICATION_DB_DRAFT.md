# 분류 DB 설계 초안

- 작성일: 2026-10-09 (같은 날 리뷰 반영해 1차 수정 — 12절)
- 수정일: 2026-10-27 — 멘토링(기업 관계·산업 적용 판정)과 생성 쪽 입력(PR #36, 10-27 develop 병합) 반영. 관련성 판정 표·기업 관계 표 추가 (12절)
- 수정일: 2026-10-28 — 산업 분류 외부 검토 반영. 회사–산업 연결에 연결 경로·경유 회사·사업 단계·역할·근거 칼럼 추가(4-2), 판정에 `direct_allowed` 추가(4-8), 산업 목록 교체(9절). 기준은 [INDUSTRY_REVIEW.md](INDUSTRY_REVIEW.md) 2-2 ~ 2-5 (12절)
- 수정일: 2026-10-28 (2차) — 외부 기업(30종목 밖)을 관계의 출발점으로 쓰도록 `external_companies` 추가(4-9), `company_relations` 양 끝을 종목·외부 기업으로 넓히고 근거 칼럼 추가(4-7), 외부 기업·기업 관계의 넣는 기준과 시작 목록은 [RELATION_REVIEW.md](RELATION_REVIEW.md) 로 따로 둠
- 수정일: 2026-10-28 (3차) — 기업 관계 외부 검토 반영. `company_relations` 를 제품·계약 범위별 행으로(`product_scope` 를 고유 키에), 단계(`stage`)·실제 당사자(`from_/to_via_company`)·적용 기간 추가(4-7). 자회사 표기를 남기는 `via_subsidiary`(4-5), 판정에 넘긴 관계 전부를 담는 `relation_refs`(4-8). 자회사 표기 출발점의 관계 확장 범위(5-1). 종목코드에 영문 대문자 허용(4-9)
- 수정일: 2026-10-28 (4차) — 기업 관계 56개 행 전체 대조 검토 반영. `relation_refs` 를 대표 경로와 상관없이 보존(4-8, 5-1). 자회사 표기 출발점의 범위 제한에서 `ownership` 제외(5-1). 실제 당사자(`from_/to_via_company`)를 별칭 자격과 분리해 합작법인도 기록(4-7). `stage` 를 "확인된 수준" 으로 재정의, `ownership` 범위 "지분" 고정(4-7)
- 수정일: 2026-10-30 — 구현. 10-29 멘토링 방향대로 `company_relations` 를 (from, to, 종류, 산업) 한 행으로 줄이고 제품 범위·단계·근거 수준·실제 당사자·기간을 `note` 로(4-7). `tense` 값을 `past`·`future` 로(4-4). 단계별 모델은 회차 `usage` 에(4-3). 자세한 것은 12절
- 수정일: 2026-11-02 — 지금 쓰는 기준 JSON 을 `draft2` 로 적고, 전제 P3 을 구현(자료당 LLM 최대 세 번)에 맞췄다. 첫 실행에서 나온 개선 과제는 [CLASSIFICATION_TUNING.md](CLASSIFICATION_TUNING.md)
- 상태: **구현 중.** 표 8개는 ai 리비전 `0027_classification`, 모델은 `app/models/classification.py`, 처리는 `app/services/classification/`, 저장·조회는 `app/repositories/classification.py`. 기준 JSON 은 아직 사실 확인 전 초안이다. 첫 버전은 `app/data/classification_basis/2026-10-30-draft.json`, 지금 쓰는 버전은 외부 검토 3차를 반영한 `2026-10-30-draft2.json` 이다. 산업 세분화의 검증은 [INDUSTRY_REVIEW.md](INDUSTRY_REVIEW.md), 기업 관계·외부 기업의 검증은 [RELATION_REVIEW.md](RELATION_REVIEW.md) 로 받는다.
- 구현 브랜치: `feature/data-classification` (10-21 까지의 추출 실험 브랜치에 develop 을 병합해 이어 씀)
- 근거: 아래 0절의 전제(팀 결정과 멘토 피드백을 옮겨 적은 것), [DB_SCHEMA.md](DB_SCHEMA.md)(이미 있는 표)
- 범위: 자료를 종목·산업·시장으로 분류하고, 사건이 각 종목에 해당하는지 판정해 저장하는 표와, 종목별 후보 자료를 조회하는 규칙
- 범위 밖: 사건이 주가를 움직였는지(인과) 판정, 생성 입력 JSON 구성(`kind` 등) — 보고서 생성 담당

---

## 0. 이 설계의 전제

설계보다 먼저 정해진 것들이다. 본문에서는 `(전제 P1)` 처럼 가리킨다.

| # | 전제 | 출처 |
| --- | --- | --- |
| P1 | 기업용·산업용 LLM 을 따로 두지 않고 **문장 추출 → scope(company / industry / macro) + 대상 분류 → 종목별 조립** 순서로 처리한다. 산업 문장은 산업 문장으로 보존하고, 어느 종목에 붙일지는 DB 의 회사–산업 관계로 정한다. 그러면 LLM 이 기사에 없는 관계를 지어내는 일이 줄어든다 | 멘토 피드백 (2026-10-27 P11 로 보완: DB 관계는 후보만 정하고, 붙일지는 사건마다 판정한다) |
| P2 | LLM 은 사건마다 **근거 문장 번호, 역할(원인·등락·전망 …), 시점(일어남·전망), 기사 속 대상 표기**를 낸다. 앞 문장이 있어야 뜻이 통하면 그 번호도 따로 낸다. 문장을 옮겨 쓰지 않고 번호만 낸다(지어낼 수 없는 구조) | 팀 결정 |
| P3 | **사건 추출 LLM 은 기사마다 한 번** 불러 사건 목록을 뽑고, 후보 모으기는 코드가 한다. 사전에 없는 표기가 있으면 코드 선택(②), 후보가 있으면 해당 여부 판정(④, P11)을 자료당 한 번씩 더 부른다. 그래서 자료 하나에 최대 세 번이고, 후보 수만큼 늘지는 않는다. 추출 단계는 원인 후보를 넓게 남기고, 좁히는 건 판정·생성 단계에서 한다 | 팀 결정 (2026-11-02 구현에 맞춰 수정) |
| P4 | **기업 후보는 LLM 이 아니라 데이터가 정한다.** 표기 → 종목코드는 별칭 JSON(사전에 없으면 ② LLM 이 목록 안에서 고른다), 산업 → 기업·기업 → 기업은 DB. ④ LLM 은 데이터가 정한 후보 안에서 "이 사건이 이 종목에 해당하는가" 만 판정하고, 후보 밖 종목을 낼 수 없다(P11). 산업·관계로 가져온 사건은 원인으로 확정하지 않는다 | 팀 결정 (2026-10-27 P11 에 맞춰 수정) |
| P5 | "정말 주가를 움직였나" 는 시세가 있는 생성 단계에서 판단한다. 분류는 원인 후보까지만 만든다 | 팀 결정 |
| P6 | 종목 기준 JSON 은 종목코드·공식명·별칭·산업을 구분해 담는다. "삼성" 처럼 여러 회사를 가리킬 수 있는 표기는 문맥 없이 특정 회사로 확정하지 않는다. 산업 표현을 기업 별칭에 넣지 않는다 | 팀 결정 |
| P7 | 분류 결과는 원문과 분리해 저장하고 원문을 덮어쓰지 않는다. 모델·프롬프트·기준 버전, 분류 시각과 처리 상태를 남긴다. 재분류해도 이전 결과를 보존하고 조회에 쓸 회차를 고른다. 실패와 미분류를 구분한다 | 팀 결정 |
| P8 | 보관 정책으로 원문을 지울 때는 발췌·분류 근거 같은 **사본도 삭제 범위에 넣어** 검토한다. 원문이 지워진 뒤에는 원문을 다시 확인한 것처럼 처리하지 않는다 | 팀 결정 |
| P9 | 다시 만들 수 없는 분류 결과를 저장하기 시작하면 마이그레이션 downgrade 를 막는다 | 팀 결정 |
| P10 | 사건 형식은 실험으로 확정한다. E2(역할을 나눈 출력)로 원인 재현율이 오르는지 보고, E3(기사 단위 사건 추출 → 종목별 조립)이 기존 종목별 문장 선택만큼 기업 직접 원인을 잡으면서 업황 배경 후보를 더 얻으면 채택한다. 역할 목록의 최종안과 증권사 의견(`analyst_view`)을 원인으로 볼지는 아직 정하지 않았다 | 팀 결정 |
| P11 | **소속과 적용을 나눈다.** "이 회사가 이 산업에 속한다·이 회사와 관계가 있다"(기준표, 고정)와 "이번 사건이 이 회사에 해당한다"(자료마다 판정)는 다른 질문이다. 산업·기업 관계는 근거가 아니라 **후보를 만드는 데만** 쓰고, 해당 여부는 사건마다 DIRECT / INDIRECT_CONTEXT / NOT_APPLICABLE / UNKNOWN 으로 판정해 저장한다. 같은 산업이라는 이유만으로 모든 종목에 붙이지 않는다(예: "중·저사양 FC-BGA 공급 부족" 을 모든 기판 회사에 붙이지 않는다) | 멘토 피드백 (2026-10) |
| P12 | 기업 관계는 1-hop 까지만 넓힌다. 관계에는 종류(supplier / customer / competitor / ownership)·방향·근거 출처를 둔다. 유효 기간·중요도·confidence 는 근거 있게 채울 수 있을 때 더한다 | 멘토 피드백 (2026-10), 팀 결정 |
| P13 | 분류 결과는 보고서 생성 입력(PR #36 으로 develop 에 들어온 `docs/stock_analysis_io.md` 의 `messages[].mention`, 옛 이름 `match`)으로 이어진다. 연결(입력 JSON 구성)은 생성 담당이 하고, 이 설계는 연결에 필요한 값을 조회 결과로 내는 데까지다(5절) | 팀 결정 |
| P14 | **회사–산업 소속의 기준은 사업 관련성이다.** 주가 동행은 소속 기준이 아니다(P5). 연결마다 경로(직접 영위 / 비상장 자회사 / 상장사 지분)·경유 회사·단계(영위 중 / 진출 예정)·역할·근거를 둔다. 상장사 지분·진출 예정 연결로 들어온 후보는 최대 INDIRECT_CONTEXT 다. 넣는 범위와 노드 규칙은 [INDUSTRY_REVIEW.md](INDUSTRY_REVIEW.md) 2-2 ~ 2-5 | 외부 검토 (2026-10-28), 팀 결정 |
| P15 | **30종목 밖 기업은 후보가 아니라 출발점이다.** 엔비디아·TSMC 같은 해외 기업, 한화오션 같은 30종목 밖 상장사는 외부 기업 기준표에 두고, 사건에 언급되면 기업 관계를 따라 30종목 후보를 만드는 데만 쓴다. 외부 기업 자체는 판정·브리핑 대상이 아니다. 비상장 연결 자회사(SK온, 삼성디스플레이 …)는 외부 기업이 아니라 **모회사의 별칭**으로 둔다(P14 의 `subsidiary` 와 같은 논리) | 팀 결정 (2026-10-28) |

---

## 1. 한 줄 요약

**DB 가 후보 종목을 정하고, LLM 은 그 후보마다 "이 사건이 이 종목에 해당하는가" 만 판정한다.**

멘토 피드백(전제 P1·P11)을 표 구조로 옮긴 것이다.

```
① 사건 추출(LLM) → ② 표기 → 종목·산업(사전) → ③ 후보 모으기(DB) → ④ 해당 여부 판정(LLM) → 조회
```

산업·기업 관계(기준표)는 ③ 에서 후보를 만드는 데만 쓴다. 관계가 있다고 연결이 확정되지 않는다.
LLM 은 ④ 에서 후보 밖 종목을 낼 수 없다. 다만 ② 코드 선택은 사전에 없는 표기를 목록 안의 회사로 잘못 이을 수 있고, 코드는 목록 안에 있는지만 본다. 그렇게 이어진 회사는 `company` 후보가 된다([CLASSIFICATION_TUNING.md](CLASSIFICATION_TUNING.md) 2-13).

## 2. 이번에 정한 것

| 항목 | 결정 |
| --- | --- |
| scope 값 | `company` · `industry` · `macro` · `market` 4개 (전제 P1 의 3개에 시황 `market` 을 더함) |
| 거시·시장 문장 | 모든 종목에 똑같이 배경으로 붙인다. 판정하지 않는다. 주제별로 특정 산업에만 붙이는 표는 두지 않는다 |
| 종목 하나가 여러 산업 | 허용한다 (예: 삼성전자 = 메모리반도체 + 가전 + …) |
| 산업 목록 형태 | 계층. 맨 위는 KRX 업종(BE 화면 섹터와 같은 값), 그 아래 산업, 그 아래 세부 산업·제품(필요한 곳만) |
| 산업 목록의 출처 | 분류 초안과 생성 담당 라벨(`stock_meta.json`)을 합친다. 종목마다 더 자세한 쪽을 받는다. 검증은 [INDUSTRY_REVIEW.md](INDUSTRY_REVIEW.md) |
| 화면 섹터와 뉴스용 산업 | 달라도 된다 (예: SK스퀘어 화면 섹터 = 금융, 뉴스 연결 = 지주·투자 + 메모리반도체) |
| 소속 기준 (10-28) | 사업 관련성(전제 P14). 노드는 "받을 노드가 없는 주요 사업" 이거나 "나누면 30종목 안 후보가 달라질 때" 만 만든다. 아니면 조회어(`industries.aliases`) |
| 지분·자회사 연결 (10-28) | 비상장 자회사 사업은 모회사 사업보고서에서 주요 사업으로 확인되면 넣는다(보고 부문은 중요도 근거). 상장사 지분은 명시 목록만(4개로 시작). 경로는 `stock_industries.exposure`(4-2) |
| 관련성 | **(사건, 종목)마다 판정해 저장한다** — DIRECT / INDIRECT_CONTEXT / NOT_APPLICABLE / UNKNOWN (4-8). 10-09판의 "저장하지 않고 경로로 대신한다" 를 뒤집었다(전제 P11) |
| 판정 단위 | 자료가 아니라 사건. 한 자료 안 사건마다 해당 종목이 다를 수 있다 |
| 기업 관계 | `company_relations` 기준표(4-7). 사건에 직접 언급된 종목 **또는 외부 기업**(4-9)에서 1-hop 만 후보로 넓힌다. 한쪽 끝은 반드시 30종목 |
| 외부 기업 (10-28) | `external_companies` 기준표(4-9). 30종목 밖 기업은 출발점으로만 쓰고 후보가 되지 않는다(전제 P15). 비상장 자회사는 모회사 별칭 |
| 분류 대상 종목 | **생성 담당의 `ai/app/services/stock_analysis/stock_meta.json` 30종목** (10-28 확정). 백엔드 `MVP_STOCKS`(100개)는 화면용으로 그대로 두고 바꾸지 않는다. 그래서 30종목 밖 70개 종목의 브리핑에는 분류 자료가 붙지 않는다 |
| 후보 범위 | 기준표에 있는 종목(위 30종목)만 |
| 직접 언급된 종목 | 이것도 판정한다. "대형주 일제히 하락, 삼성전자 등" 같은 지나가는 언급을 거르기 위해서다 |
| 판정 시점 | 자료가 들어올 때(분류 단계). 자료마다 한 번이고, 결과가 남아 검증할 수 있다 |
| 표기 매칭 | 별칭 사전 → 안 잡히면 LLM 이 코드 목록에서 고름 → 그래도 안 잡히면 기록하고 사람이 별칭을 더함. 임베딩은 쓰지 않는다(종목·산업 수가 작다) |
| 분류 대상 자료 | 뉴스·PDF·텔레그램 메시지. 공시는 처음에는 넣지 않는다(종목이 이미 `dart_stock_code` 로 연결돼 있고 제목뿐이다) |
| 거시·시장 주제 표(`market_topics`) | 만들지 않는다. 조립에 쓰이지 않는다. 기사 속 표기는 사건의 `mentions` 에 남는다 |

---

## 3. 전체 구조

### 3-1. 표 개수

데이터 파이프라인과 관련된 표만 센다(BE 의 시세·재무·사용자 표 제외).

| 상태 | 개수 | 표 |
| --- | --- | --- |
| develop 에 이미 있음 (ai 0019 까지) | 9 | `news`, `analyst_reports`, `source_card`, `stock_move_analyses` 외 3개, 참조용 `channel`·`stock`(BE) |
| `feature/data-collection-base` 에서 만듦 (0020~0023, 병합 전) | 2 | `telegram_messages`, `telegram_message_links` |
| `feature/source-index-dart` 에서 만듦 (0024~0026, 병합 전) | 2 | `source_card_stocks`(0024), `dart_disclosures`(0025). 0026 은 공시를 `source_card` 에 연결 |
| **이 설계로 만들 것** | **8** | 기준표 4개 + 결과표 4개 (아래) |

### 3-2. 단계

```
① 원문 (5개) ──▶ ② 공통 번호 (2개) ──▶ ③ 분류 (7개, 이 문서) ──▶ [생성 담당이 연결] ──▶ ④ 보고서 (4개)
```

분류 안의 처리 순서 (자료 하나가 들어올 때)

```
source_card (뉴스 · PDF · 메시지)
 │
 ① LLM   사건 추출 (자료당 1회)
 │        사건마다 scope, role, tense, 근거 문장 번호, 기사 속 표기
 │        → classification_runs, classification_events
 │
 ② 코드  표기 → 종목·산업·외부 기업
 │        별칭 사전 → 안 잡히면 LLM 이 코드 목록에서 고름 → 그래도 안 잡히면 기록
 │        → classification_event_entities
 │
 ③ 코드  후보 종목 모으기 (기준표에 있는 종목만)
 │        company    사건에 직접 언급된 종목
 │        industry   scope = industry 사건 → 그 산업(과 그 아래 단계)에 속한 종목   ◀ stock_industries
 │        relation   직접 언급된 종목·외부 기업에서 1-hop 관계인 종목               ◀ company_relations
 │                   (role = price_move 사건은 이 경로로 넘기지 않음)
 │        macro·market 사건은 후보를 만들지 않음 (조회 때 모든 종목에 공통 배경)
 │
 ④ LLM   (사건, 후보 종목)마다 해당 여부 판정
          입력: 사건 문장 + 후보의 산업·세부 산업 + (industry 경로면) 연결 경로·경유 회사·단계·역할
                + (relation 경로면) 찾은 관계 전부(종류·방향·대상 사업·제품 범위·단계·근거 수준) + 관계 종류별 판정 기준
          출력: DIRECT / INDIRECT_CONTEXT / NOT_APPLICABLE / UNKNOWN + 이유
          규칙: 후보 밖 종목은 낼 수 없다 · direct_allowed = false 인 후보는 최대 INDIRECT_CONTEXT
                (relation 경로, 상장사 지분·진출 예정 연결로 들어온 industry 경로)
          저장 전 코드 보정: 규칙을 어긴 출력·빠진 판정을 고치고 건수를 남김 (4-8)
          → classification_event_applicability
          → DIRECT 만 source_card_stocks (tagged_by = 'classification')
```

### 3-3. 분류 표 7개

**기준표 4개 — 사람이 만든다. 작고 거의 안 바뀐다.**

| 표 | 한 행 | 대략 행 수 |
| --- | --- | --- |
| `industries` | 산업 하나 (계층) | 70여 개 (9절) |
| `stock_industries` | (종목, 산업) 연결 하나 | 80여 개 (INDUSTRY_REVIEW 3절 수정안) |
| `company_relations` | (기업 → 기업, 관계 종류) 하나. 한쪽 끝은 30종목 | 50개 안팎으로 시작 (RELATION_REVIEW 4절) |
| `external_companies` | 30종목 밖 기업 하나 | 15개 안팎으로 시작 (RELATION_REVIEW 3절) |

**결과표 4개 — LLM 이 쌓는다. 자료가 들어올 때마다 는다.**

| 표 | 한 행 | 위 표와의 관계 |
| --- | --- | --- |
| `classification_runs` | 자료 1건을 1번 분류한 기록 | 자료 1 → 회차 N (재분류) |
| `classification_events` | 그 회차의 사건 하나 | 회차 1 → 사건 N |
| `classification_event_entities` | 사건의 표기 하나를 종목·산업으로 바꾼 결과 | 사건 1 → 대상 N |
| `classification_event_applicability` | (사건, 후보 종목) 판정 하나 | 사건 1 → 판정 N |

"하나에 여러 개" 가 겹쳐서 결과표가 여러 단이다. 한 표로 합치면 칸 수를 미리 정할 수 없어 빈칸이 생긴다.

```
source_card.id
   ↑ classification_runs.source_card_id          (지워지지 않게 막음)
classification_runs.id
   ↑ classification_events.run_id                (CASCADE)
classification_events.id
   ↑ classification_event_entities.event_id      (CASCADE)
   │  classification_event_entities.industry_code → industries.code
   ↑ classification_event_applicability.event_id (CASCADE)
      classification_event_applicability.industry_code → industries.code (industry 경로일 때)
      (relation 경로는 관계 행을 FK 로 가리키지 않고 via_stock_code·via_external_code·relation_type 을 적는다 — 4-8)
   │  classification_event_entities.external_code → external_companies.code
      classification_event_applicability.via_external_code → external_companies.code

stock_industries.industry_code → industries.code
company_relations.from_external_code·to_external_code → external_companies.code
company_relations.industry_code → industries.code
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
| `aliases` | jsonb | NN, 기본 `[]` | 조회어. 기사 속 표기 중 이 산업의 후보를 찾는 데 쓰는 문자열 목록 (예: `["D램", "낸드", "HBM"]`). **동의어가 아니다** — 산업보다 좁은 제품명도 들어간다. 사건에는 기사 속 표기가 그대로 남는다(4-4 `mentions`, 4-5 `mention`) |
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
| `exposure` | varchar(16) | NN, CHECK | 연결 경로. `own`: 직접 영위 \| `subsidiary`: 비상장 자회사가 영위 \| `stake`: 상장사를 거친 지분 노출 |
| `via_company` | text | NULL | 경유 회사 이름 (예: "삼성디스플레이", "SK하이닉스"). `own` 이 아니면 채운다 |
| `via_stock_code` | varchar(6) | NULL | 경유 상장사의 종목코드. `stake` 일 때만 채운다. 30종목 밖이어도 된다(예: 한화오션) |
| `stage` | varchar(16) | NN, CHECK | 사업 단계. `operating`: 영위 중 \| `planned`: 진출 예정(공식 발표 있음) |
| `supply_role` | varchar(16) | NULL | 같은 산업 안에서의 역할 (예: ESS 의 `battery` · `pcs`). 역할이 다른 회사가 섞인 산업에서만 채운다 |
| `source` | text | NN | 근거 출처 (사업보고서 항목, 공시, 보도자료 URL 등) |
| `source_as_of` | date | NN | 근거 기준일 (사업보고서 기준일·발표일) |
| `note` | text | NULL | 메모. 다른 경로로도 걸리는 경우, 연결재무제표 포함 여부 등 |
| `basis_version` | varchar(64) | NN | 이 행을 넣은 기준 JSON 의 버전 |
| `created_at` | timestamptz | NN, 기본 `now()` | |

- 제약
  - `UNIQUE(stock_code, industry_code)` — 같은 (종목, 산업)이 두 경로로 걸리면 `own` > `subsidiary` > `stake` 하나만 두고 나머지는 `note` 에
  - `CHECK(exposure IN ('own', 'subsidiary', 'stake'))`, `CHECK(stage IN ('operating', 'planned'))`
  - `CHECK((exposure = 'own') = (via_company IS NULL))` — 직접 영위가 아니면 경유 회사가 있다
  - `CHECK((exposure = 'stake') = (via_stock_code IS NOT NULL))` — 상장사 지분이면 경유 종목코드가 있다
  - `CHECK(via_stock_code IS NULL OR via_stock_code <> stock_code)`
  - `CHECK(source <> '')`, `CHECK(via_company IS NULL OR via_company <> '')`
- 인덱스: `(industry_code)` — 5절 산업 경로에서 "이 산업의 종목" 을 찾는다
- `supply_role` 은 CHECK 를 걸지 않는다. 값이 산업마다 다르고 산업을 더할 때 같이 늘어나서다. 값 목록은 기준 JSON 에 두고, JSON 을 넣는 코드가 검사한다.
- 칼럼 이름의 `exposure` 는 판정 경로(4-8 `path`)와 다르다. `own` 이라도 관련 사건이 모두 `DIRECT` 인 것은 아니다.
- **넣는 범위**(무엇을 `own`·`subsidiary`·`stake` 로 넣는지, 상장사 지분 명시 목록)는 [INDUSTRY_REVIEW.md](INDUSTRY_REVIEW.md) 2-4 가 원본이다.
- 기준 JSON 을 넣는 코드가 검사하는 것 (CHECK 로 못 함)
  - `stake` 행의 경유 상장사는 30종목이거나 `external_companies.stock_code` 로 등록돼 있어야 하고, 그 기업으로 가는 `ownership` 관계(4-7)가 있어야 한다. 예: (한화에어로스페이스, 조선, stake, 한화오션) ↔ (한화에어로스페이스 → 외부 기업 `hanwha_ocean`, ownership). 산업 기사와 회사 기사가 같은 지분을 다르게 보지 않게 한다(INDUSTRY_REVIEW 2-5).
  - `subsidiary` 행의 `via_company` 는 그 종목의 별칭(종류 `subsidiary`, 6절)에 있어야 한다. 예: SK이노베이션의 별칭에 "SK온". 자회사 이름이 나온 기사가 모회사에 닿게 한다.
  - `planned` 행의 `source` 는 공식 발표여야 한다. 형식으로 검사할 수 없으니 기준 JSON 리뷰에서 본다.
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
| `model` | varchar(64) | NULL | ① 사건 추출에 쓴 모델. 단계(추출·코드 선택·판정)마다 다른 모델을 쓸 수 있어 단계별 모델은 `usage` 에 남긴다(10-30) |
| `prompt_sha256` | varchar(64) | NULL | 프롬프트 파일 해시 |
| `criteria_version` | varchar(32) | NULL | 분류 기준(라벨 기준) 버전 |
| `basis_version` | varchar(64) | NN | 표기 → 종목·산업 연결에 쓴 기준 JSON 의 버전(7절) |
| `splitter_version` | varchar(32) | NULL | 문장 분리 규칙 버전. 사건의 문장 번호는 이 규칙으로 나눈 번호다 |
| `input_sha256` | varchar(64) | NULL | 분류에 넣은 본문의 해시. 원문이 그때와 같은지 맞춰 본다 |
| `sentence_count` | integer | NULL | 나눈 문장 수. 사건의 번호가 범위 안인지 저장 전에 검사할 때 쓴다 |
| `raw_response` | text | NULL | 모델 응답 원문. 형식이 깨진 응답도 남긴다 |
| `judge_prompt_sha256` | varchar(64) | NULL | ④ 판정 프롬프트 파일 해시. 판정할 후보가 없었으면 NULL |
| `judge_raw_response` | text | NULL | ④ 판정 모델 응답 원문 |
| `judge_fixes` | jsonb | NN, 기본 `{}` | 저장 전에 코드가 ④ 출력을 보정한 건수 (4-8). 예: `{"direct_lowered": 1, "missing_filled": 2, "outside_dropped": 0, "invalid_label": 0, "duplicate_dropped": 0}` |
| `error` | text | NULL | 실패 사유 |
| `usage` | jsonb | NN, 기본 `{}` | 단계별(`extract`·`link`·`judge`) 토큰 수·비용·모델. ② 코드 선택은 응답 원문도 여기(`link.raw_response`)에 남긴다 |
| `is_current` | boolean | NN, 기본 false | 조회에 쓰는 회차인지 |
| `classified_at` | timestamptz | NN, 기본 `now()` | |

- 제약
  - `CHECK(status IN ('ok','failed','no_body','skipped'))`
  - `CHECK(NOT is_current OR status = 'ok')` — 실패한 회차는 조회에 쓸 수 없다
  - `CHECK(status <> 'ok' OR (splitter_version IS NOT NULL AND input_sha256 IS NOT NULL AND sentence_count IS NOT NULL))` — 성공한 회차는 문장 번호를 다시 풀 수 있어야 한다
  - 부분 UNIQUE `(source_card_id) WHERE is_current` — 자료마다 지금 쓰는 회차는 하나
- 인덱스: `(source_card_id)`
- **현재 회차 교체와 `source_card_stocks` 갱신은 한 트랜잭션으로 한다(4-6).** 중간에 실패하면 이전 상태 그대로 남는다.
- 회차 하나에 ① 사건 추출, ② 코드 선택, ④ 판정이 함께 들어간다. 하나라도 실패하면 `failed` 다. `usage` 에 단계(`extract`·`link`·`judge`)별 토큰·비용·모델을 남긴다. `model` 칼럼은 ① 추출 모델이다.
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
| `tense` | varchar(16) | NN, CHECK | `past`(이미 일어남) \| `future`(전망). 10-21 실험에서 `happened`·`expected` 일 때 모델이 role 칸에 이 값을 넣는 실수를 해서 바꿨다 |
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
- **근거 위치:** 원문은 한 번 확보하면 바뀌지 않으므로 "회차의 `splitter_version` 으로 원문을 나눈 뒤 이 번호의 문장" 이 곧 근거 위치다. 글자 위치 칼럼은 두지 않는다. 기사·메시지·PDF 모두 저장 코드가 정상 본문을 덮어쓰지 않는다. `input_sha256` 은 원문이 그때와 같은지 맞춰 볼 값으로 남기지만 **지금은 비교하는 코드가 없다**([CLASSIFICATION_TUNING.md](CLASSIFICATION_TUNING.md) 2-10).
- **근거 구절 원문을 복사해 두지 않는다.** 복사하면 보관 정책으로 원문을 지워도 사본이 남는다(전제 P8). 원문이 지워진 뒤에는 "원문 없음" 으로 표시한다.

### 4-5. `classification_event_entities` — 표기 → 종목·산업·외부 기업

한 행 = 사건의 표기 하나를 종목·산업·외부 기업 중 하나로 바꾼 결과.

| 칼럼 | 타입 | NULL | 설명 |
| --- | --- | --- | --- |
| `id` | bigint | NN | PK |
| `event_id` | bigint | NN | FK → `classification_events.id` (ON DELETE CASCADE) |
| `stock_code` | varchar(6) | NULL | 종목이면 채운다 |
| `industry_code` | varchar(32) | NULL | FK → `industries.code`. 산업이면 채운다 |
| `external_code` | varchar(32) | NULL | FK → `external_companies.code`. 외부 기업이면 채운다(4-9) |
| `mention` | text | NN | 이 연결의 근거가 된 표기. 사건의 `mentions` 중 하나 |
| `linked_by` | varchar(16) | NN, CHECK | `alias`(별칭 사전) \| `llm_code`(별칭에 안 걸린 표기를 LLM 이 코드 목록에서 고름). 나중에 `manual`(사람)을 더할 수 있다 |
| `via_subsidiary` | text | NULL | 자회사 별칭(종류 `subsidiary`, 6절)으로 연결됐을 때 그 자회사의 정식 이름 (예: 표기 "SDC" → 종목 삼성전자, `via_subsidiary = '삼성디스플레이'`). 실제 언급된 자회사를 잃지 않고, ③ 관계 확장 범위와 ④ 판정 입력에 쓴다 |

- 제약
  - `CHECK(industry_code IS NULL OR via_subsidiary IS NULL)` — 산업에는 자회사 별칭이 없다
  - `CHECK(via_subsidiary IS NULL OR via_subsidiary <> '')`
  - `CHECK(num_nonnulls(stock_code, industry_code, external_code) = 1)` — 종목·산업·외부 기업 중 하나만. `telegram_message_links` 의 `ck_telegram_message_link_target` 과 같은 방식
  - `UNIQUE(event_id, stock_code, mention)`, `UNIQUE(event_id, industry_code, mention)`, `UNIQUE(event_id, external_code, mention)` — 같은 표기로 같은 대상을 두 번 넣지 않는다. 표기가 다르면 같은 대상이라도 행이 따로 생긴다(예: 한 사건에 "삼성전자" 와 "Samsung Electronics" → 같은 종목 2행). 그래야 사건의 `mentions` 와 비교할 때 연결된 표기를 미연결로 잘못 보지 않는다. NULL 끼리는 겹치지 않으므로 세 제약이 서로 막지 않는다
  - `CHECK(mention <> '')`
  - `CHECK(linked_by IN ('alias', 'llm_code'))`
- 인덱스: `(event_id)`, `(stock_code)`, `(industry_code)`, `(external_code)`
- 외부 기업 행은 후보를 직접 만들지 않는다. ③ 의 `relation` 경로 출발점으로만 쓴다(5-1).
- 같은 사건이 한 종목에 여러 행으로 걸릴 수 있으므로, 후보 모으기(5-1)와 `source_card_stocks` 갱신(4-6)은 (사건, 종목) 또는 (자료, 종목)으로 중복을 없앤다.
- 어느 별칭에도 안 걸린 표기(예: "삼성")는 이 표에 행이 없다. 사건의 `mentions` 와 비교하면 찾을 수 있고, 사람이 보고 별칭을 더한 뒤 재분류한다.
- 거시·시장 사건은 대개 이 표에 행이 없다. 모든 종목에 붙으므로 대상이 필요 없다.

### 4-6. `source_card_stocks` — 기존 표, 칼럼 변경 없음

- 현재 회차의 판정(4-8) 중 `label = 'DIRECT'` 인 (자료, 종목)을 `tagged_by = 'classification'` 으로 넣는다. 경로·scope 는 따지지 않는다.
- 이미 `report_item_code`·`dart_stock_code` 로 연결된 (자료, 종목)은 고유 제약 때문에 넣지 않고 건너뛴다(그 연결은 이미 있다).
- 현재 회차가 바뀌면 그 자료의 `classification` 행만 지우고 다시 넣는다. 다른 `tagged_by` 행은 건드리지 않는다. 4-3 의 회차 교체와 같은 트랜잭션.
- 이 표는 종목에 **직접** 해당하는 자료만 담는다. INDIRECT_CONTEXT·거시·시장 자료는 여기 없다(5절).

### 4-7. `company_relations` — 기업 ↔ 기업 관계 (기준표)

한 행 = 두 기업 사이의 관계 하나를 **(관계 종류, 산업) 하나**로 나눈 것. 같은 두 회사라도 관계 종류가 다르거나(공급 + 경쟁), 같은 공급 관계라도 걸린 산업이 다르면(디스플레이 OLED + 메모리 DRAM) 행을 나눈다.
양 끝은 각각 30종목이거나 외부 기업(4-9)이고, **적어도 한쪽은 30종목**이다. 사람이 근거를 보고 넣는다. ③ 에서 후보를 넓히는 데만 쓴다(전제 P11·P12·P15).

**10-30 (10-29 멘토링 방향): 코드 경로가 달라지는 값만 칸으로 둔다.** 양 끝·종류·산업은 ③ 의 후보와 자회사 범위 제한(5-1)을 바꾸므로 칸이다. 제품·계약 범위, 단계, 근거 수준, 실제 당사자, 적용 기간은 ④ 판정 입력으로만 쓰이므로 `note` 한 칸에 적고 그대로 판정에 넘긴다. 10-28 판의 `product_scope`·`from_/to_via_company`·`stage`·`evidence`·`source_as_of`·`period_from/to` 칸은 없앴다(12절). 넣는 기준(무엇을 넣고 무엇을 note 에 적는지)은 그대로 [RELATION_REVIEW.md](RELATION_REVIEW.md) 2절이다.

| 칼럼 | 타입 | NULL | 설명 |
| --- | --- | --- | --- |
| `id` | bigint | NN | PK |
| `from_stock_code` | varchar(6) | NULL | 아래 `relation_type` 의 주어가 30종목이면 |
| `from_external_code` | varchar(32) | NULL | FK → `external_companies.code`. 주어가 외부 기업이면 |
| `to_stock_code` | varchar(6) | NULL | 목적어가 30종목이면 |
| `to_external_code` | varchar(32) | NULL | FK → `external_companies.code`. 목적어가 외부 기업이면 |
| `relation_type` | varchar(16) | NN, CHECK | `supplier`: from 이 to 의 공급사 (to 에서 보면 고객사) \| `competitor`: 서로 경쟁사 \| `ownership`: from 이 to 의 지분을 가짐 |
| `industry_code` | varchar(32) | NULL | FK → `industries.code`. 관계가 걸린 사업 (예: SK하이닉스 → 엔비디아 `supplier` 는 `memory`). 고유 키에 들어간다. 지분 관계는 비어 있을 수 있다 |
| `source` | text | NN | 근거 출처 (사업보고서 항목, 공시 번호, URL, 발표일 등) |
| `note` | text | NULL | 판정에 넘기는 관계 설명. 제품·계약 범위("범위 HBM4·SOCAMM2"), 확인된 단계("단계 공급 확인"·"계약 확인"·"협의·개발"), 근거 수준("근거 official"·"reported"), 실제 당사자("실제 당사자 삼성디스플레이"), 적용 기간("기간 2026~2032"). 같은 (from, to, 종류, 산업)에 범위가 여럿이면 함께 적는다 (예: 포스코퓨처엠 → 삼성SDI 의 NCA 공급 확인 + LFP 계약 확인) |
| `basis_version` | varchar(64) | NN | 이 행을 넣은 기준 JSON 의 버전(7절) |
| `created_at` | timestamptz | NN, 기본 `now()` | |

- 제약
  - `CHECK(num_nonnulls(from_stock_code, from_external_code) = 1)`, `CHECK(num_nonnulls(to_stock_code, to_external_code) = 1)` — 양 끝은 종목이든 외부 기업이든 하나씩
  - `CHECK(from_stock_code IS NOT NULL OR to_stock_code IS NOT NULL)` — 외부 기업끼리의 관계는 넣지 않는다. 후보는 30종목뿐이고 1-hop 이라 쓰일 데가 없다
  - `CHECK(from_stock_code IS NULL OR to_stock_code IS NULL OR from_stock_code <> to_stock_code)` — 자기 자신과의 관계 금지. 외부 기업끼리는 위 제약에서 이미 막힌다
  - `CHECK(relation_type IN ('supplier', 'competitor', 'ownership'))`
  - `CHECK(relation_type <> 'competitor' OR (from_stock_code IS NOT NULL AND (to_external_code IS NOT NULL OR from_stock_code < to_stock_code)))` — 방향이 없는 관계는 한 행만 둔다. 종목끼리는 코드가 작은 쪽이, 외부 기업과는 종목 쪽이 from 이다. 기준 JSON 에는 순서 상관없이 쓰고 넣는 코드가 맞춘다
  - `CHECK(source <> '')`
  - 고유: `CREATE UNIQUE INDEX uq_company_relations_key ON company_relations (coalesce(from_stock_code, from_external_code), coalesce(to_stock_code, to_external_code), relation_type, coalesce(industry_code, ''))`. NULL 이 섞인 칼럼에 그냥 `UNIQUE` 를 걸면 NULL 끼리 다른 값으로 봐서 중복을 못 막는다. 종목코드(숫자·영문 대문자 6자리)와 외부 기업 코드(영문 소문자로 시작, 4-9)는 겹치지 않으므로 합쳐서 비교해도 된다
- 인덱스: `(from_stock_code)`, `(to_stock_code)`, `(from_external_code)`, `(to_external_code)` — ③ 에서 언급된 기업이 어느 쪽에 있든 찾는다
- 고객 관계는 따로 두지 않는다. `supplier` 를 반대 방향으로 읽으면 고객이다. 두 종류로 두면 같은 관계가 두 행으로 들어간다.
- 합작·제휴는 종류를 따로 두지 않는다. 공급이 있으면 `supplier`, 지분이 있으면 `ownership` 으로 넣고 합작법인 이름은 `note` 에 실제 당사자로 적는다.
- ③ 은 **양방향**으로 후보를 만든다. 고객의 수요 감소 → 공급사, 공급사의 생산 차질 → 고객 둘 다 있기 때문이다. 방향은 ④ 판정 입력에 넘긴다(`relation_refs.candidate_is`). 외부 기업 쪽은 후보가 되지 않으므로, 외부 기업이 걸린 관계는 사실상 외부 기업 → 종목 한 방향으로만 쓰인다.
- 중요도·confidence 칼럼은 두지 않는다. 근거 있게 채울 수 없다(전제 P12). 단계·근거 수준·기간은 `note` 로 판정에 넘긴다. 보도만 있는 관계도 받되 `note` 에 "근거 reported" 를 적는다.
- 협의·개발 단계 관계도 후보를 만든다. `note` 의 단계로 "공급 중" 과 구별하게 한다.
- `ownership` 의 from 은 **실제 보유 법인**이다. 그룹 전체 보유를 한 회사 보유로 적지 않는다. 법인 보유를 확인하지 못한 관계는 넣지 않는다.
- 경쟁 관계는 영향 방향(반사이익·동반 악재)을 정하지 않는다. 후보만 만들고 방향은 판정·생성 단계가 기사를 보고 정한다.
- 이 표도 **지금 기준만** 담는다(4-2 와 같다). 종료된 관계는 넣지 않는다. 그래서 판정 표가 이 표의 `id` 를 FK 로 가리키지 않는다(4-8).

- **넣는 기준**(관계 종류별 넣는 조건, 근거 수준·단계의 쓰임)과 **시작 목록**은 [RELATION_REVIEW.md](RELATION_REVIEW.md) 2·4절이 원본이다. 그 문서의 제품별 행(23a·23b, 50·51 등)은 산업이 같으면 기준 JSON 에서 한 행으로 합치고 `note` 에 둘 다 적는다.
- `stock_industries` 의 `stake` 행에는 짝이 되는 `ownership` 행이 있어야 한다(4-2 검사).

### 4-8. `classification_event_applicability` — 사건 × 종목 판정

한 행 = 사건 하나가 후보 종목 하나에 해당하는지 판정한 결과(④).

| 칼럼 | 타입 | NULL | 설명 |
| --- | --- | --- | --- |
| `id` | bigint | NN | PK |
| `event_id` | bigint | NN | FK → `classification_events.id` (ON DELETE CASCADE) |
| `stock_code` | varchar(6) | NN | 후보 종목 |
| `label` | varchar(24) | NN, CHECK | `DIRECT` \| `INDIRECT_CONTEXT` \| `NOT_APPLICABLE` \| `UNKNOWN` |
| `path` | varchar(16) | NN, CHECK | 후보가 된 경로. `company` \| `industry` \| `relation` |
| `industry_code` | varchar(32) | NULL | FK → `industries.code`. `industry` 경로일 때 걸린 산업 |
| `via_stock_code` | varchar(6) | NULL | `relation` 경로가 종목에서 출발했을 때 그 종목(사건에 직접 언급된 종목) |
| `via_external_code` | varchar(32) | NULL | FK → `external_companies.code`. `relation` 경로가 외부 기업에서 출발했을 때 그 기업(사건에 직접 언급된 외부 기업) |
| `relation_type` | varchar(16) | NULL | `relation` 경로일 때 대표 관계의 종류. 판정 당시 값을 그대로 적는다 |
| `relation_refs` | jsonb | NN, 기본 `[]` | 이 후보에 걸린 **관계 전부**. 판정에 모두 넘긴 값이다. **대표 경로(`path`)와 상관없이 보존한다** — 산업 경로나 직접 언급으로 합쳐진 후보도 관계로도 걸렸으면 여기 남는다. 예: `[{"via": "apple", "type": "supplier", "candidate_is": "supplier", "industry": "display", "note": "범위 OLED 패널. 실제 당사자 삼성디스플레이. 단계 공급 확인"}, {"via": "apple", "type": "competitor", "candidate_is": "competitor", "industry": "smartphone", "note": "범위 스마트폰"}]`. `candidate_is` 는 출발점에서 본 후보의 자리(`supplier`·`customer`·`competitor`·`owner`·`owned`). 위 `via_*`·`relation_type` 은 `path = 'relation'` 일 때 이 중 대표 하나다(5-1) |
| `direct_allowed` | boolean | NN | 이 후보가 `DIRECT` 를 받을 수 있는지. ③ 이 경로로 정한다(5-1). `company` → true, `relation` → false, `industry` → 걸린 연결(4-2)이 `exposure = 'stake'` 이거나 `stage = 'planned'` 면 false, 아니면 true |
| `reason` | text | NULL | 판정 이유 |

- 판정 값의 뜻

  | 값 | 뜻 |
  | --- | --- |
  | `DIRECT` | 이 사건이 이 종목에 직접 해당한다 |
  | `INDIRECT_CONTEXT` | 이 종목의 업황·경쟁·거래 관계 배경이다 |
  | `NOT_APPLICABLE` | 후보였지만 이 종목과 관계없다 (예: 같은 산업이지만 다른 제품) |
  | `UNKNOWN` | 주어진 정보로 판단할 수 없다 |

- 제약
  - `UNIQUE(event_id, stock_code)` — 한 사건·종목에 판정 하나. 여러 경로로 후보가 됐으면 ③ 에서 위쪽 경로 하나를 대표로 고른다(`company` > `industry` > `relation`). 관계 근거는 `relation_refs` 에 남긴다
  - `label`·`path`·`relation_type` 의 `IN (...)` CHECK
  - `CHECK((path = 'industry') = (industry_code IS NOT NULL))`
  - `CHECK((path = 'relation') = (num_nonnulls(via_stock_code, via_external_code) = 1 AND relation_type IS NOT NULL))` — relation 경로면 출발점(종목 또는 외부 기업) 하나와 관계 종류가 있다
  - `CHECK(path = 'relation' OR num_nonnulls(via_stock_code, via_external_code, relation_type) = 0)` — 다른 경로에는 출발점·관계 종류를 적지 않는다
  - `CHECK(jsonb_typeof(relation_refs) = 'array')`, `CHECK(path <> 'relation' OR jsonb_array_length(relation_refs) > 0)` — relation 경로면 관계가 하나 이상. 다른 경로는 비어 있어도, 차 있어도 된다(합쳐진 관계 근거를 버리지 않는다)
  - `CHECK(path <> 'relation' OR NOT direct_allowed)` — 관계로 들어온 종목은 기사가 말하지 않은 종목이라 DIRECT 가 될 수 없다
  - `CHECK(path <> 'company' OR direct_allowed)`
  - `CHECK(direct_allowed OR label <> 'DIRECT')` — 상장사 지분·진출 예정 연결로 들어온 industry 경로 후보도 DIRECT 불가(전제 P14). 산업 기사는 그 사업을 하는 상장사의 소식이거나 아직 매출이 없는 사업의 소식이라, 모회사에 직접 해당하지 않는다
- 인덱스: `(event_id)`, `(stock_code)`
- **저장 전 보정 (코드).** ④ 출력을 그대로 넣으면 LLM 출력 하나가 CHECK 에 걸려 회차 전체가 롤백된다. 저장 전에 코드가 아래처럼 고치고, 고친 건수를 회차의 `judge_fixes` 에 남긴다. 판정 이유(`reason`) 앞에는 `[보정: …]` 을 붙인다.

  | ④ 출력 | 보정 | `judge_fixes` 키 |
  | --- | --- | --- |
  | `direct_allowed = false` 인 후보에 `DIRECT` | `INDIRECT_CONTEXT` 로 내린다 | `direct_lowered` |
  | 후보인데 판정이 없음 | `UNKNOWN` 으로 채운다 (`reason = '[보정: 판정 누락]'`) | `missing_filled` |
  | 후보 밖 종목 | 버린다 (후보 밖 종목을 낼 수 없다는 규칙, 전제 P4) | `outside_dropped` |
  | 허용 밖 판정 값 (예: `INDIRECT`) | `UNKNOWN` 으로 바꾼다 | `invalid_label` |
  | 같은 (사건, 종목)에 판정이 둘 이상 | 처음 것만 남긴다 | `duplicate_dropped` |

  - ④ 응답이 JSON 으로 열리지 않거나 사건 번호를 알아볼 수 없으면 보정하지 않고 회차를 `failed` 로 둔다(4-3).
  - 보정 건수가 많으면 프롬프트를 고칠 신호다. 평가(11절 17번) 때 회차별 `judge_fixes` 를 함께 본다.
- 판정 입력에는 후보 종목의 산업·세부 산업(`stock_industries`)과, industry 경로면 걸린 연결의 `exposure`·`via_company`·`stage`·`supply_role`, `relation_refs` 가 있으면(경로와 상관없이) 관계마다 출발 기업 이름·관계 종류·방향·`industry_code`·`note`(제품 범위·단계·근거 수준·실제 당사자, 10-29)를 넣는다. 자회사 표기로 연결된 대상(4-5 `via_subsidiary`)은 "자회사 ○○ 언급" 으로 넣는다. 예: "SK스퀘어 — 메모리반도체, 상장사 지분(SK하이닉스)", "LS ELECTRIC — ESS, 역할 PCS", "삼성전자 — 애플의 공급사(디스플레이, OLED 패널, 실제 당사자 삼성디스플레이, 공급 중) + 애플의 경쟁사(스마트폰)". 세부 산업 정보가 없으면 LLM 이 회사 사업을 짐작하게 되므로 이 정보가 판정의 근거다.
- 관계 종류별 판정 기준은 ④ 프롬프트에 적는다. 예: supplier·customer 는 수요·발주·생산 차질·단가 소식(`note` 의 단계가 협의·개발·계약 확인이면 공급이 확인되지 않았음을 감안), competitor 는 사고·생산 차질·점유율·가격 경쟁·규제(반사이익인지 동반 악재인지 정하지 않는다), ownership 은 자회사 실적·가치 → 모회사. 사건의 제품이 관계의 `industry_code`·`note` 의 범위와 맞지 않으면 NOT_APPLICABLE 이다. 평가에서 자주 틀리는 경우가 보이면 그 규칙을 코드(③ 의 후보 제외)로 옮긴다.
- 관계 행을 FK 로 가리키지 않는 이유: 기준표는 기준이 바뀌면 통째로 바뀐다(4-2, 7절). 판정 당시 어떤 관계였는지는 `relation_refs`(판정에 넘긴 관계 전부)와 회차의 `basis_version` 으로 남긴다. industry 경로의 연결 속성(`exposure` 등)도 같은 이유로 복사하지 않는다. 판정에 영향을 준 결과만 `direct_allowed` 로 남기고, 나머지는 `industry_code` 와 `basis_version` 으로 그때의 기준 JSON 에서 찾는다.
- macro·market 사건은 이 표에 행이 없다. 판정하지 않고 조회 때 모든 종목에 붙는다(5절).

### 4-9. `external_companies` — 외부 기업 (기준표)

한 행 = 30종목 밖의 기업 하나. 해외 기업(엔비디아, TSMC), 30종목 밖 국내 상장사(한화오션, LG화학), 30종목의 연결 자회사가 아닌 비상장사(보스턴다이내믹스 등)를 담는다.
**후보가 되지 않는다.** 사건에 언급되면 `company_relations` 를 따라 30종목 후보를 만드는 출발점으로만 쓴다(전제 P15).

| 칼럼 | 타입 | NULL | 설명 |
| --- | --- | --- | --- |
| `code` | varchar(32) | NN, PK | 식별자 (예: `nvidia`, `tsmc`, `hanwha_ocean`). **한 번 정하면 바꾸지 않는다** — 분류 결과가 FK 로 가리킨다 |
| `name` | varchar(100) | NN | 표시 이름 (예: "엔비디아") |
| `country` | varchar(2) | NULL | 국가 코드 ISO 3166-1 (예: `US`, `TW`, `KR`) |
| `stock_code` | varchar(6) | NULL | 국내 상장사면 종목코드. 4-2 `stake` 의 경유 상장사와 맞춰 볼 때 쓴다 |
| `ticker` | varchar(16) | NULL | 해외 상장사면 거래소 티커 (예: `NVDA`). 사람이 확인할 때 쓴다 |
| `retired_at` | timestamptz | NULL | 기준에서 빠진 시각. 지우지 않는다(과거 분류 결과가 가리키므로) |
| `basis_version` | varchar(64) | NN | 마지막으로 이 행을 넣은 기준 JSON 의 버전(7절) |
| `created_at` | timestamptz | NN, 기본 `now()` | |

- 제약
  - `CHECK(code ~ '^[a-z][a-z0-9_]*$')` — 영문 소문자만 쓴다. 종목코드(숫자·영문 대문자)와 겹치지 않게 한다. 4-7 의 고유 식 인덱스가 이걸 전제로 한다
  - `CHECK(stock_code IS NULL OR stock_code ~ '^[0-9A-Z]{6}$')` — 2024년부터 새로 상장한 종목은 영문 대문자가 섞인 코드를 쓴다(예: 삼성에피스홀딩스 `0126Z0`). 숫자만 받으면 이런 종목을 거부한다
  - 부분 UNIQUE `(stock_code) WHERE stock_code IS NOT NULL` — 국내 상장사 하나를 두 번 넣지 않는다
- 별칭은 종목 별칭처럼 기준 JSON 에만 둔다(전제 P6, 7절). 예: `nvidia` → "엔비디아", "NVIDIA", "Nvidia".
- 기준 JSON 을 넣는 코드가 검사하는 것 (CHECK 로 못 함)
  - `stock_code` 가 30종목이 아니다. 30종목이면 외부 기업이 아니라 종목으로 다룬다.
  - 외부 기업마다 `company_relations` 행이 하나 이상 있다. 관계가 없으면 출발점으로 쓸 데가 없으므로 넣지 않는다.
  - 외부 기업 이름이 어떤 종목의 별칭과도 겹치지 않는다. 비상장 연결 자회사는 외부 기업이 아니라 모회사 별칭이다(전제 P15, 6절). 외부 기업의 비상장 연결 자회사도 그 외부 기업의 별칭이다(예: 삼성에피스홀딩스 ← "삼성바이오에피스").
- **넣는 기준과 시작 목록**은 [RELATION_REVIEW.md](RELATION_REVIEW.md) 2-1·3절이 원본이다. 요약: 30종목 중 하나 이상과 관계가 있는 기업만 넣고, 이후에는 미연결 표기 기록(6절)에 자주 나오는 30종목 밖 기업을 보고 더한다.
- 은퇴한 외부 기업(`retired_at` 있음)에는 새 관계를 넣지 않는다. 기준 JSON 을 넣는 코드가 검사한다.

---

## 5. 후보 모으기 규칙과 종목별 조회

### 5-1. 후보 모으기 (③, 분류할 때)

사건마다 아래 경로로 후보 종목을 모은다. 후보는 기준표에 있는 종목(`stock_meta.json` 30종목)만이다.

| 경로 | 찾는 조건 | 쓰는 기준표 |
| --- | --- | --- |
| `company` | 사건의 대상(4-5)에 종목이 있다 (scope 무관) | — |
| `industry` | `scope = 'industry'` 이고, 대상 산업이 종목의 산업 **자신이거나 그 상위** | `stock_industries`, `industries` |
| `relation` | `company` 경로 종목 또는 사건 대상의 외부 기업(4-5 `external_code`)과 1-hop 관계인 30종목 (양방향). `role = 'price_move'` 사건은 넘기지 않는다 | `company_relations` |

- `industry` 경로는 `scope = 'industry'` 인 사건만 탄다. "삼성전자, 메모리 가격 상승에 실적 개선" 처럼 회사 사건에 산업 표기가 섞였다고 다른 메모리 회사에 퍼지지 않게 한다.
- 상위 산업 매칭: 종목의 산업과 그 조상 산업 목록을 먼저 구한다(산업 표가 수십 행이라 코드에서 계산하거나 `WITH RECURSIVE` 한 번). "반도체 업황" 기사(`semiconductor`)는 그 아래 `memory`·`foundry` 종목에 모두 붙고, "D램" 기사(`memory`)는 메모리 종목에만 붙는다.
- 같은 상위 아래의 **형제 세부 산업으로는 넓히지 않는다.** "중·저사양 FC-BGA" 기사는 고사양 FC-BGA 종목의 후보가 아니다. 형제 산업에도 배경이 될 수 있지만, 넓히면 같은 산업 전체에 붙이는 문제(전제 P11)로 돌아간다.
- `relation` 경로는 사건에 **직접 언급된** 기업에서만 출발한다. 30종목이면 `company` 경로 종목, 30종목 밖이면 외부 기업이다. `industry` 경로로 들어온 종목에서 다시 넓히지 않는다(사실상 2-hop 이 되므로).
- 외부 기업은 scope 와 상관없이 출발점이 된다. "엔비디아, HBM 주문 확대" 를 LLM 이 `company` 로 보든 `industry` 로 보든 SK하이닉스·삼성전자가 relation 경로 후보가 된다. 이 기사가 산업 표기("HBM")로도 걸리면 대표 경로는 위쪽(`industry`)이지만, 엔비디아 공급 관계는 `relation_refs` 에 남아 판정에 넘어간다.
- **자회사 표기로 들어온 출발점은, 공급·경쟁 관계는 그 자회사 사업 범위의 것만 탄다.** 대상의 `via_subsidiary`(4-5)가 있으면, `supplier`·`competitor` 관계는 다음 둘 중 하나를 만족해야 탄다. (1) 관계의 그 쪽 실제 당사자가 그 자회사다 — **10-30: 실제 당사자가 `note` 로 옮겨져 코드가 볼 수 없다. 지금은 (2)만 본다.** 외부 기업의 자회사 표기(삼성바이오에피스)는 외부 기업에 산업 연결이 없어 (2)로 거를 수 없으므로 제한하지 않는다. (2) 관계의 `industry_code` 가 그 자회사를 거친 산업 연결(4-2 `exposure = 'subsidiary'`, `via_company` = 그 자회사)의 산업이다. 예: "삼성디스플레이" 기사 → 삼성전자 → 애플 OLED 공급(실제 당사자 삼성디스플레이)은 타고, 삼성전자–LG전자 가전 경쟁은 타지 않는다. "하만" 기사 → 삼성전자 → 엔비디아 HBM 공급은 타지 않는다. **`ownership` 관계는 이 제한을 받지 않는다.** 지분 관계는 사업 범위가 아니라 보유자를 찾는 것이라 산업이 비어 있어, 제한하면 항상 걸러진다. 예: "삼성바이오에피스" 기사 → 삼성에피스홀딩스(외부 기업) → 삼성물산·삼성전자 지분. 판정 상한(relation 경로, INDIRECT_CONTEXT)은 그대로다. 기준은 [RELATION_REVIEW.md](RELATION_REVIEW.md) 2-1.
- 한 종목이 relation 경로로 여러 번 걸리면(예: 애플 생산 차질 → 삼성전자는 OLED·메모리 공급사이자 스마트폰 경쟁사) **후보는 하나로 합치고, 찾은 관계는 모두 `relation_refs` 에 담아 판정에 넘긴다.** 영향 경로가 서로 다르기 때문이다. 대표 관계(`via_*`·`relation_type`)는 출발점이 종목인 관계를 먼저, 그 안에서는 기준 JSON 순서로 고른다. (10-30: 근거 수준·단계가 `note` 로 옮겨져 순서 기준에서 빠졌다. 기준 JSON 에 공식·공급 확인 관계를 먼저 적는다)
- `role = 'price_move'` 사건("B사 주가 3% 하락")은 관계 회사에 대한 정보가 아니라서 `relation` 경로로 넘기지 않는다.
- 한 종목이 여러 경로에 걸리면 위쪽 경로 하나를 대표로 고른다(`company` > `industry` > `relation`). **관계 경로로도 걸렸다면 그 관계는 버리지 않고 `relation_refs` 에 남긴다.** 대표 경로는 `direct_allowed` 와 저장 칸을 정할 뿐이고, 판정에 넘기는 근거는 줄이지 않는다.
- `industry` 경로에서 한 종목이 여러 연결에 걸리면(예: "반도체 업황" → 삼성전자의 메모리반도체·파운드리) `direct_allowed = true` 인 연결을 먼저, 그 안에서는 기준 JSON 순서로 하나를 고른다. 고른 연결의 `industry_code` 를 판정에 적는다.
- `stake`·`planned` 연결도 후보는 만든다. 후보에서 빼지 않고 `direct_allowed = false` 로 판정 상한만 둔다. 산업 기사에서 SK스퀘어 같은 지분 노출 종목을 놓치지 않기 위해서다(INDUSTRY_REVIEW 2-5).
- macro·market 사건은 후보를 만들지 않는다.

### 5-2. 종목별 조회 (생성 쪽에 넘기는 것)

입력: 종목 X, 기준 시각 T, 조회 기간, 판정 조건(기본 `DIRECT`·`INDIRECT_CONTEXT`).
기존 `stock_card_ids()` 는 `source_card_stocks` 만 보므로 DIRECT 자료만 나온다. 아래 두 갈래를 합친다.

| 갈래 | 찾는 조건 |
| --- | --- |
| 판정 | 현재 회차 사건의 판정(4-8)에서 `stock_code = X` 이고 `label` 이 판정 조건에 맞음 |
| 공통 배경 | 현재 회차 사건 중 `scope IN ('macro', 'market')` |

- 시각 조건은 `stock_card_ids()` 와 같은 규칙을 쓴다: `source_card.available_at <= T`(기준 시각과 같은 시각의 자료는 포함), 공개 시각을 모르면 `event_date` 가 T 의 날짜(KST)보다 앞선 날. 이 조건 부분을 함수로 떼어 두 갈래가 같이 쓴다.
- 사건은 본문에서 나왔다. 공개는 T 전이어도 본문을 T 뒤에 받았거나 받은 시각을 모르면 `sources` 에서 빼고 `not_observed` 로 센다(`get_sources` 의 `cutoff` 와 같은 규칙).
- 현재 회차(`is_current`)의 사건만 본다. 분류하지 않은 자료, 실패만 있는 자료는 "미분류" 로 따로 센다.
- NOT_APPLICABLE·UNKNOWN 은 기본으로 빼되, 조건으로 요청하면 낸다(판정 품질 점검용).
- `DIRECT` 외 판정·공통 배경으로 온 사건은 원인으로 확정하지 않는다(전제 P4·P5). 원인인지는 생성 단계가 시세와 함께 판단한다.

반환 형태 (Python `dict`. JSON 문자열로 바꾸는 건 생성 쪽이 프롬프트에 넣을 때 한다. 키는 snake_case)

```jsonc
{
  "sources": [                              // 자료 단위
    {
      "source_card_id": 101,
      "card_type": "message",               // news | pdf | message
      "source_name": "...", "url": "...", "channel_id": 3,
      "available_at": "2026-10-20T09:12:00+09:00",
      "body_status": "ok",
      "card_label": "DIRECT",               // 이 자료 안 사건 판정 중 가장 강한 값. 공통 배경 사건만 있으면 null
      "events": [                           // 사건 단위
        {
          "event_id": 5001, "run_id": 77,
          "scope": "company", "role": "cause", "tense": "past",
          "sentence_indices": [3],
          "context_indices": [2],           // 근거 문장만으로 뜻이 안 통할 때 함께 읽을 문장. 없으면 []
          "label": "DIRECT",                // 공통 배경 사건이면 null
          "path": "company"                 // company | industry | relation | macro | market
        }
      ]
    }
  ],
  "unclassified": 4,                        // 기간 안에 있지만 분류 안 된 자료 수
  "failed": 1,                              // 분류에 실패만 한 자료 수
  "not_observed": 2                         // 판정은 있지만 기준 시각에 본문이 없던 자료 수
}
```

- `card_label` 순서: `DIRECT` > `INDIRECT_CONTEXT` > `UNKNOWN` > `NOT_APPLICABLE`. 이 자료 안 사건 판정 중 가장 강한 값이 대표값이고, 새 표 없이 조회할 때 계산한다. 생성 쪽 `mention` 은 이 값이 아니라 `events[].path` 로 정한다(5-3). `DIRECT` 에는 industry 경로도 들어가서 "이 종목을 직접 다룸" 과 뜻이 다르다.
- 원문(메시지 `text`·기사 본문)은 넣지 않는다. `source_card_id` 로 원문 표를 따라가 읽는다(`repositories/source_card/query.py` 의 `get_sources`).
- `body_status` 는 자료 종류마다 다른 칸에서 만든다. 텔레그램 메시지 표에는 이 칸이 없다.

  | card_type | 값을 만드는 곳 |
  | --- | --- |
  | `news` | `news.body_status` (`ok` · `failed` · `purged`) |
  | `pdf` | `analyst_reports.body_status` (`pending` · `ok` · `empty` · `unusable` · `failed` · `skipped` · `purged`) |
  | `message` | `telegram_messages.purged_at` 이 있으면 `purged`, 없으면 `ok` (지운 메시지는 `text` 가 NULL) |

### 5-3. 보고서 생성 입력과의 대응 (연결은 생성 담당)

develop 의 `docs/stock_analysis_io.md`(PR #36, 10-27 병합) 입력 기준이다. 연결 코드는 생성 담당이 만든다(전제 P13). `match` → `mention` 이름 변경은 생성 담당이 할 예정이라, 그 문서와 코드에는 아직 `match` 로 남아 있다.

| 생성 입력 칸 | 이 조회 결과에서 |
| --- | --- |
| `messages[].mention = "mentioned"` | 이 종목 판정 중 `path = "company"` 인 사건이 있는 자료 (옛 이름 `match = "direct"`) |
| `messages[].mention = "not_mentioned"` | 그 밖의 `DIRECT`·`INDIRECT_CONTEXT` (industry·relation 경로). 공통 배경 사건만 있는 자료(`card_label = null`)는 연결 쪽이 정한다 |
| (넣지 않음) | `NOT_APPLICABLE`, `UNKNOWN` |
| `channel`·`url`·`datetime_kst`·`text` | `source_card_id` → `telegram_messages` |
| `sector` | `stock_industries` (지금은 `stock_meta.json`. 9절로 합친 뒤 옮긴다) |
| `kind`·`after_prev_close`·`first_seen_kst`·`dup_channels` | 이 설계에 없다. 연결 쪽이 만든다 |

### 예시 (가상의 기사, 가상의 회사)

기준표

- `stock_industries`: A사 — FC-BGA 고사양 / B사 — FC-BGA 중·저사양 / C사 — 일반 PCB (모두 기판 아래)
- `company_relations`: (B사, D사, supplier) — B사는 D사의 공급사 / (A사, B사, competitor)

> ① 중·저사양 FC-BGA 공급 부족이 이어지고 있다. ② B사는 주요 고객 D사에 단가 인상을 통보했다. ③ 미국 금리 인하 기대에 코스피는 1% 올랐다.

① 사건 추출 · ② 표기 연결

| 사건 | scope | role | sentence_indices | mentions | 대상 행 |
| --- | --- | --- | --- | --- | --- |
| 1 | industry | cause | `{1}` | `{중·저사양 FC-BGA}` | `industry_code = fcbga_low_mid` |
| 2 | company | cause | `{2}` | `{B사, D사}` | B사, D사 |
| 3 | macro | cause | `{3}` | `{미국 금리, 코스피}` | 없음 |

③ 후보 · ④ 판정

| 사건 | 종목 | path | label | 근거 |
| --- | --- | --- | --- | --- |
| 1 | B사 | industry | DIRECT | `stock_industries` 의 (B사, FC-BGA 중·저사양) |
| 2 | B사 | company | DIRECT | 직접 언급 |
| 2 | D사 | company | DIRECT | 직접 언급 (B사 → D사 관계로도 걸리지만 위쪽 경로 하나로) |
| 2 | A사 | relation | INDIRECT_CONTEXT | B사의 경쟁사 (`via_stock_code = B사`) |

산업을 "기판" 까지만 나눴다면 사건 1 의 후보는 A·B·C 사 셋이 되고, ④ 가 C사(일반 PCB)를 NOT_APPLICABLE 로 걸러야 한다. 세부 산업이 있으면 후보 단계에서 이미 좁혀진다.

조회 결과 (판정 조건 기본값)

| 종목 | DIRECT | INDIRECT_CONTEXT | 공통 배경 |
| --- | --- | --- | --- |
| A사 | — | 2 | 3 |
| B사 | 1, 2 | — | 3 |
| C사 | — | — | 3 |
| D사 | 2 | — | 3 |

---

## 6. 표기 → 대상 연결 (전제 P4)

- LLM 은 사건마다 기사 속 표기(`mentions`)만 낸다. 코드가 원문에 그 표기가 있는지 검사한다.
- 표기 → 종목코드: 기준 JSON 의 종목 별칭. 표기 → 산업: `industries.aliases`. 표기 → 외부 기업: 기준 JSON 의 외부 기업 별칭(4-9).
- 종목·외부 기업 별칭에는 종류를 둔다. `name`(회사 자신의 이름·약칭·영문명)과 `subsidiary`(비상장 연결 자회사 이름. 예: SK이노베이션 ← "SK온", 삼성전자 ← "삼성디스플레이"·"하만", KB금융 ← "KB증권"·"KB국민카드", 외부 기업 삼성에피스홀딩스 ← "삼성바이오에피스")다.
  - `subsidiary` 별칭으로 연결되면 대상 행(4-5)에 `via_subsidiary` 로 자회사 이름을 남긴다. 판정 입력에는 "자회사 ○○ 언급" 으로 넘긴다. 자회사 소식이 모회사에 직접 해당하는지는 ④ 가 판정한다(DIRECT 가능).
  - 근거: 비상장 연결 자회사는 모회사 연결재무제표에 들어가고 그 사업이 모회사 사업보고서에서 주요 사업으로 확인된다. 지주회사의 사업 자회사(KB국민은행, 포스코 …)도 여기다. 그래서 MVP 에서는 모회사 사업의 일부로 다룬다. 비상장이라는 사실만으로 같다고 보는 것이 아니다. 연결 대상이 아니면 별칭으로 두지 않는다(INDUSTRY_REVIEW 2-3, RELATION_REVIEW 2-1).
  - 자회사 표기로 들어온 출발점의 관계 확장 범위는 5-1 이 정한다.
- 상장 자회사(한화오션, 포스코퓨처엠 …)는 별칭이 아니라 외부 기업이다. 그 소식은 `ownership` 관계로 모회사에 닿고, 판정 상한은 INDIRECT_CONTEXT 다.
- 별칭에 안 걸린 표기는 LLM 에게 종목·산업 코드 목록을 주고 고르게 한다(`linked_by = 'llm_code'`). 산업 표기는 "TV 제조사", "메모리 업체들" 처럼 형태가 다양해서 별칭으로 다 잡히지 않기 때문이다. 목록 밖 코드를 내면 버린다.
- 그래도 안 걸리면 대상 행을 만들지 않는다. 사람이 보고 별칭을 더한 뒤 재분류한다.
- 임베딩으로 후보 산업을 찾는 단계는 두지 않는다. 종목 30개·산업 70여 개라 사전과 코드 목록으로 충분하다. 산업 목록이 수백 개로 커지면 다시 본다.

## 7. 기준 JSON 과 버전

- 종목·별칭·산업·외부 기업·종목–산업 연결·기업–기업 관계를 담은 **기준 JSON 파일 하나**가 원본이다. DB 의 `industries`·`stock_industries`·`external_companies`·`company_relations` 는 이 파일에서 넣는다. 종목·외부 기업 별칭은 JSON 에만 둔다(전제 P6).
- 생성 담당의 `stock_meta.json`(업종 라벨)과 같은 정보를 두 곳에 두지 않는다. 9절로 합친 뒤에는 기준 JSON 이 원본이고, 생성 쪽은 `stock_industries` 를 읽도록 옮긴다(생성 담당과 맞출 것).
- 버전 = 파일 내용의 sha256. `basis_version` 칼럼(varchar(64))에 이 값을 적는다.
- **버전마다 파일을 새로 만들고, 만든 파일은 고치지 않는다.** 예: `ai/app/data/classification_basis/<날짜>.json`. 이 파일들이 예전 기준의 기록이다.
- DB 의 기준표에는 지금 기준만 있다. 예전 회차가 어떤 기준으로 연결됐는지는 회차의 `basis_version` 으로 해당 파일을 찾아 본다.
- 기준을 바꿨을 때 예전 회차의 대상 행(4-5)은 그대로 둔다. 새 기준으로 다시 연결하려면 재분류한다(새 회차).
- 후보 모으기(5-1)는 **분류할 때의 기준**으로 한다. 판정이 그 후보 위에 저장되므로, 기준을 바꾼 뒤 새 기준의 후보·판정을 쓰려면 재분류한다(새 회차). 조회(5-2)는 저장된 판정만 읽고 기준표를 다시 보지 않는다. 이미 만든 보고서가 무엇을 썼는지는 보고서 쪽이 저장한다(생성 담당과 맞출 것).

## 8. 구현·마이그레이션 메모

- 다음 ai 리비전으로 한 번에 만든다. `0025` 는 `dart_disclosures`, `0026` 은 공시 카드 연결이 쓰므로 그 뒤 번호다. 정확한 번호는 구현할 때 develop 기준으로 정한다.
- 기존 표의 칼럼은 바꾸지 않는다.
- `classification_runs` 에 행이 있으면 downgrade 를 막는다. 분류 결과는 다시 만들려면 LLM 비용이 들고, 원문이 지워졌으면 다시 만들 수 없다(전제 P9). 기준표(`industries`·`stock_industries`·`external_companies`·`company_relations`)는 JSON 에서 다시 넣으면 되므로 막지 않는다.
- 문장 분리 코드(`app/services/news_link/sentence.py`)에는 지금 버전 값이 없다. 분리 규칙을 **버전별 함수로 남긴다.**
  - 예: `SPLITTERS = {"v1": split_sentences_v1, "v2": split_sentences_v2}`, 새 분류는 최신 버전을 쓴다.
  - 예전 회차의 문장을 꺼낼 때는 회차의 `splitter_version` 으로 함수를 골라 부른다. 버전 값만 올리고 기존 함수를 고치면 예전 회차의 "15번 문장" 을 다시 찾을 수 없다.
  - **한 번 배포한 버전의 함수는 고치지 않는다.** 고쳐야 하면 새 버전을 만든다. 버전마다 고정 입력·기대 출력 테스트를 둬서 실수로 바뀌면 깨지게 한다.
  - `classification_runs` 에 그 버전의 회차가 남아 있는 동안은 함수를 지우지 않는다.
- `raw_response`·`reason` 에 원문 일부가 들어갈 수 있다. 보관 정책 삭제(`python -m app.collectors.sources purge`) 범위에 넣을지 정한다 → 11절.
- `dart_disclosures` 는 `0026` 부터 `source_card` 에 연결된다(`card_type = 'disclosure'`). 본문이 없어 제목만으로 분류할지, 분류 대상에 넣을지는 별도로 정한다.

---

## 9. 산업 목록 초안

맨 위는 KRX 업종(BE `MVP_STOCKS` 의 `sector` 값)이다. 그 아래는 [INDUSTRY_REVIEW.md](INDUSTRY_REVIEW.md) 2-6 계층(10-28)을 옮겼다.
노드 규칙·회사별 연결은 INDUSTRY_REVIEW 2-2 ~ 2-6·3절이 원본이다. 이 표는 `industries` 에 넣을 모양만 보인다.
**아직 구현 전이라 코드를 바꿔도 된다.** 기준 JSON 을 처음 넣은 뒤부터는 바꾸지 않는다(4-1).

| code | name | parent_code | 조회어 예시 (`aliases`) |
| --- | --- | --- | --- |
| `krx_electronics` | 전기전자 | — | |
| `semiconductor` | 반도체 | `krx_electronics` | 반도체 업황, 반도체주 |
| `memory` | 메모리반도체 | `semiconductor` | D램, DRAM, 낸드, NAND, HBM |
| `foundry` | 파운드리·시스템반도체 | `semiconductor` | 파운드리, 위탁생산, 시스템LSI, 시스템반도체 |
| `display` | 디스플레이 패널 | `krx_electronics` | OLED, 디스플레이 |
| `smartphone` | 스마트폰 | `krx_electronics` | 스마트폰, 폴더블 |
| `home_appliance` | 가전·TV | `krx_electronics` | 가전, TV, 생활가전 |
| `hvac` | 냉난방공조(HVAC) | `krx_electronics` | HVAC, 공조, 데이터센터 냉각, 칠러 |
| `electronic_parts` | 전자부품 | `krx_electronics` | 전자부품 |
| `mlcc` | MLCC | `electronic_parts` | MLCC, 적층세라믹콘덴서 |
| `camera_module` | 카메라모듈 | `electronic_parts` | 카메라모듈 |
| `pkg_substrate` | 반도체 패키지 기판 | `electronic_parts` | FC-BGA, 패키지 기판, 반도체 기판 |
| `electronic_materials` | 전자재료 | `krx_electronics` | 전자재료, 반도체 소재 |
| `battery` | 2차전지 | `krx_electronics` | 2차전지, 이차전지, 배터리 |
| `ess` | 전력저장장치(ESS) | `krx_electronics` | ESS, 에너지저장장치, PCS |
| `power_grid` | 전력설비 | `krx_electronics` | 변압기, 전력기기, 배전반 |
| `factory_automation` | 산업자동화 | `krx_electronics` | PLC, 산업자동화 |
| `krx_transport_equip` | 운송장비·부품 | — | |
| `auto` | 자동차 | `krx_transport_equip` | 자동차 업황, 자동차 관세 |
| `vehicle` | 완성차 | `auto` | 완성차, 전기차 판매, 하이브리드, PBV |
| `auto_parts` | 자동차부품 | `auto` | 자동차부품, 모듈, A/S 부품 |
| `auto_electronics` | 전장 | `auto` | 전장, 인포테인먼트, 차량용 디스플레이 |
| `shipbuilding` | 조선 | `krx_transport_equip` | 조선, 수주, LNG선, 컨테이너선 발주, 함정, 잠수함, 해양플랜트 |
| `defense` | 방위산업 | `krx_transport_equip` | 방산, K9, 방산 수출 |
| `aerospace` | 우주항공 | `krx_transport_equip` | 우주, 발사체, 항공엔진 |
| `krx_machinery` | 기계·장비 | — | |
| `power_equipment` | 발전설비 | `krx_machinery` | 발전설비 |
| `nuclear_equipment` | 원전설비 | `power_equipment` | 원전, 원자력, SMR |
| `gas_turbine` | 가스터빈 | `power_equipment` | 가스터빈 |
| `marine_engine` | 선박엔진 | `krx_machinery` | 선박엔진, 엔진기계 |
| `robot` | 로봇 | `krx_machinery` | 로봇, 휴머노이드, 액추에이터 |
| `krx_pharma` | 제약 | — | |
| `biopharma` | 바이오 | `krx_pharma` | 바이오, 바이오의약품 |
| `bio_cdmo` | 바이오 CDMO | `biopharma` | CDMO, CMO, 위탁개발생산, 위탁생산 |
| `biosimilar` | 바이오시밀러 | `biopharma` | 바이오시밀러 |
| `krx_finance` | 금융 | — | |
| `bank` | 은행 | `krx_finance` | 은행, 순이자마진, NIM, 예대마진 |
| `financial_holding` | 금융지주 | `krx_finance` | 금융지주, 밸류업, 주주환원 |
| `holding` | 지주·투자 | `krx_finance` | 지주사, 지주회사 |
| `securities` | 증권 | `krx_finance` | 증권사, 브로커리지, IB |
| `card` | 카드 | `krx_finance` | 카드사, 가맹점 수수료, 카드론 |
| `payment` | 간편결제 | `krx_finance` | 간편결제, 전자결제 |
| `krx_insurance` | 보험 | — | |
| `life_insurance` | 생명보험 | `krx_insurance` | 생명보험, 생보사 |
| `non_life_insurance` | 손해보험 | `krx_insurance` | 손해보험, 손보사, 자동차보험 |
| `krx_construction` | 건설 | — | |
| `construction` | 건설 | `krx_construction` | 건설, 수주, 해외건설 |
| `real_estate` | 부동산 | `krx_construction` | 부동산 개발, 임대 |
| `krx_distribution` | 유통 | — | |
| `trading` | 상사 | `krx_distribution` | 종합상사, 트레이딩 |
| `fashion` | 패션 | `krx_distribution` | 패션 |
| `leisure` | 레저 | `krx_distribution` | 리조트, 테마파크, 레저 |
| `food_service` | 식자재·급식 | `krx_distribution` | 단체급식, 식자재 |
| `krx_it_service` | IT 서비스 | — | |
| `internet` | 인터넷 | `krx_it_service` | 포털, 검색, 광고, 커머스, 웹툰, 클라우드 |
| `it_service` | IT서비스 | `krx_it_service` | IT서비스, SI, AI 전환 |
| `krx_chemical` | 화학 | — | |
| `refining` | 정유 | `krx_chemical` | 정유, 정제마진 |
| `petrochemical` | 석유화학 | `krx_chemical` | 석유화학, 에틸렌, 나프타 |
| `krx_utilities` | 전기·가스 ※ BE `sector` 값 확인 | — | |
| `lng_power` | LNG·발전 | `krx_utilities` | LNG, 도시가스, 민자발전 |
| `krx_metal` | 금속 | — | |
| `steel` | 철강 | `krx_metal` | 철강, 열연, 냉연 |
| `battery_materials` | 이차전지 소재 | `krx_metal` | 이차전지 소재, 배터리 소재 |
| `lithium` | 리튬 | `battery_materials` | 리튬, 수산화리튬 |
| `cathode_anode` | 양극재·음극재 | `battery_materials` | 양극재, 음극재 |
| `krx_transport` | 운송·창고 | — | |
| `shipping` | 해운 | `krx_transport` | 해운, 운임, SCFI, 컨테이너선 운임, 벌크선, BDI |
| `krx_food` | 음식료·담배 | — | |
| `tobacco` | 담배 | `krx_food` | 담배, 궐련, 궐련형 전자담배, NGP |
| `health_food` | 건강기능식품 | `krx_food` | 건강기능식품, 홍삼 |

10-27 안에서 없앤 코드: `cooling_system`(→ `hvac`), `nuclear_power`(→ `nuclear_equipment`), `food`(→ `tobacco`·`health_food`). 아직 DB 에 넣기 전이라 `retired_at` 없이 목록에서 뺀다.

- **조회어가 겹치는 곳.** "수주" 는 조선·건설에, "LNG" 는 LNG·발전과 조선("LNG선")에, "컨테이너선" 은 조선(발주)과 해운(운임)에 걸린다. 표기 연결(6절)은 긴 표기를 먼저 맞추고, 짧고 겹치는 조회어("수주")는 기준 JSON 에 넣기 전에 뺄지 정한다. 겹친 채로 두면 두 산업 모두 후보가 되고 ④ 가 거른다.
- `auto`·`biopharma`·`battery_materials` 처럼 아래 단계가 있는 산업에는 종목을 직접 연결하지 않는다(4-2, 가장 작은 분류에 연결).

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
| 2 | ~~산업 표기 연결 방법~~ | | **정함 (10-27)**: 별칭 사전 → LLM 코드 선택 → 미연결 기록. 임베딩 없음 (6절) |
| 3 | ~~자회사 지분으로 산업 연결~~ | | **정함 (10-28)**: 비상장 자회사 사업은 모회사 사업보고서에서 주요 사업으로 확인되면 `subsidiary`, 상장사 경유는 명시 목록만 `stake`(최대 INDIRECT_CONTEXT). INDUSTRY_REVIEW 2-3·2-4, 4-2 |
| 4 | ~~분류 대상 종목·우선주 포함~~ | | **정함 (10-28)**: `stock_meta.json` 30종목. 삼성전자우 없음, LG전자 포함. 백엔드 상위 30과 3개가 다르다(백엔드에만: 삼성전자우·효성중공업·한미반도체 / stock_meta 에만: 메리츠금융지주·HMM·KT&G) |
| 5 | ~~바이오 분리~~ | | **정함 (10-28)**: `bio_cdmo` · `biosimilar` 로 나눈다(9절) |
| 6 | ~~`macro` 경로를 생성 입력에 넘기는 법~~ | | **정함 (10-27)**: 조회 결과에 `path = macro` 로 그대로 낸다. 생성 입력으로 바꾸는 건 연결 담당(생성 담당)이 정한다 (5-3) |
| 7 | `role` 최종안, `analyst_view` 를 원인으로 볼지 | 전제 P10 | 실험 E2 결과 보고 결정 |
| 8 | 전망(`outlook`) 사건을 후보로 넘길지 | 넘김 / 뺌 | 넘기되 role 로 구분 |
| 9 | `raw_response`·`judge_raw_response`·`reason` 을 보관 정책 삭제 범위에 넣을지 | 넣음 / 안 넣음 | 넣음(원문 일부가 섞일 수 있다) |
| 10 | ~~공시를 분류 대상에 넣을지~~ | | **정함 (10-27)**: 처음에는 넣지 않는다. 종목은 이미 `dart_stock_code` 로 연결돼 있고 제목뿐이라 관계·산업으로 넓힐 근거가 부족하다 |
| 11 | ~~마이그레이션 시점~~ | | **정함 (10-30)**: 지금 만든다(`0027_classification`). 수집 → 분류 → 조회를 먼저 이어 놓고 모델·프롬프트를 시험하기로 했다. 사건 형식이 바뀌면 새 리비전으로 고친다 |
| 12 | PDF 본문(`analyst_reports.body_text`)이 없을 때 요약(`summary_text`)으로 분류할지 | 허용 / 불허 | 허용하되 `purged` 는 제외, 회차에 어느 글로 분류했는지 기록. 뉴스 요약은 지금처럼 쓰지 않는다(4-3) |
| 13 | 업종 지도 회사별 연결 | — | 규칙과 계층은 정함 (10-28, INDUSTRY_REVIEW 2절). 남은 일: 3절 `†` 항목을 DART 사업보고서의 주요 제품·서비스와 부문 정보로 확인하고 "사실 확인"·"채택" 칸을 채운다. 다 채워지면 기준 JSON 첫 버전을 만든다 |
| 14 | 관련성 판정이 두 곳에서 일어남 | 분류 ④ 결과를 `mention`(옛 이름 `match`)으로 쓰고 생성 쪽 `issue_trace.relation` 은 점검용 / 생성 쪽에 맡김 | 생성 담당과 결정. 이 설계의 표는 어느 쪽이든 그대로다 |
| 15 | ~~`company_relations` 데이터를 누가 어떤 근거로 채울지~~ | | **정함 (10-28)**: 넣는 기준과 시작 목록은 RELATION_REVIEW 2~4절. 검색·공시로 "사실 확인"(근거·기준일·`evidence`)과 "채택" 칸을 채운 뒤 기준 JSON 에 넣는다 |
| 16 | `ownership` 관계와 `stake` 연결도 최대 INDIRECT_CONTEXT 로 둘지 | 그대로 / DIRECT 허용 | 그대로 시작. SK하이닉스 소식 → SK스퀘어 처럼 주가가 거의 같이 움직이는 경우를 평가에서 보고 판단. 바꾸면 둘을 같이 바꾼다(같은 지분을 산업 기사·회사 기사에서 다르게 보지 않게) |
| 17 | 판정(④) 평가 방법 | — | 사람이 만든 정답 표본으로 NOT_APPLICABLE·UNKNOWN 비율과 오판을 본다. 표본 범위는 미정 |
| 18 | `stake` 명시 목록을 넓힐지 | 4개 유지 / 두산밥캣·SK 상장 자회사 등 추가 | 4개로 시작(INDUSTRY_REVIEW 2-4). 17번 평가에서 산업 기사로 놓친 지분 노출이 보이면 더한다 |
| 19 | 조회어가 여러 산업에 겹칠 때 ("수주", "LNG") | 둘 다 후보 / 짧은 조회어 빼기 | 긴 표기 먼저 맞추고, 겹치는 짧은 조회어는 기준 JSON 만들 때 뺄지 정한다(9절) |
| 20 | `krx_utilities`(LNG·발전의 맨 위) 이름 | — | BE `MVP_STOCKS` 의 `sector` 값과 글자까지 맞춘다. 30종목 중 이 업종인 종목이 없으므로 BE 100종목 목록에서 확인 |
| 21 | 외부 기업에서 출발한 후보가 너무 많아질 때 | 그대로 / 관계의 `industry_code` 와 사건 산업이 맞을 때만 넘김 | 그대로 시작. 엔비디아·애플처럼 자주 나오는 기업은 관계 없는 소식(게임용 GPU 출시 등)에도 공급사를 후보로 만든다. ④ 가 NOT_APPLICABLE 로 거르는 비율을 17번 평가에서 보고, 높으면 산업 일치 조건을 코드(③)로 옮긴다 |
| 22 | `reported` 관계로 들어온 후보의 판정 | 다른 관계와 같음 / 더 보수적으로 | 같게 시작. 판정 입력에 "보도 근거" 를 넘기고, 평가에서 오판이 많으면 프롬프트 기준을 바꾼다 |
| 23 | 관계 종류를 늘릴지 (합작 `jv`, 라이선스 등) | 3개 유지 / 추가 | 3개로 시작(4-7). 합작은 `supplier`·`ownership` + `note` |
| 24 | `agreement`(협의·개발) 단계 관계로 후보를 만들지 | 만듦 / 뺌 | 만들고 판정에 단계를 넘긴다(4-7). 평가에서 NOT_APPLICABLE 비율이 높으면 코드(③)에서 뺀다 |
| 25 | 자회사 표기 출발점의 관계 확장 범위 규칙(5-1)이 너무 좁거나 넓은지 | 지금 규칙 / 자회사 실제 당사자만 / 제한 없음 | 지금 규칙으로 시작. 공급·경쟁은 실제 당사자 일치 또는 자회사 경유 산업 일치, 지분은 제한 없음(4차) |
| 26 | 합작법인 이름(Ultium Cells, HLI Green Power)이 기사에 나올 때 연결 | 연결 안 함(미연결 기록) / 출자 회사 별칭으로 / 외부 기업으로 | 연결 안 함으로 시작. 실제 당사자 칸(4-7)에만 기록. 미연결 기록에 자주 나오면 회계처리를 확인해 정한다(RELATION_REVIEW 5절 6번) |

---

## 12. 변경 이력

### 2026-10-30 — 구현

수집 → 분류 → 조회를 먼저 이어 놓고 모델·프롬프트를 시험하기로 해서(11절 11번) 표 8개를 만들었다. 분류·생성의 DIRECT 뜻 차이와 관련성 판정 중복(11절 14번)은 10-29 회의에서 "각자 써 보고 충돌이 크면 다시 회의" 로 정했다 — 이 문서의 판정 정의는 그대로다.

| 계기 | 반영 |
| --- | --- |
| 10-29 멘토링: 코드 경로가 달라지는 값만 칸, 나머지는 note | `company_relations` 를 (from, to, 종류, 산업) 한 행으로. `product_scope`·`from_/to_via_company`·`stage`·`evidence`·`source_as_of`·`period_from/to` 를 없애고 `note` 로(4-7). 고유 키에 `product_scope` 대신 `industry_code` |
| 실제 당사자가 칸에서 빠짐 | 자회사 표기 출발점의 범위 제한은 "자회사 경유 산업 일치" 만 본다. 외부 기업의 자회사 표기는 제한하지 않는다(5-1) |
| 근거 수준·단계가 칸에서 빠짐 | 대표 관계 순서는 "출발점이 종목인 관계 → 기준 JSON 순서" 만(5-1). 판정 입력에는 `note` 가 그대로 간다(4-8) |
| 10-21 추출 실험: `happened`·`expected` 를 모델이 role 칸에 넣음 | `tense` 값을 `past`·`future` 로(4-4). 실험 브랜치에서 바꿨던 것을 이 문서에 옮겼다 |
| 단계(추출·코드 선택·판정)마다 모델을 바꿔 시험 | 회차의 `model` 은 ① 추출 모델, 단계별 모델·비용은 `usage` 에(4-3). 칼럼은 나누지 않았다 |
| ② LLM 코드 선택의 선택지 | 맨 위 산업(KRX 업종)은 목록에서 뺀다. 업종 전체로 퍼지는 연결을 막는다(6절) |
| 기준 JSON 첫 버전 | INDUSTRY_REVIEW 3절·RELATION_REVIEW 3·4절 10-28 수정안을 사실 확인 전 초안으로 넣었다(`2026-10-30-draft.json`). † 항목은 넣고, 채택 칸이 보류인 관계(19·30·33·57번)와 법인명 미확인 리튬 연결은 뺐다. 겹치는 조회어 "수주"·"위탁생산" 은 뺐다(11절 19번) |

4절의 제약은 0027 리비전으로 PostgreSQL 16 에서 실행해 확인했다(tests/test_classification_repository_db.py — 관계 경로 DIRECT 거부, 배열 안 NULL 거부, 관계 고유 키, 분류 기록이 있는 자료 삭제 거부, downgrade 거부).

### 2026-10-28 (4차) — 기업 관계 전체 대조 검토 반영

외부 검토가 [RELATION_REVIEW.md](RELATION_REVIEW.md) 56개 행 전체를 공개 자료와 대조했다. 데이터(출처·기준일·범위·단계)는 그 문서에, 설계 지적은 여기에 반영했다.

| 계기 | 반영 |
| --- | --- |
| 대표 경로가 `industry` 면 `relation_refs` 를 비우게 돼 관계 근거가 사라진다 ("엔비디아 HBM 주문 확대" → 삼성전자) | `relation_refs` 를 경로와 상관없이 보존. CHECK 를 "relation 경로면 하나 이상" 으로 완화(4-8, 5-1) |
| 자회사 표기 출발점의 범위 제한이 지분 관계(산업 비어 있음)를 항상 거른다 ("삼성바이오에피스" → 삼성물산·삼성전자) | 범위 제한은 `supplier`·`competitor` 에만. `ownership` 은 제한 없이 타고 판정 상한만(5-1) |
| 실제 당사자를 자회사 별칭에 있는 이름으로만 받아 합작법인을 적을 수 없다 (Ultium Cells, HLI Green Power) | `from_/to_via_company` 를 기록으로, 별칭 자격과 분리(4-7). 합작법인 표기 연결은 11절 26번 |
| `contracted = 공급 전` 은 확인한 것보다 강한 표현 | `stage` 를 "확인된 수준" 으로 재정의(4-7) |
| 지분 범위에 비율을 넣으면 비율이 바뀔 때 다른 관계가 된다 (`product_scope` 는 고유 키) | `ownership` 은 `product_scope = '지분'`, `evidence = 'official'` 을 CHECK 로(4-7) |
| 그룹 보유와 법인 보유가 섞인다 (현대차–보스턴다이내믹스, 한화에어로스페이스–한화오션) | `ownership` 의 from 은 실제 보유 법인. 확인 못 하면 넣지 않음(4-7) |

4-7·4-8 의 바뀐 제약은 아직 PostgreSQL 에서 실행해 보지 않았다.

### 2026-10-28 (3차) — 기업 관계 외부 검토 반영

검색 기반 외부 검토가 [RELATION_REVIEW.md](RELATION_REVIEW.md) 를 공식 자료와 대조했다. 데이터 수정은 그 문서에, 표 구조에 영향을 주는 지적은 여기에 반영했다.

| 계기 | 반영 |
| --- | --- |
| 삼성에피스홀딩스 종목코드 `0126Z0` — 숫자 6자리 검사가 거부한다 | `external_companies.stock_code` CHECK 를 `^[0-9A-Z]{6}$` 로(4-9). 고유 식 인덱스 설명도 고침(4-7) |
| 같은 공급 관계 안의 제품(삼성전자→애플 OLED·메모리)을 따로 둘 수 없다 | 한 행 = 제품·계약 범위 하나. `subject` → `product_scope`(NN), 고유 키에 포함(4-7) |
| 공식 자료라고 공급 중은 아니다 (삼성SDI–GM 공동개발) | `stage`(agreement / contracted / active) 추가. `evidence` 는 자료 출처만 말한다(4-7) |
| 모회사로 연결해도 실제 거래 주체를 잃으면 안 된다 | 관계에 `from_via_company`·`to_via_company`, 표기 연결에 `via_subsidiary`(4-5) |
| 자회사 표기(하만)로 들어온 모회사(삼성전자)가 무관한 관계(엔비디아 HBM)로 퍼진다 | 자회사 표기 출발점은 실제 당사자 일치 또는 자회사 경유 산업 일치 관계로만 넓힘(5-1) |
| 한 종목이 공급사이자 경쟁사로 걸리면 관계 하나만 판정에 넘어간다 | 후보는 합치고 관계는 전부 `relation_refs` 로(4-8, 5-1) |
| 외부 기업의 자회사(삼성바이오에피스) 표기 규칙이 없다 | 외부 기업에도 `subsidiary` 별칭(6절, 4-9) |
| 경쟁 관계를 반사이익으로 가정 | 영향 방향을 정하지 않음(4-7, 4-8 판정 기준) |
| 계약 기간이 공개된 관계가 있다 (삼성SDI→현대차 2026~2032) | `period_from`·`period_to` 추가. 공개된 경우만 채움(전제 P12 의 "근거 있게 채울 수 있을 때") |
| "투자 경로가 모회사뿐" 이라는 자회사 근거 | 연결 대상 여부와 모회사 사업 관련성으로 고침(6절, INDUSTRY_REVIEW 2-3) |

4-5·4-7·4-8·4-9 의 새 제약은 아직 PostgreSQL 에서 실행해 보지 않았다.

### 2026-10-28 (2차) — 기업 관계 설계: 외부 기업 추가

| 계기 | 반영 |
| --- | --- |
| 엔비디아·TSMC 같은 30종목 밖 기업 소식이 30종목에 닿지 못함. 표기 연결도, 관계의 출발점도 안 됨 | `external_companies` 기준표 추가(4-9). 전제 P15. 외부 기업은 후보가 아니라 출발점 |
| 관계 양 끝이 종목코드만 받음 | `company_relations` 양 끝을 종목·외부 기업 중 하나로(`from_/to_stock_code`, `from_/to_external_code`). 한쪽은 반드시 30종목. NULL 이 섞여 고유 제약은 식 인덱스로(4-7) |
| 관계마다 무엇에 대한 관계인지, 근거가 얼마나 단단한지 없음 | `industry_code`·`subject`·`evidence`(official / reported)·`source_as_of` 추가. 중요도·confidence 는 여전히 두지 않음(전제 P12) |
| 외부 기업 표기를 사건에 연결해야 함 | `classification_event_entities.external_code` 추가(4-5). 판정 표에 `via_external_code` 추가, relation 경로 CHECK 수정(4-8) |
| relation 경로 출발점 | 사건에 직접 언급된 종목 **또는 외부 기업**. 외부 기업은 scope 와 상관없이 출발점. 여러 관계로 걸리면 종목 출발·official 우선(5-1) |
| 비상장 자회사(SK온, 삼성디스플레이 …) 이름이 나온 기사 | 외부 기업이 아니라 모회사 별칭(종류 `subsidiary`)으로. INDUSTRY_REVIEW 2-3 과 같은 논리라 DIRECT 가능. 상장 자회사는 외부 기업 + `ownership`, 최대 INDIRECT_CONTEXT(6절) |
| `stake` 와 `ownership` 짝 검사 | 경유 상장사가 30종목 밖이면 외부 기업으로 등록하고 그쪽 `ownership` 과 짝을 맞춤(4-2) |
| 데이터 시작점 | 외부 기업 14개·관계 49개 초안. 넣는 기준과 함께 RELATION_REVIEW.md 로 따로 둠(이 문서는 표 구조만). 사실 확인·채택 칸은 비움 |

4-5·4-7·4-8·4-9 의 새 제약은 아직 PostgreSQL 에서 실행해 보지 않았다.

### 2026-10-28 — 산업 분류 외부 검토 반영

검색 기반 외부 검토가 30종목 연결을 공식 사업 자료와 대조했다. 그 결과와, 검토를 우리 목적(30종목 중 후보 고르기)에 맞게 거른 결정을 반영했다. 회사별 내용은 [INDUSTRY_REVIEW.md](INDUSTRY_REVIEW.md) 2·3절에 있다.

| 계기 | 반영 |
| --- | --- |
| 검토: 종목마다 연결 범위가 다르다 (메리츠만 자회사 사업, SK스퀘어만 지분, 현대차만 미래 사업) | 공통 기준을 정함. 전제 P14, `stock_industries` 에 `exposure`·`via_company`·`via_stock_code`·`stage`·`supply_role`·`source`·`source_as_of` 추가(4-2) |
| 검토: 연결 경로와 사업 단계는 다른 축이다 | `exposure`(own / subsidiary / stake) 와 `stage`(operating / planned) 를 칼럼으로 나눔. 사건 판정의 `DIRECT` 와 헷갈리지 않게 `direct` 라는 값을 쓰지 않음 |
| 자회사·지분 구분 기준 | 경유 회사가 **상장사인지**로 가름. 비상장 자회사 사업은 모회사 사업처럼, 상장사 경유는 지분 노출로. 연결재무제표 포함 여부는 메모로만 |
| 지분 노출 후보가 DIRECT 로 판정될 수 있음 | 판정에 `direct_allowed` 추가(4-8). relation 경로 전용 CHECK 를 일반화하고, 보정 키 `relation_direct_lowered` → `direct_lowered` |
| 검토: 지분 연결을 기업 관계로만 옮기면 산업 기사에서 모회사 후보가 빠진다 | 둘 다 둔다. `stake` 행과 `ownership` 행의 짝을 기준 JSON 로드 때 검사(4-2). 후보에서 빼지 않고 판정 상한만 둠(5-1) |
| 검토: HBM 은 메모리의 동의어가 아니다 | `aliases` 를 조회어로 정의(4-1). 사건에는 기사 속 표기가 그대로 남는다 |
| 검토: 세분화 제안 다수 (DRAM/NAND, NAVER 사업별, 해운 컨테이너/벌크 …) | 노드 규칙(INDUSTRY_REVIEW 2-2)에 맞는 것만 노드로, 나머지는 조회어로(9절) |
| 검토: KT&G 담배 누락, 두산 "원자력발전", 바이오 미분리 등 | 9절 산업 목록 교체(70여 개). 11절 3·5번 정함, 18~20번 추가 |
| 검토: 사업이 있음을 확인한 것과 연결에 넣기로 한 것은 다르다 | INDUSTRY_REVIEW 3절 표에 "사실 확인"(출처·기준일)과 "채택" 칸을 따로 둠 |

4-2·4-8 의 새 제약은 아직 PostgreSQL 에서 실행해 보지 않았다.

### 2026-10-27 — 멘토링(기업 관계·산업 적용 판정)과 생성 쪽 입력(PR #36) 반영

| 계기 | 반영 |
| --- | --- |
| 멘토: 관계는 근거가 아니라 후보 생성기로 쓰고, 관련성은 기사에서 다시 판정 | 전제 P11 추가, P4 수정. ③ 후보 모으기 → ④ 판정 단계(3-2, 5-1) |
| 멘토: 소속(belongs_to)과 적용(affects)을 분리, DIRECT / INDIRECT_CONTEXT / NOT_APPLICABLE / UNKNOWN | `classification_event_applicability` 추가(4-8). 2절의 "관련성은 저장하지 않고 경로로 대신한다" 를 뒤집음 |
| 멘토: 관계에 종류·방향·근거, 1-hop 까지, 관계 종류별 전달 조건 | `company_relations` 추가(4-7), 전제 P12. 종류별 기준은 ④ 프롬프트에, 코드 규칙은 두 개(price_move 는 관계로 안 넘김, relation 경로는 DIRECT 불가) |
| 멘토: 산업 → 세부 산업 → 제품으로 노출 정보 구체화 | 산업 계층에 세부 산업 단계 추가(9절). 판정 입력에 넣어 LLM 이 회사 사업을 짐작하지 않게 함 |
| 멘토: 사전 → 임베딩 → 의미 판정 | 사전 → LLM 코드 선택 → 미연결 기록. 임베딩은 종목·산업 수가 작아 뺌(6절) |
| PR #36: 생성 입력은 메시지 단위 `match`(direct / indirect) | 조회 결과에 자료 단위 `card_label` 추가, 대응표(5-2, 5-3). 연결은 생성 담당(전제 P13) |
| PR #36: 생성 쪽에 업종 라벨(`stock_meta.json`)이 따로 있음 | 두 벌을 합쳐 9절 산업 목록으로. 종목마다 더 자세한 쪽을 받음. 검증은 INDUSTRY_REVIEW |
| 인과 판정(사건이 주가를 움직였나)의 위치 | 이 설계 범위 밖으로 명시(머리말). PR #36 의 생성 쪽 러너가 이미 층·strength·판정을 규칙으로 다시 계산한다 |
| 저장 전 보정 (10-28) | ④ 출력을 코드가 보정하는 규칙과 회차의 `judge_fixes` 칼럼 추가(4-3, 4-8) |
| 분류 대상 종목 (10-28) | `stock_meta.json` 30종목으로 확정. 백엔드 100개 목록은 바꾸지 않는다(2절, 11절 4번) |
| 자체 점검 | `linked_by` 에 `llm_code` 추가, 회차에 판정 프롬프트·응답 칼럼 추가(4-3), `source_card_stocks` 에는 DIRECT 만(4-6), 형제 세부 산업으로 넓히지 않음(5-1), 예시를 FC-BGA 로 바꿈 |

10-09 의 PostgreSQL 실행 확인은 표 5개 기준이다. 새 표 2개(4-7, 4-8)의 제약은 아직 실행해 보지 않았다.

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
