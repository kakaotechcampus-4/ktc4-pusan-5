"""One-time interactive login and read-only channel access checks."""

import argparse
import asyncio
import getpass
import os
from pathlib import Path

from app.core.config import settings
from app.services.analyst.telegram import (
    DEFAULT_CHANNELS,
    check_channels,
    connect_authorized,
    make_client,
)


def save_session(path: Path, session: str) -> None:
    """Never print the login credential or overwrite an existing credentials file."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(f"TELEGRAM_SESSION={session}\n")


async def login(path: Path) -> None:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    settings.require_telegram(require_session=False)
    if path.exists():
        raise RuntimeError(f"{path}가 이미 있습니다. 기존 파일을 별도 보관한 뒤 다시 실행하세요.")
    client = TelegramClient(StringSession(), settings.telegram_api_id, settings.telegram_api_hash)
    try:
        await client.start(
            phone=lambda: input("전화번호(국가번호 포함): "),
            code_callback=lambda: getpass.getpass("텔레그램 로그인 코드: "),
            password=lambda: getpass.getpass("2단계 인증 비밀번호: "),
        )
        save_session(path, client.session.save())
    finally:
        await client.disconnect()
    print(f"세션을 {path}에 저장했습니다. 이 파일을 공유하거나 커밋하지 마세요.")


async def check(channels: tuple[str, ...]) -> None:
    client = make_client()
    try:
        await connect_authorized(client)
        for label, _ in await check_channels(client, channels):
            print(f"{label}: PDF 목록 읽기 가능")
    finally:
        await client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--login", action="store_true", help="계정 로그인 후 .env.telegram 저장")
    modes.add_argument("--check", action="store_true", help="세션·채널 접근 확인; DB/가입 변경 없음")
    parser.add_argument("--channel", action="append", help="확인할 채널; 여러 번 지정 가능")
    args = parser.parse_args()
    try:
        asyncio.run(login(Path(".env.telegram")) if args.login
                    else check(tuple(args.channel or DEFAULT_CHANNELS)))
    except Exception as exc:  # noqa: BLE001 — 오류는 집계하되 계정 정보는 출력하지 않는다
        message = str(exc) if type(exc) is RuntimeError else type(exc).__name__
        parser.exit(1, f"텔레그램 준비 실패: {message}\n")


if __name__ == "__main__":
    main()
