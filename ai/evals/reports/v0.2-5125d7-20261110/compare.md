# v0.2 실행 vs rescore-v0.1

칸 순서: 판정 일치 move·relative(3회 중), 규칙 A 위반, gold 밖 link, 대조 link, 시황 msg link, 과장 후보, 누락 후보, 3회 결론 일치, 정형 보고서 수, verify 실패 수, 비용(₩). 값은 `이전→지금`, 같으면 하나만.

## A

| 케이스 | 3회 판정(지금) | move_match | relative_match | rule_a_violations | spurious_candidates | contrast_links | recap_msg_links | overclaim_candidates | omission_candidates | same_conclusion_runs | skipped_llm | verify_failed | cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| c01_000660_2026-10-28 | explained/explained · explained/explained · explained/explained | 3 | 3 | 0 | 2→1 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 48.21→33.84 |
| c02_005930_2026-10-29 | explained/explained · explained/explained · explained/explained | 0 | 0 | 6→5 | 0 | 0 | 0 | 6→5 | 0 | 3→2 | 0 | 0 | 32.72→32.97 |
| c03_000660_2026-10-23 | explained/explained · explained/explained · explained/explained | 3 | 3 | 2→3 | 3→1 | 0 | 0 | 2→3 | 0 | 1→2 | 0 | 0 | 40.11→32.21 |
| c04_000660_2026-10-26 | no_clear_cause/explained · no_clear_cause/partially_explained · no_clear_cause/explained | 3 | 0→1 | 2→3 | 0 | 0 | 0 | 2→3 | 0 | 2 | 0 | 0 | 30.52→32.23 |
| c05_009150_2026-10-30 | explained/explained · explained/no_clear_cause · explained/explained | 0 | 0→1 | 3 | 0 | 0 | 0 | 3 | 0 | 3→2 | 0 | 0 | 23.85→22.89 |
| c06_267250_2026-10-28 | partially_explained/no_clear_cause · partially_explained/no_clear_cause · partially_explained/no_clear_cause | 0 | 3 | 3 | 0 | 0 | 0 | 3 | 0 | 3 | 0 | 0 | 14.95→25.2 |
| c07_005930_2026-10-26 | explained/no_clear_cause · explained/no_clear_cause · explained/no_clear_cause | 0 | 3 | 0 | 0 | 0 | 4→5 | 0 | 0 | 2 | 0 | 0 | 28.02→38.6 |
| c08_034220_2026-10-22 | partially_explained/explained · partially_explained/explained · partially_explained/no_clear_cause | 0 | 1 | 6 | 0 | 0 | 0 | 6 | 0 | 2 | 0 | 0 | 27.9→25.69 |
| c09_009150_2026-10-28 | explained/explained · explained/explained · explained/explained | 3 | 3 | 0 | 1→0 | 0 | 3 | 0 | 0 | 2→3 | 0 | 0 | 36.86→27.35 |
| c10_011070_2026-10-27 | no_clear_cause/no_clear_cause · no_clear_cause/no_clear_cause · no_clear_cause/no_clear_cause | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 13.63→14.69 |

합계: reports 30, verdict_match_move 15, verdict_match_relative 19→21, rule_a_violations 22→23, spurious_candidates 6→2, contrast_links 0, recap_msg_links 7→8, overclaim_candidates 22→23, omission_candidates 0, cases_all_3_same_conclusion 4→3, skipped_llm 0, injected_cited 0, recap_cited 1→0, cost 296.77→285.67

## B

| 케이스 | 3회 판정(지금) | move_match | relative_match | rule_a_violations | spurious_candidates | contrast_links | recap_msg_links | overclaim_candidates | omission_candidates | same_conclusion_runs | skipped_llm | verify_failed | cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| b01_034730_2026-11-05 | partially_explained/explained · no_clear_cause/no_clear_cause · partially_explained/explained | 3→1 | 3→1 | 0→2 | 0 | 0 | 0 | 0→2 | 0 | 3→2 | 0 | 0 | 16.72→28.14 |
| b04_086790_2026-11-05 | no_clear_cause/no_clear_cause · no_clear_cause/no_clear_cause · no_clear_cause/no_clear_cause | 0→3 | 2→3 | 0 | 3→0 | 0 | 0 | 0 | 0 | 2→3 | 0 | 0 | 8.97→7.13 |
| b05_000810_2026-11-05 | no_clear_cause/no_clear_cause · no_clear_cause/no_clear_cause · no_clear_cause/no_clear_cause | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 3 | 0 | 0.0 |

합계: reports 9, verdict_match_move 6→7, verdict_match_relative 8→7, rule_a_violations 0→2, spurious_candidates 3→0, contrast_links 0, recap_msg_links 0, overclaim_candidates 0→2, omission_candidates 0, cases_all_3_same_conclusion 2, skipped_llm 3, injected_cited 0, recap_cited 0, cost 25.69→35.27

