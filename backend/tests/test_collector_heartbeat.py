"""수집기 하트비트. compose 헬스체크가 이 파일의 수정 시각을 보므로, 갱신되고 실패해도 수집을 막지 않아야 한다."""

import logging
import os
import time
from pathlib import Path

import pytest

from app.collectors.market import (
    HEARTBEAT_PATH,
    LAST_SUCCESS_PATH,
    is_success,
    touch_heartbeat,
    touch_last_success,
)
from app.services import krx


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
    if not compose.exists():
        pytest.skip("저장소 루트의 docker-compose.yml 이 없는 환경(backend 폴더만 있는 경우)")

    assert HEARTBEAT_PATH.as_posix() in compose.read_text(encoding="utf-8")


def test_last_success_touch_creates_the_file_and_moves_the_time_forward(tmp_path):
    path = tmp_path / "collector-last-success"
    path.touch()
    old = time.time() - 600
    os.utime(path, (old, old))

    touch_last_success(path)

    assert time.time() - path.stat().st_mtime < 5


def test_last_success_unwritable_path_does_not_raise(tmp_path, caplog):
    path = tmp_path / "missing-dir" / "collector-last-success"

    with caplog.at_level(logging.WARNING, logger="app.collectors.market"):
        touch_last_success(path)

    assert "cannot write" in caplog.text


def test_last_success_path_is_separate_from_the_heartbeat_the_healthcheck_reads():
    assert LAST_SUCCESS_PATH != HEARTBEAT_PATH


def test_is_success_requires_a_value_without_error():
    assert is_success(object(), None)
    assert not is_success(None, "UPSTREAM_TIMEOUT")
    assert not is_success(None, None)


def test_is_success_counts_a_krx_batch_when_either_half_arrived():
    both_failed = krx.MarketBatch(None, None, "A", "B")
    quote_only = krx.MarketBatch(object(), None, None, "B")
    sectors_only = krx.MarketBatch(None, [], "A", None)

    assert not is_success(both_failed, None)
    assert is_success(quote_only, None)
    assert is_success(sectors_only, None)
