"""LLM 意図解析レイヤー。

パーサーの選択はここで一本化する。GEMINI_API_KEY 未設定なら MockParser。
"""

from functools import lru_cache

from app.config import get_settings
from app.llm.base import IntentParser, ParseResult
from app.llm.mock import MockParser

__all__ = ["IntentParser", "ParseResult", "get_parser"]


@lru_cache
def get_parser() -> IntentParser:
    """設定に応じたパーサーを返す（SPEC §13）。テストでは DI で差し替える。"""
    settings = get_settings()
    if settings.use_mock_parser:
        return MockParser()
    from app.llm.gemini import GeminiParser

    return GeminiParser(api_key=settings.gemini_api_key, model=settings.gemini_model)
