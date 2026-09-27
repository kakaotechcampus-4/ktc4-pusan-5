"""Account-specific preparation without real Telegram calls."""

from datetime import UTC, date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telethon.errors.common import TypeNotFoundError

from app.collectors import telegram as collector
from app.collectors import telegram_setup
from app.core.config import Settings
from app.services.analyst.telegram import check_channels, connect_authorized, iter_pdf_messages


def test_login_requires_app_credentials_but_not_existing_session():
    config = Settings(_env_file=None, telegram_api_id=12345, telegram_api_hash="dummy")
    config.require_telegram(require_session=False)
    with pytest.raises(RuntimeError, match="TELEGRAM_SESSION"):
        config.require_telegram()


def test_blank_session_is_rejected():
    with pytest.raises(RuntimeError, match="TELEGRAM_SESSION"):
        Settings(_env_file=None, telegram_api_id=12345,
                 telegram_api_hash="dummy", telegram_session=" ").require_telegram()


def test_session_file_is_private_and_never_overwritten(tmp_path):
    path = tmp_path / ".env.telegram"
    telegram_setup.save_session(path, "dummy-session")
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        telegram_setup.save_session(path, "replacement")
    assert path.read_text() == "TELEGRAM_SESSION=dummy-session\n"


async def test_revoked_session_does_not_start_interactive_login():
    client = AsyncMock()
    client.is_user_authorized.return_value = False
    with pytest.raises(RuntimeError, match="세션"):
        await connect_authorized(client)
    client.start.assert_not_awaited()


async def test_channel_check_reads_pdf_list_without_joining():
    client = AsyncMock()
    client.get_input_entity.return_value = "resolved-peer"
    assert await check_channels(client, ("channel_one",)) == [("channel_one", "resolved-peer")]
    client.get_messages.assert_awaited_once()
    assert client.get_messages.await_args.kwargs["limit"] == 1


async def test_channel_resolution_falls_back_to_own_dialogs():
    client = AsyncMock()
    client.get_input_entity.side_effect = ValueError("not cached")

    async def dialogs():
        yield SimpleNamespace(entity=SimpleNamespace(username="channel_one"),
                              input_entity="own-account-peer")

    client.iter_dialogs = dialogs
    assert await check_channels(client, ("channel_one",)) == [("channel_one", "own-account-peer")]


async def test_access_error_does_not_expose_protocol_bytes():
    client = AsyncMock()
    client.get_messages.side_effect = ValueError("PRIVATE_ACCOUNT_HASH")
    with pytest.raises(RuntimeError, match="접근 확인 실패") as error:
        await check_channels(client, ("channel_one",))
    assert "PRIVATE_ACCOUNT_HASH" not in str(error.value)


async def test_unsupported_response_is_not_silently_reported_as_success():
    async def messages(*args, **kwargs):
        raise TypeNotFoundError(123, b"PRIVATE_ACCOUNT_HASH")
        yield  # async iterator

    client = SimpleNamespace(iter_messages=messages)
    with pytest.raises(RuntimeError, match="부분 수집"):
        async for _ in iter_pdf_messages(client, "channel_one", date(2026, 1, 1)):
            pass


async def test_collector_checks_access_before_opening_database(monkeypatch):
    client = AsyncMock()
    monkeypatch.setattr(collector, "make_client", lambda: client)
    monkeypatch.setattr(collector, "check_channels",
                        AsyncMock(side_effect=RuntimeError("접근 확인 실패")))
    monkeypatch.setattr(collector, "SessionLocal", lambda: pytest.fail("DB must not be opened"))
    with pytest.raises(RuntimeError, match="접근 확인 실패"):
        await collector.collect()
    client.disconnect.assert_awaited_once()
    client.start.assert_not_awaited()


def test_cli_exits_nonzero_on_collection_failure(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["telegram"])
    monkeypatch.setattr(collector, "collect", AsyncMock(side_effect=RuntimeError("채널 오류")))
    with pytest.raises(SystemExit) as error:
        collector.main()
    assert error.value.code == 1
    assert "채널 오류" in capsys.readouterr().err


async def test_partial_channel_failure_saves_progress_but_reports_failure(monkeypatch):
    from datetime import datetime

    from app.services.analyst.schema import PdfText

    client = AsyncMock()
    manager = AsyncMock()
    session = manager.__aenter__.return_value
    monkeypatch.setattr(collector, "make_client", lambda: client)
    monkeypatch.setattr(collector, "SessionLocal", lambda: manager)
    monkeypatch.setattr(collector, "check_channels", AsyncMock(return_value=[
        ("channel_one", "one"), ("channel_two", "two"),
    ]))
    monkeypatch.setattr(collector, "known_ids", AsyncMock(side_effect=lambda *a: set()))
    monkeypatch.setattr(collector, "known_naver_pdf_hashes", AsyncMock(return_value=set()))
    save = AsyncMock(side_effect=lambda session, rows: len(rows))
    monkeypatch.setattr(collector, "upsert_analyst_reports", save)
    monkeypatch.setattr(collector, "_extract", AsyncMock(return_value=PdfText(
        status="ok", text="실적과 사업을 분석한 본문입니다. " * 100,
    )))

    async def messages(client, peer, since):
        yield SimpleNamespace(id=1, date=datetime.now(UTC)), "report.pdf"
        if peer == "one":
            raise RuntimeError("unreadable response")

    monkeypatch.setattr(collector, "iter_pdf_messages", messages)
    with pytest.raises(RuntimeError, match="완료 저장 2건"):
        await collector.collect(delay=0)
    assert save.await_count == 2
    assert session.commit.await_count == 2
    client.disconnect.assert_awaited_once()
