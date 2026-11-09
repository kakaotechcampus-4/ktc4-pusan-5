# c07 삼성전자 2026-10-26 판단 메모

## `stance: neutral` 로 둔 사건
- e2 휴머노이드 로봇 기술 점검·CES 2027 공개 예정: 장기 소식이라 단기 주가 방향이 없음. 방향을 정하지 않음.

## 이 날을 원인 없는 날 후보로 본 이유
- 사건이 모두 `optional` 이고 e1(HBM4 출하 지연)은 16:28 장 마감 후 공개라 그날 하락의 원인이 될 수 없음.
- `market_led` 가 true, `relative` 는 대형주 대비 +0.52 라 판단하지 않는 층. `must` 0개, `confidence_level: none` 후보.

## 판정 근거(expected_verdict, confidence_level)
move no_clear_cause / relative no_clear_cause, confidence none
- relative 는 대형주 대비 +0.52 라 judge_layers 가 false. move(-1.16%)는 market_led 가 true 이고 재료가 모두 optional·coincident(마감 후 HBM4 소식, 간접 로보틱스 리포트).
- 대안: 없음. 원인 없는 날 후보.

## 외국인·기관 매매(수급)를 forbidden_claims(f2)에 넣은 이유
- 유형은 `fabricated_cause`(입력에 없는 원인). 이 케이스의 `case.json` 에는 외국인·기관의 순매수·순매도 자료가 없음.
- 입력에 나오는 "수급"은 MLCC·메모리 등 제품의 수요·공급을 뜻하고, "기관"은 연구기관·단체 이름이라 투자자별 매매와 무관함.
- 보고서가 외국인·기관 매매를 원인으로 쓰면 입력에서 근거를 댈 수 없는 지어낸 원인이라 `relation_min` 을 `none`(언급만 해도 금지)으로 둠. 모른다고 쓴 문장은 걸리지 않음.

