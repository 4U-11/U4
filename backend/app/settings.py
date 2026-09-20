"""读取本地开发配置，并把相对路径固定解析到项目根目录。"""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """本地文件处理、翻译和 AI 服务配置。"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    upload_dir: Path = Path("storage/uploads")
    parsed_dir: Path = Path("storage/parsed")
    max_upload_size_mb: int = Field(default=50, gt=0)
    libretranslate_url: str = Field(default="http://127.0.0.1:5000", max_length=2048)
    libretranslate_api_key: SecretStr | None = None
    platform_ai_api_key: SecretStr | None = None
    platform_ai_base_url: str = Field(
        default="https://api.openai.com/v1", max_length=2048
    )
    platform_ai_model: str = Field(default="gpt-4o-mini", min_length=1, max_length=128)

    @property
    def uploads_path(self) -> Path:
        """相对 UPLOAD_DIR 始终相对于项目根目录，不受启动目录影响。"""
        if self.upload_dir.is_absolute():
            return self.upload_dir
        return (PROJECT_ROOT / self.upload_dir).resolve()

    @property
    def parsed_path(self) -> Path:
        """相对 PARSED_DIR 始终相对于项目根目录解析。"""
        if self.parsed_dir.is_absolute():
            return self.parsed_dir
        return (PROJECT_ROOT / self.parsed_dir).resolve()

    @property
    def tasks_path(self) -> Path:
        """Keep persisted task status alongside local parsed results."""
        return self.parsed_path / "tasks"

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


settings = Settings()
