FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# PDF 본문 추출에 pdftotext(poppler)를 쓴다. 없으면 pypdf 로 넘어가지만 품질이 떨어진다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

# 상시 서버가 아니라 `python -m app.collectors.<이름>` 으로 한 번 돌고 끝나는 배치다.
# 기본 명령은 이미지가 정상인지 확인만 한다. 실제 실행은 `docker compose run --rm ai <명령>` 으로 넘긴다.
CMD ["/app/.venv/bin/python", "-c", "import app; print('basis-ai image ok')"]
