# c08 LG디스플레이 2026-10-22 판단 메모

## e1 실적을 `should` 로 둔 이유
- 사실: 영업이익 2,506억원은 컨센 2,591억원 소폭 하회, 매출도 컨센 하회, 지배주주순이익 7,467억원은 컨센 2,603억원 대폭 상회. 주가 -1.63% 는 대형주(-2.79%)보다 덜 내림(`relative` +1.16, 비교 `덜`).
- 직접 공시지만 방향이 섞여(하회와 상회) 판정이 `none` 이고, 루브릭상 `none` 이면 `must` 는 0개라 `should`. 상한 `coincident`, stance `neutral`.
- 보고서가 한쪽 방향으로 단정하면 과장. `unknowns` 후보: 덜 내린 이유(수급 등), 순이익 상회분이 일회성인지.
- 이전에는 판정을 `partial` 로 보고 `must` 로 뒀으나, 직접 재료의 방향이 혼재면 `no_clear_cause` 로 한다는 기준(rubric §2)으로 바꾸면서 `should` 로 내림.

## 판정 근거(expected_verdict, confidence_level)
move no_clear_cause / relative no_clear_cause, confidence none
- 영업이익·매출 하회는 하락과, 순이익 상회는 덜 내린 것과 각각 방향이 맞지만 서로 섞여 어느 쪽이 주가를 움직였는지 알 수 없음. 루브릭 §2 의 "직접 재료는 있으나 혼재" 는 `no_clear_cause`. move_strength_cap 이 partial 이라 대형주 몫도 큼.
- 대안: 두 층 `partially_explained`(직접 재료가 있고 방향이 일부 맞음). 이 경우 e1 을 `must` 로 올릴 수 있음.
