# c04 SK하이닉스 2026-10-26 판단 메모

## `unconfirmed_items` 에 특별배당 보도를 적은 이유
- 키옥시아 지분 차익 약 16조원 특별배당 추진은 동아일보 보도(IB·재계 전언)이고, 회사는 해명(미확정) 공시 단계였음.
- 보고서가 이를 확정된 환원으로 쓰면 과장이라 `unconfirmed_items` 에 적고 e1 상한을 `coincident` 로 둠.
- 형식은 문장 하나(보도 내용, 출처 성격, 확인 전 단계).

## `move` 층에는 사건을 달지 않은 이유
- 등락률이 -0.16% 라 `judge_layers.move` 가 false(절댓값 1 이하). e1 의 `layer` 는 `relative` 만.

## e2(HBM4 출하 지연)를 `optional` 로 둔 이유
- 16:28 장 마감 후 공개라 그날 움직임의 원인이 될 수 없음. 맥락 정보로만 둠.

## 판정 근거(expected_verdict, confidence_level)
move no_clear_cause / relative partially_explained, confidence partial
- move 는 -0.16% 라 judge_layers 가 false(절댓값 1 이하)라 no_clear_cause 로 고정.
- relative(대형주 대비 +1.52, 덜 내림)에는 특별배당 추진 보도가 방향이 맞는 재료이지만 미확인이고 상한이 coincident. 방향은 맞아도 미확인·약해서 `partially_explained`(rubric §2).
- 대안: relative no_clear_cause(확정되지 않은 보도라 설명으로 인정하지 않음). 이 경우 confidence 는 `none`.
