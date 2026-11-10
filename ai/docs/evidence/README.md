# 실행 증거

테크스펙 「Agentic AI 설계 및 구현 개요」에 적은 동작이 실제로 돌았다는 기록이다.
문서의 각 주장을 아래 파일의 어느 줄에서 확인할 수 있는지 적었다.

- 실행 환경: 운영 DB 의 복사본(테스트용 Postgres)에서, 병합 예정 PR 을 모두 합친 브랜치로 돌렸다.
- 기사 원문은 넣지 않았다(수집 범위의 데이터 이용 제한). 파일에는 자료 ID·회차 번호·라벨·비용만 있다.
- 이 폴더의 채점은 **분류 단계**(자료를 종목에 넘길지)만 본다. 완성된 보고서의 품질은 보고서 eval(`ai/evals/`, `feature/eval_set` 브랜치)에서 따로 잰다.

## 파일

| 파일 | 내용 |
| --- | --- |
| `logs/classify_20261109_rehearsal.log` | 11-09 오전 분류. 하루 비용 상한 ₩300 으로 일부러 낮춰 상한이 실제로 멈추는지 확인 |
| `logs/classify_20261109_pm.log` | 11-09 오후 하루치 분류. 641건 · ₩1,155.10 · failed 2 |
| `logs/classify_20261110.log` | 11-10 하루치 분류. 634건 · ₩1,003.84 · failed 0 |
| `gold_scores.md` | 판정 품질 채점 결과 (날짜별, 방식별) |
| `gold/labels_*.csv` | 채점에 쓴 정답 라벨. 번호·회차·사건·종목·방식별 판정·정답 |

### 로그 한 줄 읽는 법

```
[159/641] 자료 9155    pdf      failed   회차 2282   사건  0  DIRECT -  ₩1.72
          공통 자료 ID 자료 종류  상태      DB 회차 ID  뽑은 사건 수  직접 해당 종목  이 자료의 LLM 비용
```

## 문서 절과 증거

### 4절 · 상황에 따라 경로가 바뀌는 지점

| 상황 | 경로 | 증거 |
| --- | --- | --- |
| 본문 없음 | `no_body`, LLM 안 부름 | `classify_20261109_pm.log` 5줄 |
| 제목·본문 2만 자 초과 | `skipped`, LLM 안 부름 | `classify_20261109_pm.log` 46~47줄 |
| 추출 응답이 허용값 밖 | `failed`, 응답 원문 저장, 다음 자료 계속 | `classify_20261109_pm.log` 193~194줄, 292~293줄 |
| 서버 오류(503)·스트림 끊김 | 기다렸다 다시 보냄 | `classify_20261109_pm.log` 351줄, `classify_20261110.log` 47·48·52줄 |
| 종목당 네이버 뉴스 상한 | 상위 20건만 분류, 원문은 남김 | 각 로그 3줄 |
| 하루 비용 상한 도달 | 새 자료 시작 안 함 | `classify_20261109_rehearsal.log` 198~199줄 |

### 5절 · 상태 관리와 중단 후 재개

| 주장 | 증거 |
| --- | --- |
| 비용 상한으로 멈춘 자료는 회차를 만들지 않는다 | `classify_20261109_rehearsal.log` 198줄: 처리 174건(ok 150 · no_body 6 · skipped 17 · failed 1), budget 607건은 회차 없음 |
| 같은 날 다음 실행은 앞 실행의 비용을 이어받는다 | `classify_20261109_pm.log` 4줄 "오늘 이미 ₩316.49" (= 리허설 비용) |
| 이미 끝난 자료는 다시 분류하지 않는다 | 리허설이 처리한 자료 174건과 오후 실행이 처리한 자료 641건의 겹침 0건 (두 로그의 자료 ID 대조) |
| 실패해도 실행 전체가 멈추지 않는다 | `classify_20261109_pm.log` 680~682줄: failed 2 이후에도 641건 끝까지, 종료 코드 1 로 알림 |

멈춘 자료가 다음 실행에서 다시 골라지는 것은 테스트로 확인한다(아래). 로그만으로는 오후 실행이 처리한 자료 중
어느 것이 "리허설에서 상한으로 멈춘 자료"인지 구분할 수 없다(리허설은 시작하지 않은 자료의 ID 를 찍지 않는다).

### 테스트

| 주장 | 테스트 (`ai/tests/`) |
| --- | --- |
| 비용 상한에 닿으면 새 자료를 시작하지 않는다 | `test_classification_concurrency.py::test_daily_budget_stops_starting_new_cards` |
| 사람이 고른 자료(`--ids`)는 상한·잠금을 받지 않는다 | `test_classification_concurrency.py::test_explicit_ids_ignore_the_daily_budget`, `::test_explicit_ids_do_not_wait_for_the_lock` |
| 고르기부터 저장까지 잠근다 | `test_classification_concurrency.py::test_lock_is_held_from_selection_until_every_card_is_saved` |
| 한 자료의 실패가 다른 자료를 멈추지 않는다 | `test_classification_concurrency.py::test_failed_card_does_not_stop_the_others` |
| 저장 실패는 failed 회차로 남기고 비용도 남긴다 | `test_classification_run.py::test_save_failure_records_failed_run_and_continues`, `test_classification_concurrency.py::test_cost_of_a_card_that_failed_to_save_stays_in_the_total` |
| 회차가 생기면 다음 실행이 고르지 않는다 | `test_classification_repository_db.py::test_save_run_makes_current_and_indexes_direct` (PostgreSQL 필요) |
| 실패·실험 회차는 조회에 쓰는 회차를 바꾸지 않는다 | `test_classification_repository_db.py::test_failed_and_experiment_runs_keep_the_current_one` (PostgreSQL 필요) |
| 응답 형식이 깨지면 failed 로 남기고 원문을 저장한다 | `test_classification_pipeline.py::test_broken_extraction_is_failed_but_kept`, `::test_broken_judgment_is_failed_but_kept` |
| 홍보성 Jev 가 실패해도 회차는 실패가 아니다 | `test_classification_promo.py::test_jev_failure_keeps_run_ok_with_regex_only` |
| 관계 판정 Jev 가 실패하면 회차는 실패다 | `test_classification_judge_relation.py::test_jev_failure_fails_the_judging` |
| 주주 관계뿐이면 묻지 않고 해당 없음 | `test_classification_judge_relation.py::test_owned_only_needs_no_call_at_all` |
| 보고서: 재호출은 한 번뿐이다 | `test_stock_analysis_generate.py::test_invalid_twice_stays_invalid_after_one_retry` |
| 보고서: 근거가 없으면 LLM 없이 정형 보고서 | `test_stock_analysis_generate.py::test_no_direct_or_theme_message_gives_canned_report_without_llm` |
| 보고서: 인용이 두 번 틀리면 그 항목만 뺀다 | `test_stock_analysis_repair.py::test_second_failure_drops_factor_and_marks_event` |

```bash
cd ai && uv run pytest
```

2026-11-11, develop `57ae2dc` 기준: **1596 passed, 107 skipped**.
건너뛴 것은 `MIGRATION_TEST_ADMIN_URL`(테스트용 PostgreSQL)이 있어야 도는 DB 테스트다.
위 표에서는 `test_classification_repository_db.py` 두 줄이 여기에 해당하고, 나머지 15개는 통과했다.

## 정답 라벨은 어떻게 만들었나

`gold/` 의 정답은 **사람이 아니라 외부 모델(ChatGPT)이 매긴 라벨**이다.

1. 우리 모델의 판정은 숨기고, 기사 제목·사건 문장·후보 종목·후보가 된 이유(경로·관계)와 판정 기준 안내서만 줬다. 우리 판정은 따로 둔 대조 파일에만 있었다.
2. 판정에 쓰는 모델(luna · Jev)과 다른 모델이라, 자기 답을 자기가 채점하는 구조는 아니다.
3. 규칙을 고를 때 본 날짜와 확인한 날짜를 나눴다([gold_scores.md](gold_scores.md#원칙-규칙을-정한-데이터와-확인한-데이터를-나눴다)).

**한계**

- 사람 정답이 아니라서 외부 모델의 치우침이 섞일 수 있다. 각 묶음은 한 번씩만 라벨을 매겼다.
- 판정 기준 안내서와 우리 프롬프트가 같은 서비스 기준에서 나왔다. 그 기준에 맞는 방식이 유리할 수 있다.
- 표본을 답이 갈린 칸에서 많이 뽑았다. 점수는 방식끼리의 비교로만 쓴다.
- 정답은 이미 후보가 된 (자료, 종목) 쌍에만 매겼다. 그래서 ② 연결 단계에서 아예 놓친 종목은 이 채점에 잡히지 않는다.
  보고서 eval 의 실서비스 케이스 메모에서 그런 예가 2건 나왔다(장전 코멘트의 "SK에코플랜트" 가 SK 로, 시황 기사의 "NAVER 8.61%" 가 NAVER 로 이어지지 않음).

**아직 하지 않은 것**

- [ ] 사람이 외부 라벨 일부(20~30쌍)를 직접 보고 일치율 확인 — 마감 전 시간이 없어 미실시
