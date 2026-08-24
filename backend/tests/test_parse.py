"""意図解析のテスト（SPEC §7、§8.2）。

MockParser の意図判定、GeminiParser のフォールバックと障害時の扱い、
POST /api/parse の契約を検証する。実通信は行わない（SPEC §7.8）。
"""

import json
from typing import Any

import pytest

from app.errors import LLMUnavailableError
from app.llm.gemini import GeminiParser
from app.llm.mock import MockParser
from tests.conftest import auth

# ---------------------------------------------------------------- MockParser


@pytest.mark.parametrize(
    ("text", "expected_intent"),
    [
        ("101番の車、今どうなってる？", "query_vehicle"),
        ("イチマルイチの状態教えて", "query_vehicle"),
        ("2035番って空いてる？", "query_vehicle"),
        ("101番を商談中にして", "lock_vehicle"),
        ("イチマルイチ、押さえといて", "lock_vehicle"),
        ("101番、田中様と商談中です", "lock_vehicle"),
        ("101番のロック外して", "unlock_vehicle"),
        ("イチマルイチ、商談終わりました", "unlock_vehicle"),
        ("101番戻していいよ", "unlock_vehicle"),
        ("101番、売れました", "mark_sold"),
        ("イチマルイチ、ご成約です", "mark_sold"),
        ("101番を売却済にして", "mark_sold"),
    ],
)
def test_代表的な発話から意図を判定する(
    parser: MockParser, text: str, expected_intent: str
) -> None:
    """SPEC §7.2 の発話例をそのまま検証する。"""
    result = parser.parse(text)
    assert result.intent == expected_intent
    assert result.vehicle_no in {"101", "2035"}
    assert result.missing == []


def test_ロック解除はロック指示と取り違えない(parser: MockParser) -> None:
    """「ロック外して」は lock_vehicle ではなく unlock_vehicle。"""
    assert parser.parse("310番のロックを解除して").intent == "unlock_vehicle"


def test_複数の用件は最初の一件のみを採用する(parser: MockParser) -> None:
    """SPEC §7.7：一度に認識する意図はひとつだけ。"""
    result = parser.parse("101番を商談中にして、あと205番は売れました")
    assert result.intent == "lock_vehicle"
    assert result.vehicle_no == "101"


def test_商談メモを取り出す(parser: MockParser) -> None:
    """lock_vehicle のときだけ note を持つ（SPEC §7.2）。"""
    result = parser.parse("101番、田中様と商談中です")
    assert result.note == "田中様と商談中"


def test_ロック以外の意図ではnoteを持たない(parser: MockParser) -> None:
    """note は lock_vehicle 専用のパラメータ。"""
    assert parser.parse("101番、売れました").note is None


def test_番号が無い発話はmissingに積む(parser: MockParser) -> None:
    """必須パラメータの欠落は missing で表現する（SPEC §7.3）。"""
    result = parser.parse("商談中にして")
    assert result.intent == "lock_vehicle"
    assert result.vehicle_no is None
    assert result.missing == ["vehicle_no"]


def test_認識できない発話はunknownになる(parser: MockParser) -> None:
    """SPEC §7.6：unknown は確信度 0.0 とする。"""
    result = parser.parse("今日の天気はどうですか")
    assert result.intent == "unknown"
    assert result.confidence == 0.0
    assert result.vehicle_no is None


def test_カナ読みの番号も正規化される(parser: MockParser) -> None:
    """パーサーの出力は常に正規化済み（SPEC §7.5）。"""
    assert parser.parse("イチマルイチ番の車を商談中にして").vehicle_no == "101"
    assert parser.parse("ひゃくいちばん、押さえて").vehicle_no == "101"


# ---------------------------------------------------------------- GeminiParser


class _StubResponse:
    """generate_content の戻り値を模したスタブ。"""

    def __init__(self, text: str | None) -> None:
        self.text = text


class _StubModels:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class _StubClient:
    """genai.Client の最小限のスタブ。ネットワークには接続しない。"""

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.models = _StubModels(response, error)


def _gemini_with(payload: dict | str | None = None, error: Exception | None = None):
    """スタブクライアントを注入した GeminiParser を作る。"""
    text = payload if isinstance(payload, str) or payload is None else json.dumps(payload)
    client = _StubClient(_StubResponse(text), error)
    return GeminiParser(api_key="dummy", model="gemini-3.5-flash", client=client)


def test_Gemini応答の車両番号は必ず正規化される() -> None:
    """LLM の vehicle_no をそのまま信用しない（SPEC §7.5）。"""
    parser = _gemini_with(
        {"intent": "lock_vehicle", "vehicle_no": "イチマルイチ番", "note": None, "confidence": 0.93}
    )
    result = parser.parse("イチマルイチ番の車を商談中にして")
    assert result.vehicle_no == "101"
    assert result.confidence == 0.93
    assert result.raw_text == "イチマルイチ番の車を商談中にして"


def test_正規化できない番号はmissingになる() -> None:
    """3〜4桁にならない番号は null 扱い（SPEC §7.5-7）。"""
    parser = _gemini_with(
        {"intent": "query_vehicle", "vehicle_no": "12", "note": None, "confidence": 0.8}
    )
    result = parser.parse("12番どうなってる")
    assert result.vehicle_no is None
    assert result.missing == ["vehicle_no"]


def test_スキーマに合致しない応答はunknownにフォールバックする() -> None:
    """SPEC §7.3：列挙外の intent は認識不能として扱う。"""
    parser = _gemini_with({"intent": "delete_vehicle", "confidence": 0.99})
    result = parser.parse("101番を削除して")
    assert result.intent == "unknown"
    assert result.confidence == 0.0


def test_unknownの確信度は常にゼロになる() -> None:
    """unknown に確信度を持たせる意味は無い（SPEC §7.6）。"""
    result = _gemini_with({"intent": "unknown", "confidence": 0.98}).parse("今日の天気は？")
    assert result.intent == "unknown"
    assert result.confidence == 0.0


def test_JSONでない応答はunknownにフォールバックする() -> None:
    """構造化出力が壊れていても 500 にはしない。"""
    result = _gemini_with("これは JSON ではありません").parse("101番どうなってる")
    assert result.intent == "unknown"
    assert result.confidence == 0.0


def test_空応答はunknownにフォールバックする() -> None:
    """安全性ブロック等で text が None のケース。"""
    result = _gemini_with(None).parse("101番どうなってる")
    assert result.intent == "unknown"


def test_確信度は0から1に丸められる() -> None:
    """値域外の confidence をそのまま通さない。"""
    parser = _gemini_with(
        {"intent": "query_vehicle", "vehicle_no": "101", "confidence": 42}
    )
    assert parser.parse("101番どうなってる").confidence == 1.0


def test_API呼び出しの失敗はLLM_UNAVAILABLEになる() -> None:
    """通信・認証の失敗は 502 として利用者に伝える（SPEC §8.6）。"""
    parser = _gemini_with(error=RuntimeError("connection refused"))
    with pytest.raises(LLMUnavailableError) as excinfo:
        parser.parse("101番どうなってる")
    assert excinfo.value.status_code == 502
    assert excinfo.value.code == "LLM_UNAVAILABLE"


def test_空文字はAPIを呼ばずにunknownを返す() -> None:
    """無駄なトークンを消費しない。"""
    parser = _gemini_with({"intent": "query_vehicle", "confidence": 1.0})
    result = parser.parse("   ")
    assert result.intent == "unknown"
    assert parser._client.models.calls == []


def test_送信するリクエストにスキーマとプロンプトが含まれる() -> None:
    """structured output でスキーマを強制していること（SPEC §7.3）。"""
    parser = _gemini_with(
        {"intent": "query_vehicle", "vehicle_no": "101", "confidence": 0.9}
    )
    parser.parse("101番どうなってる")
    config = parser._client.models.calls[0]["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is not None
    assert config.temperature == 0.0
    assert "中古車販売店" in config.system_instruction


# ---------------------------------------------------------------- POST /api/parse


def test_解析APIは正規化済みの意図を返す(client, users) -> None:
    """SPEC §8.2 のレスポンス契約。"""
    response = client.post(
        "/api/parse",
        json={"text": "イチマルイチ番の車、今どうなってる？"},
        headers=auth(users["sato"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "query_vehicle"
    assert body["params"] == {"vehicle_no": "101", "note": None}
    assert body["missing"] == []
    assert 0.0 <= body["confidence"] <= 1.0
    # raw_text はバックエンドが埋め戻す（SPEC §7.3）
    assert body["raw_text"] == "イチマルイチ番の車、今どうなってる？"


def test_解析APIは書き込み意図でもDBを変更しない(client, users, reload_vehicle, vehicle) -> None:
    """SPEC §8.2：解析のみ。副作用は一切発生しない。"""
    before = reload_vehicle("101")
    before_status, before_version = before.status, before.version
    response = client.post(
        "/api/parse",
        json={"text": "101番を商談中にして"},
        headers=auth(users["sato"]),
    )
    assert response.status_code == 200
    assert response.json()["intent"] == "lock_vehicle"
    after = reload_vehicle("101")
    assert (after.status, after.version) == (before_status, before_version)


def test_解析APIは存在しない番号でも200を返す(client, users) -> None:
    """存在確認は後続の GET /api/vehicles/{no} の責務（SPEC §7.5）。"""
    response = client.post(
        "/api/parse", json={"text": "9999番どうなってる"}, headers=auth(users["sato"])
    )
    assert response.status_code == 200
    assert response.json()["params"]["vehicle_no"] == "9999"


def test_解析APIは担当者ヘッダーが無ければ401(client, users) -> None:
    """SPEC §3：X-User-Id は /api/users 以外の全リクエストに必要。"""
    response = client.post("/api/parse", json={"text": "101番どうなってる"})
    assert response.status_code == 401
    assert response.json()["code"] == "NO_IDENTITY"


def test_解析APIは空文字をunknownとして返す(client, users) -> None:
    """空入力でもエラーにはしない。"""
    response = client.post(
        "/api/parse", json={"text": ""}, headers=auth(users["sato"])
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "unknown"
    assert body["confidence"] == 0.0
