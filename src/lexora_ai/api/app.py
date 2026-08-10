from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from lexora_ai import __version__
from lexora_ai.api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.north_gateway_lock = asyncio.Lock()
    try:
        yield
    finally:
        manager = getattr(app.state, "checkpointer_manager", None)
        if manager is not None:
            await manager.__aexit__(None, None, None)


def create_app() -> FastAPI:
    app = FastAPI(
        title="法析 Lexora API",
        summary="AI 法律案例分析助手",
        description=(
            "基于用户提交的案件材料生成结构化案例分析。输出用于研究和材料整理，"
            "不构成法律意见。"
        ),
        version=__version__,
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


app = create_app()
