"""종목 정보 표(stock_meta.json) — 업종 라벨과 대형주 유니버스 시총 비중.

지금은 러너 설정 파일 하나에 둔다. 나중에 KRX 업종 분류나 DB 종목 테이블로 옮길 때는 이 모듈의 함수만 바꾸면
된다(부르는 쪽은 코드로 묻기만 한다). 표에 없는 종목은 업종 None, 비중 None 이다.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

META_PATH = Path(__file__).with_name("stock_meta.json")


@lru_cache(maxsize=1)
def _table() -> dict[str, dict[str, Any]]:
    return json.loads(META_PATH.read_text(encoding="utf-8"))["stocks"]


def sector(code: Any) -> list[str] | None:
    """업종 라벨 목록(예: ["지주", "반도체"]). 표에 없으면 None."""
    info = _table().get(str(code))
    return list(info["sector"]) if info and info.get("sector") else None


def universe_weight(code: Any) -> float | None:
    """대형주 유니버스 안 시총 비중(0~1). 유니버스 밖이거나 표에 없으면 None."""
    info = _table().get(str(code))
    return info.get("universe_weight") if info else None


def universe_codes() -> tuple[str, ...]:
    """대형주 유니버스 종목코드(universe_weight 가 있는 종목). 입력 peer_median_pct 의 비교 대상과 같은 묶음이다."""
    return tuple(sorted(code for code, info in _table().items() if info.get("universe_weight") is not None))


__all__ = ["META_PATH", "sector", "universe_codes", "universe_weight"]
