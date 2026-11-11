"""수집·분류 스케줄. 서버 cron 이 회차 이름만 넘기면 여기서 무엇을 어떤 순서로 돌릴지 정한다.

    uv run python -m app.schedule list                    회차표와 cron(UTC) 시각
    uv run python -m app.schedule round r0900 --dry-run   무엇을 돌릴지만 본다(수집·분류는 실행하지 않는다)
    uv run python -m app.schedule round r0900             실제로 돌린다

회차표는 plan.py, 실행은 runner.py 다.
"""
