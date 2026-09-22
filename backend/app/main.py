from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.database import engine
from app.core.errors import (
    AppError,
    app_error_handler,
    http_exception_handler,
    unhandled_exception_handler,
    validation_error_handler,
)
from app.routers import concepts
from app.routers.auth import router as auth_router
from app.routers.market import router as market_router
from app.routers.stocks import router as stock_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 스키마는 여기서 만들지 않는다. `uv run alembic upgrade head` 로 미리 맞춰둔다.
    yield
    await engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(concepts.router)
app.include_router(market_router)
app.include_router(stock_router)
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])


@app.get("/health")
async def health():
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok"}
