"""backend 첫 리비전(99dbfe02fd98)이 만든 표. 테스트 DB 를 실제 설치 순서와 같게 만든다.

실제 DB 에서는 backend 가 `alembic upgrade head` 로 먼저 이 표들을 만들고, 그다음에 AI 가
news·source_card 를 넘겨받고 channel 을 FK 로 가리킨다. AI 리비전은 이 표가 없으면 중단한다.

DDL 은 backend 리비전을 오프라인으로 렌더링한 그대로다. 손으로 고치지 않는다 — 고치면
"backend 가 만든 그 표" 가 아니게 된다. AI 가 넘겨받는 데 필요한 표(channel·news·
source_card)와 source_card 를 인용하는 report 쪽만 둔다. backend 이력 표(alembic_version)는
AI 이력(alembic_version_ai)과 섞이지 않는지 보려고 같이 만든다.
"""

BACKEND_HEAD = "20260922_01"

BACKEND_DDL = """
CREATE TABLE channel (
    id SERIAL NOT NULL,
    telegram_handle VARCHAR(100) NOT NULL,
    name VARCHAR(200) NOT NULL,
    is_public BOOLEAN NOT NULL,
    grade VARCHAR(1),
    reviewed_by VARCHAR(50),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    category VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (telegram_handle)
);

CREATE TABLE news (
    id SERIAL NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    publisher VARCHAR(100) NOT NULL,
    source VARCHAR(20) NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE NOT NULL,
    summary TEXT NOT NULL,
    cleaned_text TEXT,
    collected_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (url)
);

CREATE INDEX ix_news_published_at ON news (published_at);

CREATE TABLE report (
    id BIGSERIAL NOT NULL,
    report_type VARCHAR(20) NOT NULL,
    stock_code VARCHAR(12),
    title VARCHAR(200) NOT NULL,
    body TEXT,
    verdict VARCHAR(20),
    status VARCHAR(20) NOT NULL,
    generated_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE report_block (
    id BIGSERIAL NOT NULL,
    report_id BIGINT NOT NULL,
    block_type VARCHAR(20) NOT NULL,
    order_index INTEGER NOT NULL,
    claim VARCHAR(300),
    detail TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(report_id) REFERENCES report (id)
);

CREATE TABLE source_card (
    id BIGSERIAL NOT NULL,
    card_type VARCHAR(50) NOT NULL,
    stock_code VARCHAR(12),
    event_date DATE,
    channel_id INTEGER,
    source_name VARCHAR(100),
    source_url VARCHAR(500),
    raw_text TEXT,
    cleaned_text TEXT,
    tags JSONB NOT NULL,
    payload JSONB NOT NULL,
    confidence FLOAT,
    collected_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(channel_id) REFERENCES channel (id)
);

CREATE INDEX idx_source_card_payload_gin ON source_card USING gin (payload);

CREATE INDEX idx_source_card_stock_date ON source_card (stock_code, event_date);

CREATE INDEX idx_source_card_tags_gin ON source_card USING gin (tags);

CREATE INDEX idx_source_card_type ON source_card (card_type);

CREATE TABLE report_citation (
    id BIGSERIAL NOT NULL,
    report_id BIGINT NOT NULL,
    block_id BIGINT,
    source_card_id BIGINT NOT NULL,
    excerpt TEXT,
    citation_type VARCHAR(20) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(block_id) REFERENCES report_block (id),
    FOREIGN KEY(report_id) REFERENCES report (id),
    FOREIGN KEY(source_card_id) REFERENCES source_card (id)
);

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL,
    PRIMARY KEY (version_num)
);
"""


def backend_statements() -> list[str]:
    """asyncpg 는 한 번에 한 문장을 받는다."""
    return [s.strip() for s in BACKEND_DDL.split(";") if s.strip()] + [
        f"INSERT INTO alembic_version VALUES ('{BACKEND_HEAD}')"
    ]
