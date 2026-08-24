"""GeminiParser（SPEC §7）。本番実装。

Gemini の function calling / structured output でスキーマを強制する。
スキーマに合致しない応答が返った場合は例外を捕捉し、
{"intent": "unknown", "confidence": 0.0} にフォールバックする（SPEC §7.3）。
"""

from app.llm.base import IntentParser, ParseResult


class GeminiParser(IntentParser):
    """Gemini API を呼び出すパーサー。"""

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def parse(self, text: str) -> ParseResult:
        raise NotImplementedError("骨組みのみ。実装は次段階")
