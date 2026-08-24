"""Gemini への実通信を伴う結合テスト（SPEC §7.8）。

`pytest -m integration` を明示したときだけ実行される。既定では skip。
GEMINI_API_KEY が未設定の環境でも安全に skip する。
"""

import pytest

from app.config import get_settings
from app.llm.gemini import GeminiParser

pytestmark = pytest.mark.integration

settings = get_settings()

requires_api_key = pytest.mark.skipif(
    not settings.gemini_api_key, reason="GEMINI_API_KEY が未設定のため skip"
)


@pytest.fixture(scope="module")
def gemini() -> GeminiParser:
    """本番と同じ設定のパーサー。"""
    return GeminiParser(api_key=settings.gemini_api_key, model=settings.gemini_model)


@requires_api_key
@pytest.mark.parametrize(
    ("text", "expected_intent", "expected_no"),
    [
        ("101番の車、今どうなってる？", "query_vehicle", "101"),
        ("イチマルイチの状態教えて", "query_vehicle", "101"),
        ("2035番って空いてる？", "query_vehicle", "2035"),
        ("101番を商談中にして", "lock_vehicle", "101"),
        ("イチマルイチ、押さえといて", "lock_vehicle", "101"),
        ("101番のロック外して", "unlock_vehicle", "101"),
        ("イチマルイチ、商談終わりました", "unlock_vehicle", "101"),
        ("101番、売れました", "mark_sold", "101"),
        ("イチマルイチ、ご成約です", "mark_sold", "101"),
        ("ひゃくいちばんの車、押さえておいて", "lock_vehicle", "101"),
    ],
)
def test_実通信で代表的な発話を解析できる(
    gemini: GeminiParser, text: str, expected_intent: str, expected_no: str
) -> None:
    """SPEC §7.2 の発話例が意図・番号ともに正しく解析されること。"""
    result = gemini.parse(text)
    assert result.intent == expected_intent
    assert result.vehicle_no == expected_no
    assert result.missing == []
    assert result.confidence > 0.0


@requires_api_key
def test_実通信で番号の無い発話はmissingになる(gemini: GeminiParser) -> None:
    """述べられていない番号を推測してはならない（SPEC §7.7）。"""
    result = gemini.parse("さっきの車、商談中にしておいて")
    assert result.vehicle_no is None
    assert result.missing == ["vehicle_no"]


@requires_api_key
def test_実通信で無関係な発話はunknownになる(gemini: GeminiParser) -> None:
    """業務と無関係な発話は認識不能として返す。"""
    assert gemini.parse("今日の東京の天気を教えて").intent == "unknown"


@requires_api_key
def test_実通信で商談メモを取り出せる(gemini: GeminiParser) -> None:
    """lock_vehicle のときは商談相手を note に記録する。"""
    result = gemini.parse("101番、田中様と商談中です")
    assert result.intent == "lock_vehicle"
    assert result.vehicle_no == "101"
    assert result.note is not None and "田中" in result.note


@requires_api_key
@pytest.mark.parametrize(
    ("text", "expected_intent", "expected_no"),
    [
        ("イチマルイチじゃなくて、ニーゼロゴを押さえて", "lock_vehicle", "205"),
        ("ニーゼロゴじゃなくて、サンイチマルのほうをキープして", "lock_vehicle", "310"),
        ("310番じゃなくて2035番の状態教えて", "query_vehicle", "2035"),
    ],
)
def test_実通信で言い直しは後の番号を採用する(
    gemini: GeminiParser, text: str, expected_intent: str, expected_no: str
) -> None:
    """「AじゃなくてB」は B を採る。誤った車両を掴むと同僚の商談を壊す。"""
    result = gemini.parse(text)
    assert result.intent == expected_intent
    assert result.vehicle_no == expected_no


@requires_api_key
@pytest.mark.parametrize("text", ["12番の車どうなってる", "45番って空いてる？"])
def test_実通信で桁数の合わない番号は確信度を下げる(gemini: GeminiParser, text: str) -> None:
    """管理番号は3〜4桁。2桁は聞き取り誤りとして低い確信度で返す（SPEC §7.6）。"""
    result = gemini.parse(text)
    assert result.vehicle_no is None
    assert result.missing == ["vehicle_no"]
    assert result.confidence < settings.low_confidence_threshold


@requires_api_key
def test_実通信で商談の取りやめはロック解除と解釈する(gemini: GeminiParser) -> None:
    """「やっぱりやめて」は unlock。曖昧なため確信度は控えめでよい。"""
    result = gemini.parse("101番、やっぱりやめて")
    assert result.intent == "unlock_vehicle"
    assert result.vehicle_no == "101"


@requires_api_key
def test_実通信で所有者による再ロックは延長として解釈される(gemini: GeminiParser) -> None:
    """再 lock は T5 の延長。意図としては lock_vehicle で表現する（SPEC §5.2）。"""
    result = gemini.parse("イチマルイチの商談、そのまま続けます")
    assert result.intent == "lock_vehicle"
    assert result.vehicle_no == "101"


@requires_api_key
def test_実通信でロック時間の指定は解釈しない(gemini: GeminiParser) -> None:
    """TTL は固定であり、発話による指定は受け付けない（SPEC §5.2）。"""
    result = gemini.parse("101番、1時間だけ押さえておいて")
    assert result.intent == "lock_vehicle"
    assert result.vehicle_no == "101"
