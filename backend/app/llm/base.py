"""IntentParser インターフェースと ParseResult（SPEC §7.8）。

parse(text) -> ParseResult という単一メソッドのみを契約とする。
本番は GeminiParser、テストと API キー未設定時は MockParser を使う。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, get_args

from app.llm.normalize import normalize_vehicle_no

Intent = Literal[
    "query_vehicle", "lock_vehicle", "unlock_vehicle", "mark_sold", "unknown"
]

# 意図の列挙（SPEC §7.2）。LLM が列挙外の値を返した場合の検証に使う
INTENTS: frozenset[str] = frozenset(get_args(Intent))

# vehicle_no を必須とする意図（SPEC §7.2）
INTENTS_REQUIRING_VEHICLE_NO: frozenset[str] = frozenset(INTENTS - {"unknown"})

# note を持ちうる意図（SPEC §7.2）
INTENTS_ACCEPTING_NOTE: frozenset[str] = frozenset({"lock_vehicle"})


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


def build_parse_result(
    *,
    intent: str | None,
    vehicle_no: str | None,
    note: str | None,
    confidence: float | None,
    raw_text: str,
) -> ParseResult:
    """パーサーの生の出力を SPEC §7.3 の契約に整える。

    GeminiParser と MockParser の双方がここを通ることで、
    正規化・missing の算出・値域の丸めが1箇所に揃う。
    """
    if intent not in INTENTS or intent == "unknown":
        # 列挙外の意図は認識不能として扱う（SPEC §7.3 のフォールバック）。
        # unknown には確信度を持たせる意味が無いため 0.0 に統一する（SPEC §7.6）
        return unknown_result(raw_text)

    normalized = (
        normalize_vehicle_no(vehicle_no)
        if intent in INTENTS_REQUIRING_VEHICLE_NO
        else None
    )
    missing: list[str] = []
    if intent in INTENTS_REQUIRING_VEHICLE_NO and normalized is None:
        # 正規化に失敗した番号は「聞き取れなかった」と同義に扱う（SPEC §7.5-7）
        missing.append("vehicle_no")

    cleaned_note = None
    if intent in INTENTS_ACCEPTING_NOTE and note:
        cleaned_note = note.strip() or None

    return ParseResult(
        intent=intent,  # type: ignore[arg-type]
        vehicle_no=normalized,
        note=cleaned_note,
        confidence=_clamp_confidence(confidence),
        missing=missing,
        raw_text=raw_text,
    )


def unknown_result(raw_text: str) -> ParseResult:
    """認識不能時の統一フォールバック（SPEC §7.3）。"""
    return ParseResult(intent="unknown", confidence=0.0, raw_text=raw_text)


def _clamp_confidence(value: float | None) -> float:
    """confidence を 0.0〜1.0 に丸める。数値でなければ 0.0。"""
    try:
        return min(1.0, max(0.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
