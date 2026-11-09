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

## 외국인·기관 매매(수급)를 forbidden_claims(f2)에 넣은 이유
- 유형은 `fabricated_cause`(입력에 없는 원인). 이 케이스의 `case.json` 에는 외국인·기관의 순매수·순매도 자료가 없음.
- 입력에 나오는 "수급"은 MLCC·메모리 등 제품의 수요·공급을 뜻하고, "기관"은 연구기관·단체 이름이라 투자자별 매매와 무관함.
- 보고서가 외국인·기관 매매를 원인으로 쓰면 입력에서 근거를 댈 수 없는 지어낸 원인이라 `relation_min` 을 `none`(언급만 해도 금지)으로 둠. 모른다고 쓴 문장은 걸리지 않음.

