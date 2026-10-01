"""수집할 텔레그램 채널. **조금씩 늘린다.**

채널을 늘린 만큼 근거가 늘지는 않는다. 프로토타입에서 채널을 7개에서 9개로 늘렸을 때
SK하이닉스 근거는 0건 늘고 수집량만 15,000자 늘었다. 새 채널이 같은 뉴스를 되풀이해서다.
그래서 하나씩 넣고, 넣을 때마다 수집기 출력(링크·본문 확보)을 보고 판단한다.

등급은 팀 채널 목록(CHANNELS.md)의 것이다. **채널 이름만 보고 매긴 초안**이라,
넣기 전에 t.me/s/<아이디> 를 열어 실제로 그런 채널인지 확인한다.

    A    증권사 리서치 공식 채널. 애널리스트 실명·소속이 확인된다. 보고서에 인용한다
    B    실명 운영자·기관성 채널. 출처를 밝혀 인용한다
    C·D  인용하지 않는다

지금 셋은 A 등급 중 PR #34 발췌 실험의 기사 20건이 나온 채널이다. 링크 열기·정제·
문장 선택을 이미 한 번 돌려본 곳들이다.
"""

from dataclasses import dataclass
from typing import Literal

Tier = Literal["A", "B", "C", "D"]


@dataclass(frozen=True)
class Channel:
    id: str  # t.me/s/<id> 의 그 값
    name: str  # 채널에 표시되는 이름
    affiliation: str
    tier: Tier


CHANNELS: tuple[Channel, ...] = (
    Channel("skitteam", "[ IT는 SK ]", "SK증권 리서치 IT팀", "A"),
    Channel("merITz_tech", "[메리츠 Tech 김선우, 양승수, 김동관]", "메리츠증권 리서치", "A"),
    Channel("KISGregKim", "KOREA DAILY INSIGHT - KIS GREG KIM", "한국투자증권", "A"),
)


def select_channels(ids: list[str] | None) -> tuple[Channel, ...]:
    """아이디로 고른다. 없으면 전부. 목록에 없는 아이디는 멈춘다 — 오타로 0건이 되면
    "채널이 조용했다" 와 구분이 안 된다."""
    if not ids:
        return CHANNELS
    known = {channel.id: channel for channel in CHANNELS}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise ValueError(
            f"채널 목록에 없다: {', '.join(unknown)}. "
            f"있는 것: {', '.join(known)} (services/telegram_web/channels.py)"
        )
    return tuple(known[i] for i in ids)
