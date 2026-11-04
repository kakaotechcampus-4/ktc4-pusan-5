"""수집할 텔레그램 채널. **조금씩 늘린다.**

채널을 늘린 만큼 근거가 늘지는 않는다. 프로토타입에서 채널을 7개에서 9개로 늘렸을 때
SK하이닉스 근거는 0건 늘고 수집량만 15,000자 늘었다. 새 채널이 같은 뉴스를 되풀이해서다.
그래서 작은 묶음으로 넣고, 넣을 때마다 수집기 출력(링크·본문 확보)을 보고 판단한다.

등급은 팀 채널 목록(CHANNELS.md. 저장소 밖의 팀 자료)을 따르고, 거기 없는 채널은 따로 매긴다.
어느 쪽이든 **이름 위주로 매긴 초안**이라, 넣기 전에 t.me/s/<아이디> 를 열어 실제로 그런 채널인지
확인한다.

    A    증권사 리서치 공식 채널. 애널리스트 실명·소속이 확인된다. 보고서에 인용한다
    B    실명 운영자·기관성 채널. 출처를 밝혀 인용한다
    C·D  인용하지 않는다

지금 넣은 채널은 모두 A 등급으로 둔다. 근거는 채널마다 다르다.

    skitteam·merITz_tech·KISGregKim
        CHANNELS.md 의 A 등급. PR #34 발췌 실험에 쓴 텔레그램 기사 20건이 나온 채널이고,
        링크 열기·정제를 이미 한 번 돌려 봤다.
    bio_shinhan·hedgecat0301·globalmktinsight·KISemicon
        CHANNELS.md 의 A 등급.
    financejeong·meritz_likecho·yskoh1·shinhan_park·thetransport·mirae_internet·HJS_YSK·IThardwareDisplay
        33개 종목 중 글이 적은 분야를 메우려고 넣은 증권사 섹터 채널. CHANNELS.md 에는 없고, 기존 채널의
        전달 글을 따라가 찾았다. 채널 이름과 글 표본 몇 건만 보고 잠정으로 A 를 매겼다.
"""

from dataclasses import dataclass
from typing import Literal

Tier = Literal["A", "B", "C", "D"]


@dataclass(frozen=True)
class Channel:
    id: str  # t.me/s/<id> 의 그 값
    name: str  # 채널에 표시되는 이름
    affiliation: str  # 운영 주체(증권사·팀). 수집 요약에 찍힌다
    tier: Tier  # 인용 등급 (맨 위 표)


CHANNELS: tuple[Channel, ...] = (
    Channel("skitteam", "[ IT는 SK ]", "SK증권 리서치 IT팀", "A"),
    Channel("merITz_tech", "[메리츠 Tech 김선우, 양승수, 김동관]", "메리츠증권 리서치", "A"),
    Channel("KISGregKim", "KOREA DAILY INSIGHT - KIS GREG KIM", "한국투자증권", "A"),
    Channel("bio_shinhan", "[신한 리서치본부] 제약/바이오", "신한투자증권 리서치", "A"),
    Channel("hedgecat0301", "키움증권 전략/시황 한지영", "키움증권 리서치", "A"),
    Channel("globalmktinsight", "[미래에셋증권 시황] 김석환, 김주연", "미래에셋증권 리서치", "A"),
    Channel("KISemicon", "[한투 테크팀] 남채민/황준태/김정찬/김연준", "한국투자증권 리서치", "A"),
    Channel("financejeong", "한국투자증권 금융 정태준", "한국투자증권 리서치", "A"),
    Channel("meritz_likecho", "메리츠 금융 조아해", "메리츠증권 리서치", "A"),
    Channel("yskoh1", "하나증권 증권/보험 고연수", "하나증권 리서치", "A"),
    Channel("shinhan_park", "[신한 리서치본부] 차·철·광(자동차/철강금속)", "신한투자증권 리서치", "A"),
    Channel("thetransport", "[한국투자 최고운] 운송", "한국투자증권 리서치", "A"),
    Channel("mirae_internet", "[미래 임희석] 인터넷/SW/게임", "미래에셋증권 리서치", "A"),
    Channel("HJS_YSK", "유안타 손현정 [유틸리티(전력기기)/음식료]", "유안타증권 리서치", "A"),
    Channel("IThardwareDisplay", "현대차증권 IT[전기전자 김종배, 반도체 소부장 윤동욱]", "현대차증권 리서치", "A"),
)


def select_channels(ids: list[str] | None) -> tuple[Channel, ...]:
    """아이디로 채널을 고른다. ids 가 비었으면 목록 전부를 돌려준다.

    목록에 없는 아이디가 있으면 ValueError 를 낸다. 오타 난 채널을 조용히 0건으로 넘기면
    "그 채널에 글이 없었다" 와 구분이 안 된다.
    """
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
