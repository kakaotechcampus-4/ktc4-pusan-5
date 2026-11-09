# c05 삼성전기 2026-10-30 판단 메모

## e1 공급계약을 `should` 로 둔 이유
- 사실: 8,793억원 규모(매출 대비 7.8%) MLCC 공급계약이라는 호재 공시가 14:15 에 나왔는데 주가는 -7.50% 급락.
- 직접 재료지만 하락과 방향이 반대라 판정이 `none` 이고, 루브릭상 `none` 이면 `must` 는 0개라 `should`. 상한은 `coincident`.
- 보고서가 이 공시를 하락 원인으로 쓰면 방향 뒤집기(`HF_FALSE_CAUSE`)로 잡을 대상.

## 판정 근거(expected_verdict, confidence_level)
move no_clear_cause / relative no_clear_cause, confidence none
- 직접 호재 공시는 있으나 -7.50%(대형주 대비 -4.60%p) 급락과 방향이 반대. 루브릭 §2 의 "직접 재료는 있으나 방향이 반대·혼재·불분명" 은 `no_clear_cause`.
- 하락 방향 재료는 입력에 없음. `unknowns` 후보: 급락의 개별 원인, 수급.
- 대안: `partially_explained`. 이 경우 e1 을 `must` 로 올릴 수 있음.
