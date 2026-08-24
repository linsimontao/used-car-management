"""System prompt と function schema（SPEC §7.7）。

Gemini の structured output でスキーマを強制するため、
「JSON で出力せよ」と指示して文字列を自前でパースする方式は採らない。
"""

# System prompt に含めるべき要素は SPEC §7.7 を参照
SYSTEM_PROMPT = """（骨組みのみ。実装は次段階）"""

# Gemini に渡す構造化出力スキーマ（SPEC §7.3 の出力契約に対応）
INTENT_SCHEMA: dict = {}
