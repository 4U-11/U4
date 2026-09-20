from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api_settings import router as settings_router
from .backup import router as backup_router
from .documents import router as documents_router
from .errors import register_error_handlers
from .processing import router as processing_router
from .documents import recover_interrupted_documents
from .task_store import recover_interrupted_processing_tasks


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Recover local tasks that were interrupted by a server restart."""
    recover_interrupted_documents()
    recover_interrupted_processing_tasks()
    yield


app = FastAPI(
    title="Course Material Learning Assistant API",
    version="0.1.0",
    lifespan=lifespan,
)

# 注册全局错误处理和资料接口，具体代码分别放在独立文件里。
register_error_handlers(app)
app.include_router(documents_router)
app.include_router(processing_router)
app.include_router(settings_router)
app.include_router(backup_router)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict[str, str]:
    """
    用于检查后端是否正常运行。
    """
    return {
        "status": "ok",
        "service": "course-material-api",
    }
