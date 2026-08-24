"""MockParser（SPEC §7.8）。

キーワードと正規表現による決定的な実装。
バックエンドの全単体テストで使用し、GEMINI_API_KEY 未設定時のフォールバックも兼ねる。
ネットワーク接続を行わず、トークンも消費しない。
"""

from app.llm.base import IntentParser, ParseResult


class MockParser(IntentParser):
    """キーワード照合による決定的なパーサー。"""

    def parse(self, text: str) -> ParseResult:
        raise NotImplementedError("骨組みのみ。実装は次段階")
