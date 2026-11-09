# c06 HD현대 2026-10-28 판단 메모

## `stance: neutral` 로 둔 사건
- e2 조선 업종 밸류에이션 콜: 디레이팅 분석이라 방향이 애매함.
- e3 교환사채 발행: 자금 조달 의미와 희석 우려가 엇갈려 방향을 정하기 어려움.
- 방향이 불분명한 재료에 방향을 정하면 정상 보고서를 틀렸다고 채점할 위험이 더 커서 `neutral` 로 둠.

## e1 을 `optional` 로 둔 이유
- HD현대일렉트릭·HD현대중공업은 HD현대 본체가 아닌 계열·유사 종목이라 이 종목의 원인이 아님(유사 종목 혼동 함정).
- 보고서가 이를 HD현대 원인으로 쓰면 `forbidden_claims` 로 잡을 대상.

## e3(교환사채 발행)은 `should`
- HD현대 본체의 직접 재료지만 시황 메시지 속 한 줄이고 영향 방향이 불분명해 상한 `coincident`. 공시 접수 시각이 비어 있어 공시는 근거로 쓰지 않음.

## 판정 근거(expected_verdict, confidence_level)
move no_clear_cause / relative no_clear_cause, confidence none
- 본체의 직접 재료는 교환사채(e3) 한 줄뿐이고 영향 방향이 불분명. 루브릭 §2 의 "직접 재료는 있으나 방향이 불분명" 은 `no_clear_cause`.
- 계열·유사 종목 실적(e1)은 이 종목의 재료가 아니라 판정 근거에 쓰지 않음. move_strength_cap 이 partial(대형주 몫이 절반 이상)이라 상한은 coincident.
- 대안: `partially_explained`(e3 을 부분 설명으로 인정). 시황 메시지 속 한 줄이라 근거가 약해 택하지 않음.
