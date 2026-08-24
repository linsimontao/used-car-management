"""環境変数による設定（SPEC §13）。

すべての設定はここで一元管理し、他モジュールは `get_settings()` 経由で参照する。
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ ディレクトリの絶対パス。相対パスの基準として使う
BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """アプリケーション設定。既定値は SPEC §13 の表に一致させる。"""

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # SQLite ファイルのパス
    db_path: str = "./data/app.db"
    # 未設定の場合 /api/parse は自動的に MockParser にフォールバックする
    gemini_api_key: str = ""
    # モデル ID。コード改修なしで差し替え可能
    gemini_model: str = "gemini-3.5-flash"
    # ロックの有効期間（分）
    lock_ttl_minutes: int = 120
    # この値を下回るとフロントが「うまく聞き取れませんでした」を表示する
    low_confidence_threshold: float = 0.6
    # フロントエンド開発サーバーのアドレス（カンマ区切りで複数指定可）
    cors_origins: str = "http://localhost:5173"
    # 画面表示用のタイムゾーン
    tz_display: str = "Asia/Tokyo"

    @property
    def db_file(self) -> Path:
        """DB_PATH を backend/ 基準の絶対パスとして解決する。"""
        path = Path(self.db_path)
        return path if path.is_absolute() else (BACKEND_ROOT / path).resolve()

    @property
    def database_url(self) -> str:
        """SQLAlchemy 用の接続 URL。"""
        return f"sqlite:///{self.db_file}"

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS_ORIGINS をリストに分解する。"""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def use_mock_parser(self) -> bool:
        """API キー未設定なら MockParser を使う（SPEC §13）。"""
        return not self.gemini_api_key


@lru_cache
def get_settings() -> Settings:
    """設定のシングルトン。プロセス内で 1 度だけ読み込む。"""
    return Settings()
