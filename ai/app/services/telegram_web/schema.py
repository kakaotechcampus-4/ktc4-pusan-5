"""채널 메시지 한 건. t.me/s/ 웹 미리보기에서 읽은 그대로다.

**text 는 채널에 보이는 글자 그대로 둔다.** 보고서가 인용한 문장(quote)이 원문에 실제로
있는지 문자열로 대조하기 때문이다. 뉴스 링크 발췌를 손대지 않는 것과 같은 이유다
(news_link/clean.py 참고). 링크를 연 결과도 text 에 섞지 않고 옆의 link_bodies 에 붙인다.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.services.news_link.schema import LinkBody


class ChannelMessage(BaseModel):
    channel: str  # 채널 아이디 (t.me/s/<아이디>)
    msg_id: int | None = None  # 채널 안에서만 유일하다. (channel, msg_id) 가 키다
    url: str | None = None  # https://t.me/<채널>/<번호>. 보고서의 출처 주소가 된다
    # 게시 시각(KST). 보고서 대상일 기준으로 글을 자를 때(컷오프) 쓸 수 있는 **유일한 시각**이다.
    # 못 읽었으면 None 이다. 메시지를 버리지는 않지만 컷오프가 필요한 곳에서는 쓰지 않는다.
    posted_at: datetime | None = None
    author: str | None = None  # 채널 안 서명. 없는 채널이 많다
    views: str | None = None  # 조회수. "1.2K" 처럼 화면에 보이는 그대로
    text: str = ""  # 본문. <br> 은 줄바꿈이 되고, 나머지는 화면에 보이는 글자 그대로다
    # 본문에 걸린 외부 링크. 순서를 지키고 중복은 뺀다. t.me 링크(채널 홍보)는 넣지 않는다.
    links: list[str] = Field(default_factory=list)
    # 화면에 보이는 주소와 달라서 쓰지 않은 실제 링크(href). 작성자가 이전 글의 링크 서식을
    # 복사하면 생긴다(parse.py 참고). 대개 비어 있다.
    hidden_links: list[str] = Field(default_factory=list)
    attachment: str | None = None  # 첨부 파일 이름. 본문 없이 PDF 만 올린 글이 있다
    # 링크를 연 결과. 수집기(collectors/news_channels.py)가 붙인다. 24시간이 지난 글,
    # --no-links 로 돌린 경우, 열 만한 링크가 없는 글은 비어 있다.
    link_bodies: list[LinkBody] = Field(default_factory=list)
