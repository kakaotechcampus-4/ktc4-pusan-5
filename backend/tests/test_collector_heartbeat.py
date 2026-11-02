"""수집기 하트비트. compose 헬스체크가 이 파일의 수정 시각을 보므로, 갱신되고 실패해도 수집을 막지 않아야 한다."""

import logging
import os
import time
from pathlib import Path

from app.collectors.market import HEARTBEAT_PATH, touch_heartbeat


def test_touch_creates_the_file(tmp_path):
    path = tmp_path / "collector-heartbeat"

    touch_heartbeat(path)

    assert path.exists()


def test_touch_moves_the_modification_time_forward(tmp_path):
    path = tmp_path / "collector-heartbeat"
    path.touch()
    old = time.time() - 600
    os.utime(path, (old, old))

    touch_heartbeat(path)

    assert time.time() - path.stat().st_mtime < 5


def test_unwritable_path_does_not_raise_and_logs_a_warning(tmp_path, caplog):
    path = tmp_path / "missing-dir" / "collector-heartbeat"

    with caplog.at_level(logging.WARNING, logger="app.collectors.market"):
        touch_heartbeat(path)

    assert not path.exists()
    assert "cannot write" in caplog.text


def test_default_path_is_the_one_the_compose_healthcheck_reads():
    compose = Path(__file__).resolve().parents[2] / "docker-compose.yml"

    assert HEARTBEAT_PATH.as_posix() in compose.read_text(encoding="utf-8")
