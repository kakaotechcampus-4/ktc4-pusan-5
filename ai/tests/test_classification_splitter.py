"""문장 분리 버전 고정. 이 시험이 깨지면 예전 회차의 "몇 번 문장" 을 다시 찾을 수 없다."""

import pytest

from app.services.classification.splitter import numbered, split

# v1 의 고정 입력·기대 출력. 기대 출력을 고치지 않는다 — 깨지면 새 버전을 만든다(splitter.py).
V1_BODY = "삼성전자는 $1.56 에 마감했다. The U.S. market rose on Sept. 17.\n1. 유가\n유가가 올랐다!"
V1_SENTENCES = [
    "삼성전자는 $1.56 에 마감했다.",
    "The U.S. market rose on Sept. 17.",
    "1. 유가",
    "유가가 올랐다!",
]


def test_v1_is_pinned() -> None:
    assert split(V1_BODY, "v1") == V1_SENTENCES


def test_numbered_starts_at_one() -> None:
    assert numbered(["가.", "나."]) == "[1] 가.\n[2] 나."


def test_unknown_version_is_rejected() -> None:
    with pytest.raises(KeyError):
        split("본문.", "v0")
