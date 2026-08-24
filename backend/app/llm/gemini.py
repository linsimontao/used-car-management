"""GeminiParser（SPEC §7）。本番実装。

Gemini の function calling / structured output でスキーマを強制する。
スキーマに合致しない応答が返った場合は例外を捕捉し、
{"intent": "unknown", "confidence": 0.0} にフォールバックする（SPEC §7.3）。

エラーの切り分け：
  * API 呼び出しそのものの失敗（通信エラー・認証エラー・レート制限）
      → 502 LLM_UNAVAILABLE を送出する（SPEC §8.6）。利用者は再試行すればよい
  * 応答は得られたが内容がスキーマに合致しない
      → unknown へフォールバックする。再試行しても直らないため 502 にはしない
"""

import json
from typing import Any

from google import genai
from google.genai import types

from app.errors import LLMUnavailableError
from app.llm.base import IntentParser, ParseResult, build_parse_result, unknown_result
from app.llm.prompt import INTENT_SCHEMA, SYSTEM_PROMPT


class GeminiParser(IntentParser):
    """Gemini API を呼び出すパーサー。"""

    def __init__(self, api_key: str, model: str, client: Any | None = None) -> None:
        self.api_key = api_key
        self.model = model
        # client はテストでスタブを差し込むための注入口
        self._client = client if client is not None else genai.Client(api_key=api_key)

    def parse(self, text: str) -> ParseResult:
        """発話テキストを単一意図に解析する。DB も権限も参照しない（SPEC §7.1）。"""
        if not text.strip():
            # 空入力に API を呼ぶ意味はない
            return unknown_result(text)

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=text,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=INTENT_SCHEMA,
                    # 同じ発話に対して常に同じ解析結果を返させる
                    temperature=0.0,
                ),
            )
        except Exception as exc:  # noqa: BLE001 — SDK の例外階層に依存しない
            raise LLMUnavailableError(
                detail={"reason": type(exc).__name__, "model": self.model}
            ) from exc

        return self._to_result(getattr(response, "text", None), text)

    def _to_result(self, payload_text: str | None, raw_text: str) -> ParseResult:
        """構造化出力の JSON を ParseResult に変換する。不正なら unknown。"""
        try:
            payload = json.loads(payload_text)  # type: ignore[arg-type]
            if not isinstance(payload, dict):
                raise ValueError("オブジェクト以外が返された")
            return build_parse_result(
                intent=payload.get("intent"),
                vehicle_no=payload.get("vehicle_no"),
                note=payload.get("note"),
                confidence=payload.get("confidence"),
                raw_text=raw_text,
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            # スキーマ違反・安全性ブロックによる空応答など（SPEC §7.3）
            return unknown_result(raw_text)
