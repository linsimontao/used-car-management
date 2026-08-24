"""MockParser（SPEC §7.8）。

キーワードと正規表現による決定的な実装。
バックエンドの全単体テストで使用し、GEMINI_API_KEY 未設定時のフォールバックも兼ねる。
ネットワーク接続を行わず、トークンも消費しない。

意図の決定規則：**テキスト中で最初に出現したキーワードの意図を採用する。**
「一度に認識する意図はひとつ、複数あれば最初の一件」という SPEC §7.7 の規則を、
出現位置の比較という決定的な手続きで実現する。
"""

import re
import unicodedata

from app.llm.base import IntentParser, ParseResult, build_parse_result
from app.llm.normalize import normalize_vehicle_no

# 意図ごとのキーワード（出現位置で競合を解決するため、優先順位は同点時のみ効く）。
# 「ロック解除」は unlock と lock の双方に一致しうるため、
# lock 側は直後に解除表現が続かないことを先読みで要求する。
INTENT_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "unlock_vehicle",
        r"ロック(?:を)?(?:解除|外|はず)|解除|(?:外|はず)して|戻して|もどして"
        r"|商談(?:は)?(?:終|やめ|中止|なくなり)|終わりました|終了|キャンセル|取り消|白紙|空けて",
    ),
    (
        "mark_sold",
        r"売れ|売却|成約|ご契約|契約|お買い上げ|買われ|納車",
    ),
    (
        "lock_vehicle",
        r"商談中|押さえ|おさえ|抑え|キープ|取り置き|取置|確保|ロック(?!.{0,3}(?:解除|外|はず))",
    ),
    (
        "query_vehicle",
        r"どうなって|どうなり|状態|状況|空いて|あいて|残って|教えて|確認|見せて"
        r"|ステータス|ありますか|ある\?|ある？|どう\?|どう？",
    ),
)

# 管理番号として現れうる文字（漢数字・カナ読み・アラビア数字）
NUMBER_CHARS = r"0-9〇零一二三四五六七八九ぁ-んァ-ヴー"

# 「101番」「イチマルイチ番の車」のように接尾辞を伴う表現
NO_WITH_SUFFIX = re.compile(rf"([{NUMBER_CHARS}]+?)(?:番の車|号車|番車|番)")

# 接尾辞が無い場合に順に試す候補（カタカナ読み → 漢数字 → アラビア数字 → ひらがな読み）
FALLBACK_CANDIDATES: tuple[str, ...] = (
    r"[ァ-ヴー]{3,}",
    r"[〇零一二三四五六七八九]{3,}",
    r"\d{3,4}",
    rf"[ぁ-ん]{{3,}}",
)

# 「田中様と商談中です」から商談メモを取り出す
NOTE_PATTERN = re.compile(r"([^\s、。,]{1,12}?(?:様|さん))と(?:の)?(?:商談|お話|話)")

# 確信度。意図・番号ともに取れたときが最も高い
CONFIDENCE_FULL = 0.9
CONFIDENCE_NO_NUMBER = 0.5
CONFIDENCE_NUMBER_ONLY = 0.7


class MockParser(IntentParser):
    """キーワード照合による決定的なパーサー。"""

    def parse(self, text: str) -> ParseResult:
        """発話テキストを単一意図に解析する。外部通信は行わない。"""
        normalized_text = unicodedata.normalize("NFKC", text)
        intent = _detect_intent(normalized_text)
        vehicle_no = _extract_vehicle_no(normalized_text)

        if intent is None:
            # 番号だけが述べられた場合は照会と見なす（「101番」→ ステータス確認）
            if vehicle_no is None:
                return build_parse_result(
                    intent="unknown",
                    vehicle_no=None,
                    note=None,
                    confidence=0.0,
                    raw_text=text,
                )
            intent = "query_vehicle"
            confidence = CONFIDENCE_NUMBER_ONLY
        else:
            confidence = CONFIDENCE_FULL if vehicle_no else CONFIDENCE_NO_NUMBER

        note = None
        if intent == "lock_vehicle":
            matched = NOTE_PATTERN.search(normalized_text)
            if matched:
                note = f"{matched.group(1)}と商談中"

        return build_parse_result(
            intent=intent,
            vehicle_no=vehicle_no,
            note=note,
            confidence=confidence,
            raw_text=text,
        )


def _detect_intent(text: str) -> str | None:
    """最初に出現したキーワードの意図を返す。どれも無ければ None。"""
    hits: list[tuple[int, int, str]] = []
    for priority, (intent, pattern) in enumerate(INTENT_PATTERNS):
        matched = re.search(pattern, text)
        if matched:
            hits.append((matched.start(), priority, intent))
    if not hits:
        return None
    return min(hits)[2]


def _extract_vehicle_no(text: str) -> str | None:
    """管理番号らしき表現を切り出し、正規化を通す。

    正規化に失敗した候補は捨てて次の候補を試す。
    normalize 済みの3〜4桁が得られた候補だけを採用する。
    """
    for matched in NO_WITH_SUFFIX.finditer(text):
        normalized = normalize_vehicle_no(matched.group(1))
        if normalized:
            return normalized

    for pattern in FALLBACK_CANDIDATES:
        for candidate in re.findall(pattern, text):
            normalized = normalize_vehicle_no(candidate)
            if normalized:
                return normalized
    return None
