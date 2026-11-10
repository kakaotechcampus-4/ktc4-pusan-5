# v0.2 세트 · 프롬프트 5125d7cc8ed7 실행 (2026-11-10)

- 세트: gold.lock.json v0.2 잠정 잠금(cases/ 10건 + cases_live/ 3건). v0.1 에서 바뀐 것은 b04 정정 공시 메시지의 `is_correction: true` 뿐
- 코드: `feature/peer-group-mixed-direction-e2e` 의 커밋 4b5f312(1c4f27a 포함)를 깨끗한 임시 worktree 로 꺼내 실행. 커밋 안 된 작업 트리 수정은 쓰지 않음
- 프롬프트: `stock_analysis_system.md` sha256 `5125d7cc8ed746e0cf2e55689de0571f51c707e73bb64fdf097479930b42a51d`(실행 결과 39건 모두 같은 값)
- 실행: 케이스당 3회, `--concurrency 3`. A 30건 ₩285.67, B 9건 ₩35.27(b05 는 정형 보고서라 ₩0), 합계 ₩320.94
- 채점: `score_rule_a.py`(변경 없음). `A/summary.json`, `B/summary.json`, 케이스별 `*/cases/`
- 비교: `compare.md`, `compare.json` — rescore-v0.1(A-20261110·B-20261110 실행을 v0.1 gold 로 다시 채점한 것)과 비교

주의: 이전 실행의 프롬프트 해시는 `98bde8b0ce9c` 다. 그 뒤로 정정 공시 외에도 엇갈린 그룹·코스피 비교 문장 등
프롬프트·코드 수정이 여러 번 들어갔으므로, 바뀐 숫자를 정정 공시 수정 하나의 효과로 읽으면 안 된다. 케이스당 3회라 1회 차이는 흔들림일 수 있다.
