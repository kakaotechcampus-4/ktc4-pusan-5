"""소스에 상관없이 공통으로 쓰는 리포트 항목 모델.

Pydantic 을 쓰는 이유는 이게 **외부 경계**라서다. 네이버가 주는 JSON 을 그대로 담는
그릇이고, 남의 서버는 예고 없이 모양이 바뀐다. dataclass 면 `goalPrice` 가
숫자에서 문자열로 바뀌어도 조용히 통과해서 DB insert 할 때야 터진다 —
그때는 어느 필드가 원인인지 안 보인다. Pydantic 은 파싱하는 그 자리에서 터진다.
(backend/app/services/news/schema.py 의 NewsItem 과 같은 자리다.)
"""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

# 네이버가 쓰는 카테고리. daily 와 market 은 researchId 까지 같은 동일 데이터라 daily 만 받는다.
ResearchCategory = Literal["company", "industry", "economy", "invest", "daily"]

# 본문 추출 결과.
#   ok      뽑았다
#   empty   PDF 는 받았는데 글자가 0자다. 이미지로만 된 스캔본 — OCR 없이는 못 읽는다
#   failed  네트워크·용량 초과·파서 예외
#   skipped 첨부 자체가 없다
#   pending 아직 안 받았다
BodyStatus = Literal["ok", "empty", "failed", "skipped", "pending"]


class AnalystReportItem(BaseModel):
    """목록 한 줄 + 상세를 합친 것. DB 한 행이 된다."""

    source_id: str
    category: str
    title: str
    broker: str
    write_date: date
    item_code: str | None = None
    item_name: str | None = None
    read_count: int | None = None
    end_url: str | None = None
    attach_url: str | None = None
    opinion: str | None = None
    goal_price: int | None = None
    price_at_write: int | None = None
    summary_html: str | None = None
    summary_text: str | None = None
    # 산업 리포트 전용. 종목이 아니라 업종에 대한 의견이다.
    sector_opinion: str | None = None
    top_picks: list[str] = Field(default_factory=list)
    # 네이버 응답 원본. 나중에 우리 파싱이 틀렸을 때 대조할 수 있게 통째로 들고 있는다.
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def upside_pct(self) -> float | None:
        """상승여력. 목표주가가 작성 시점 주가보다 얼마나 위인가."""
        if not self.goal_price or not self.price_at_write:
            return None
        return round((self.goal_price - self.price_at_write) / self.price_at_write * 100, 2)


class PdfText(BaseModel):
    """PDF 에서 뽑은 본문. 파일 자체는 남기지 않고 이것만 남는다."""

    status: BodyStatus
    text: str | None = None
    chars: int = 0
    sha256: str | None = None
    size_bytes: int | None = None
    pages: int | None = None
    extractor: str | None = None  # pdftotext | pypdf
    error: str | None = None
