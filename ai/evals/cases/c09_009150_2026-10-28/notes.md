# c09 삼성전기 2026-10-28 판단 메모

## 판정 근거(expected_verdict, confidence_level)
move explained / relative explained, confidence partial
- 직접 공시(영업이익 6,910억원 컨센 6,420억원 상회, 11:58 장중 공개)이고 방향 일치(+8.74%, 대형주 대비 +6.07%). 컨퍼런스콜(AI 데이터센터 수요)도 같은 방향. 루브릭 §2 의 explained 정의를 충족.
- 지배주주순이익(컨센 5,242억원 대비 4,687억원)과 매출(소폭 하회)의 상충 요소는 상한(e1 likely_cause)과 rationale 로 다룸. 보고서가 순이익 상회처럼 단정하면 OVERCLAIM.
- cutoff 이후 삽입 자료(10-29 07:51, 07:52)는 판정 근거에서 제외.
- 처음에는 상충 요소 때문에 partially_explained 로 뒀으나, 루브릭에 없는 조건을 더한 것이라 explained 로 바꿈.
- 대안: partially_explained.

## 시황·오버나이트 메시지 https://t.me/KISGregKim/18879 (2026-11-10)
- 시황·오버나이트 메시지. 안 A 입력에는 kind 가 없어 근거 칸으로 들어감. 실서비스에서는 분류 단계에서 걸러질 수 있음.
- gold 사건으로 두지 않음. 채점(score_rule_a.py)은 이 메시지만 인용한 link 를 gold 밖 link 와 따로 "시황 메시지 link" 로 셈.

## 외국인·기관 매매(수급)를 forbidden_claims(f2)에 넣은 이유
- 유형은 `fabricated_cause`(입력에 없는 원인). 이 케이스의 `case.json` 에는 외국인·기관의 순매수·순매도 자료가 없음.
- 입력에 나오는 "수급"은 MLCC·메모리 등 제품의 수요·공급을 뜻하고, "기관"은 연구기관·단체 이름이라 투자자별 매매와 무관함.
- 보고서가 외국인·기관 매매를 원인으로 쓰면 입력에서 근거를 댈 수 없는 지어낸 원인이라 `relation_min` 을 `none`(언급만 해도 금지)으로 둠. 모른다고 쓴 문장은 걸리지 않음.

