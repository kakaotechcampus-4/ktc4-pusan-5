# market_data fixture

KRX·ECOS 응답 **모양**을 본뜬 것이다. 테스트는 이 파일을 MockTransport 로 돌려준다.

- `krx_kospi_dd_trd.json` 의 "코스피" 행과 `krx_stk_bydd_trd.json` 의 AJ네트웍스 행은
  팀 조사(backend/docs/api-research/krx.md, 2026-09-10 실응답)에 실린 원문 그대로다.
  "코스피 (외국주포함)" 행의 빈 가격 칸도 조사 문서의 실제 모양이다.
- 나머지 행(전기전자, 삼성전자)과 ECOS 값은 형식만 맞춘 가짜 숫자다. 시세로 쓰지 않는다.
- ECOS `1,391.2` 는 쉼표가 섞여 와도 읽는지 보려고 일부러 넣었다.
- 실제 응답과 모양이 어긋나는지는 `uv run pytest -m network -s tests/test_market_data_live.py` 로 본다.
