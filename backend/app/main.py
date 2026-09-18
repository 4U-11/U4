from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI(
    title="Course Material Learning Assistant API",
    version="0.1.0",
)


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