"""공통 자료 ID(source_card) 등록과 조회. 부르는 쪽은 이 패키지 이름으로 import 한다.

    registration   카드를 만들고 색인을 적는다. 쓰기
    query          공통 ID 를 고르고, 그 ID 로 원문을 읽는다
    url            출처 주소를 공통 ID 로 바꾼다
    read_model     읽은 결과의 모양과 조립. DB 를 열지 않는다

    register_missing_sources   카드가 없는 원문(news·analyst_reports·telegram_messages·
                               dart_disclosures)에 카드를
                               만든다. 몇 번을 돌려도 결과가 같다 — 원문 하나에 카드 하나라는
                               고유 제약이 있고, 이미 카드가 있는 원문은 고르지 않는다.
                               이번 원문의 카드에 공개 시각·날짜·종목(index_cards)도 다시 적는다
    backfill_canonical_urls    이관 전 news 행의 canonical_url 을 채운다
    get_sources                공통 ID 로 원문·메타데이터·발견 경로를 읽는다
    stock_card_ids             종목 하나의 자료 중 기준 시각 이전에 나온 것의 공통 ID
    card_ids_for_urls          출처 주소 → 공통 ID (보고서 출처를 원문에 이을 때)

시각 이름. 자료마다 남은 시각이 달라 무엇을 무엇과 비교하는지 섞이기 쉽다.
    cutoff           보고서가 몇 시 시점을 기준으로 만들어지는가(기준 시각). stock_card_ids 의
                     until 과 같은 값이다. 이 시각에 알 수 없던 것은 보고서에 쓰지 않는다
    available_at     자료가 공개돼 있었다고 확인된 가장 이른 시각(source_card). 자료를 고를 때
                     cutoff 와 비교한다(stock_card_ids)
    published_at     원문이 밝힌 발행 시각(기사)·게시 시각(메시지). 모르면 비어 있다
    write_date       PDF 작성일·공시 접수일. 시각 없이 날짜만 있다
    collected_at     수집기가 원문 행을 처음 저장한 시각. 공시는 처음 본 시각(first_seen_at)
    body_fetched_at  우리가 본문을 받은 시각. 발행 시각이 아니다 — 글은 나온 뒤에도 고쳐지므로
                     저장된 본문이 언제 것인지는 이 값만 말한다. 본문을 쓸지 정할 때 cutoff 와
                     비교한다(get_sources). 메시지는 처음 받은 글을 바꾸지 않아 collected_at 이다.
                     본문이 없으면 비어 있다

카드에는 원문을 복제하지 않는다. 원 발행처(source_name)와 채널만 적고 본문은 FK 로 읽는다.
"""

from app.repositories.source_card.query import get_sources, stock_card_ids
from app.repositories.source_card.read_model import Discovery, SourceRecord
from app.repositories.source_card.registration import (
    CanonicalBackfill,
    backfill_canonical_urls,
    register_missing_sources,
)
from app.repositories.source_card.url import card_ids_for_urls

__all__ = [
    "CanonicalBackfill",
    "Discovery",
    "SourceRecord",
    "backfill_canonical_urls",
    "card_ids_for_urls",
    "get_sources",
    "register_missing_sources",
    "stock_card_ids",
]
