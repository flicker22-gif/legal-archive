"""案件归档检索系统 — FastAPI 入口。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import close_pool, init_pool, init_schema
from .routers_cases import router as cases_router
from .routers_documents import router as documents_router
from .routers_folders import router as folders_router
from .routers_search import router as search_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pool()
    init_schema()
    yield
    close_pool()


app = FastAPI(title="案件归档检索系统", version="1.0.0", lifespan=lifespan)

# 本地开发：允许 Next.js 前端跨域调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4730",
        "http://127.0.0.1:4730",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cases_router)
app.include_router(folders_router)
app.include_router(documents_router)
app.include_router(search_router)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}
