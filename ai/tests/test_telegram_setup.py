"""Account-specific preparation without real Telegram calls."""

import os
from datetime import UTC, date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telethon.errors.common import TypeNotFoundError

from app.collectors import telegram as collector
from app.collectors import telegram_setup
from app.core.config import Settings
from app.core.scope import ScopeError, parse_scope
from app.services.analyst.telegram import check_channels, connect_authorized, iter_pdf_messages

# 수집기 테스트용 수집 범위. 실제 범위 파일(collection_scope.toml)은 비어 있어 수집기가 멈춘다.
SCOPE = parse_scope({
    "period": {"start": date(2000, 1, 1), "end": date(2100, 1, 1)},
    "sources": {"telegram_client": {
        "enabled": True, "channels": ["ch", "channel_one", "channel_two"], "max_items": 1000,
        "terms": {"status": "미확인"},
    }},
})


@pytest.fixture
def scoped(monkeypatch):
    """수집기가 테스트용 범위를 읽고, 지금까지 쌓인 수를 collected 로 보게 한다."""
    state = {"collected": 0}
    monkeypatch.setattr(collector, "recorded_attachment_ids", AsyncMock(return_value=set()))
    monkeypatch.setattr(collector, "load_scope", lambda: SCOPE)
    monkeypatch.setattr(collector, "count_collected",
                        AsyncMock(side_effect=lambda session, source: state["collected"]))
    return state


def test_login_requires_app_credentials_but_not_existing_session():
    config = Settings(_env_file=None, telegram_api_id=12345, telegram_api_hash="dummy")
    config.require_telegram(require_session=False)
    with pytest.raises(RuntimeError, match="TELEGRAM_SESSION"):
        config.require_telegram()


def test_blank_session_is_rejected():
    with pytest.raises(RuntimeError, match="TELEGRAM_SESSION"):
        Settings(_env_file=None, telegram_api_id=12345,
                 telegram_api_hash="dummy", telegram_session=" ").require_telegram()


def test_session_file_is_never_overwritten(tmp_path):
    path = tmp_path / ".env.telegram"
    telegram_setup.save_session(path, "dummy-session")
    with pytest.raises(FileExistsError):
        telegram_setup.save_session(path, "replacement")
    assert path.read_text() == "TELEGRAM_SESSION=dummy-session\n"


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits do not verify Windows ACLs")
def test_session_file_has_private_posix_permissions(tmp_path):
    path = tmp_path / ".env.telegram"
    telegram_setup.save_session(path, "dummy-session")
    assert path.stat().st_mode & 0o777 == 0o600


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


async def test_collector_checks_access_before_opening_database(monkeypatch, scoped):
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


async def test_partial_channel_failure_saves_progress_but_reports_failure(monkeypatch, scoped):
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
    record = AsyncMock(return_value=None)
    monkeypatch.setattr(collector, "record_pdf_messages", record)
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
    # PDF 행과 같은 묶음에서 메시지·발견 경로도 남긴다. 채널이 중간에 죽어도 그때까지 것은 남긴다.
    assert [call.args[1] for call in record.await_args_list] == ["channel_one", "channel_two"]
    assert all([f.msg_id for f in call.kwargs["found"]] == [1] for call in record.await_args_list)
    client.disconnect.assert_awaited_once()


async def test_naver_duplicates_and_excluded_pdfs_are_recorded_as_found(monkeypatch, scoped):
    """PDF 행을 만들지 않은 메시지도 '이 메시지에서 발견했다' 는 기록으로 넘긴다."""
    from datetime import datetime

    from app.services.analyst.schema import PdfText

    client = AsyncMock()
    manager = AsyncMock()
    monkeypatch.setattr(collector, "make_client", lambda: client)
    monkeypatch.setattr(collector, "SessionLocal", lambda: manager)
    monkeypatch.setattr(collector, "check_channels", AsyncMock(return_value=[("ch", "peer")]))
    monkeypatch.setattr(collector, "known_ids", AsyncMock(return_value=set()))
    monkeypatch.setattr(collector, "known_naver_pdf_hashes", AsyncMock(return_value={"dup"}))
    save = AsyncMock(side_effect=lambda session, rows: len(rows))
    monkeypatch.setattr(collector, "upsert_analyst_reports", save)
    record = AsyncMock(return_value=None)
    monkeypatch.setattr(collector, "record_pdf_messages", record)
    pdfs = {1: PdfText(status="ok", text="본문 " * 400, sha256="dup"),
            2: PdfText(status="ok", text="본문 " * 400, sha256="ai"),
            3: PdfText(status="ok", text="본문 " * 400, sha256="new")}
    monkeypatch.setattr(collector, "_extract", AsyncMock(side_effect=lambda c, m, f: pdfs[m.id]))
    monkeypatch.setattr(collector, "exclusion_reason",
                        lambda filename, body: "AI 생성" if filename == "2.pdf" else None)

    async def messages(client, peer, since):
        for msg_id in (1, 2, 3):
            yield SimpleNamespace(id=msg_id, date=datetime.now(UTC), message=f"글 {msg_id}",
                                  edit_date=None), f"{msg_id}.pdf"

    monkeypatch.setattr(collector, "iter_pdf_messages", messages)
    assert await collector.collect(delay=0, channels=("ch",)) == {"ch": 1}

    [call] = record.await_args_list
    found = call.kwargs["found"]
    assert [(f.msg_id, f.pdf_sha256, f.excluded, f.text) for f in found] == [
        (1, "dup", False, "글 1"), (2, "ai", True, "글 2"), (3, "new", False, "글 3"),
    ]
    assert call.kwargs["is_public"] is True, "주소(username)로 연 채널은 공개 채널이다"


def test_channels_opened_by_id_are_not_registered_as_public():
    """id:access_hash 로 연 채널은 공개 여부를 확인하지 못했다. 공개로 잘못 적지 않는다."""
    assert collector.public_channels(("sunstudy1234", "DOC_POOL=123:456")) == {
        "sunstudy1234": True, "DOC_POOL": False,
    }


def test_forwarded_message_keeps_where_it_came_from():
    """다른 채널 글을 전달한 PDF 메시지는 원래 채널을 남긴다. 사용자 id 는 남기지 않는다."""
    from_channel = SimpleNamespace(fwd_from=SimpleNamespace(
        from_id=SimpleNamespace(channel_id=123), channel_post=45, from_name=None))
    from_hidden_user = SimpleNamespace(fwd_from=SimpleNamespace(
        from_id=None, channel_post=None, from_name="홍길동"))
    from_user = SimpleNamespace(fwd_from=SimpleNamespace(
        from_id=SimpleNamespace(user_id=7), channel_post=None, from_name=None))
    assert collector.forward_origin(from_channel) == ("channel:123", "https://t.me/c/123/45")
    assert collector.forward_origin(from_hidden_user) == ("홍길동", None)
    assert collector.forward_origin(from_user) == ("알 수 없음", None)
    assert collector.forward_origin(SimpleNamespace(id=1)) == (None, None)


async def test_out_of_scope_channel_is_refused_before_connecting(monkeypatch, scoped):
    monkeypatch.setattr(collector, "make_client", lambda: pytest.fail("범위 밖인데 접속했다"))
    with pytest.raises(ScopeError, match="sunstudy1234"):
        await collector.collect(channels=("sunstudy1234",))


def test_cli_shows_why_the_scope_refused(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["telegram"])
    monkeypatch.setattr(collector, "collect", AsyncMock(side_effect=ScopeError("범위에서 꺼져 있다")))
    with pytest.raises(SystemExit) as error:
        collector.main()
    assert error.value.code == 1
    assert "범위에서 꺼져 있다" in capsys.readouterr().err


def _pdf_run(monkeypatch, dates):
    """메시지 날짜 목록으로 수집기를 돌릴 준비. 내려받은 메시지 id 를 담는 목록을 돌려준다."""
    from app.services.analyst.schema import PdfText

    downloaded: list[int] = []

    async def extract(client, message, filename):
        downloaded.append(message.id)
        return PdfText(status="ok", text="실적과 사업을 분석한 본문입니다. " * 100,
                       sha256=f"sha{message.id}")

    async def messages(client, peer, since):
        for msg_id, posted in enumerate(dates, start=1):
            yield SimpleNamespace(id=msg_id, date=posted), f"{msg_id}.pdf"

    monkeypatch.setattr(collector, "make_client", lambda: AsyncMock())
    monkeypatch.setattr(collector, "SessionLocal", lambda: AsyncMock())
    monkeypatch.setattr(collector, "check_channels", AsyncMock(return_value=[("ch", "peer")]))
    monkeypatch.setattr(collector, "known_ids", AsyncMock(return_value=set()))
    monkeypatch.setattr(collector, "known_naver_pdf_hashes", AsyncMock(return_value=set()))
    monkeypatch.setattr(collector, "upsert_analyst_reports",
                        AsyncMock(side_effect=lambda session, rows: len(rows)))
    monkeypatch.setattr(collector, "record_pdf_messages", AsyncMock(return_value=None))
    monkeypatch.setattr(collector, "_extract", extract)
    monkeypatch.setattr(collector, "iter_pdf_messages", messages)
    return downloaded


async def test_volume_limit_stops_before_downloading_more(monkeypatch, scoped):
    """수집량 상한에 닿으면 다음 PDF 를 내려받지 않는다. 받고 나서 버리면 이미 수집한 것이다."""
    from datetime import datetime

    now = datetime.now(UTC)
    downloaded = _pdf_run(monkeypatch, [now, now, now])
    scoped["collected"] = 999  # 상한 1000 중 999 가 이미 쌓였다

    assert await collector.collect(delay=0, channels=("ch",)) == {"ch": 1}
    assert downloaded == [1]


async def test_messages_after_the_period_are_not_downloaded(monkeypatch, scoped):
    from datetime import datetime, timedelta

    now = datetime.now(UTC)
    ended = parse_scope({
        "period": {"start": date(2000, 1, 1), "end": (now - timedelta(days=2)).date()},
        "sources": {"telegram_client": {
            "enabled": True, "channels": ["ch"], "max_items": 1000, "terms": {"status": "미확인"},
        }},
    })
    downloaded = _pdf_run(monkeypatch, [now, now - timedelta(days=3)])

    assert await collector.collect(delay=0, channels=("ch",), scope=ended) == {"ch": 1}
    assert downloaded == [2], "기간이 끝난 뒤의 글은 받지 않는다"


async def test_failed_discovery_is_recovered_without_redownloading_at_quota(monkeypatch, scoped):
    from datetime import datetime

    mock_downloaded = _pdf_run(monkeypatch, [datetime.now(UTC)])
    mock_record = AsyncMock(side_effect=["mock discovery failure", None])
    monkeypatch.setattr(collector, "record_pdf_messages", mock_record)
    with pytest.raises(RuntimeError, match="mock discovery failure"):
        await collector.collect(delay=0, channels=("ch",))
    # PDF 커밋은 성공했고 발견 경로만 실패한 상태로 재실행한다.
    monkeypatch.setattr(collector, "known_ids", AsyncMock(return_value={"1"}))
    scoped["collected"] = 1000
    assert await collector.collect(delay=0, channels=("ch",)) == {"ch": 0}
    assert mock_downloaded == [1]
    assert mock_record.await_count == 2
    assert mock_record.await_args.kwargs["found"][0].msg_id == 1
