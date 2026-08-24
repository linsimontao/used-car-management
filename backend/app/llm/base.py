"""IntentParser インターフェースと ParseResult（SPEC §7.8）。

parse(text) -> ParseResult という単一メソッドのみを契約とする。
本番は GeminiParser、テストと API キー未設定時は MockParser を使う。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

Intent = Literal[
    "query_vehicle", "lock_vehicle", "unlock_vehicle", "mark_sold", "unknown"
]


@dataclass
class ParseResult:
    """LLM の出力契約（SPEC §7.3）。"""

    intent: Intent
    vehicle_no: str | None = None
    note: str | None = None
    confidence: float = 0.0
    missing: list[str] = field(default_factory=list)
    # バックエンドが埋め戻す。LLM の出力ではない
    raw_text: str = ""


class IntentParser(ABC):
    """自然言語を単一意図の構造化データへ変換する。DB 参照も権限判定も行わない。"""

    @abstractmethod
    def parse(self, text: str) -> ParseResult:
        """発話テキストを解析する。"""
        raise NotImplementedError
