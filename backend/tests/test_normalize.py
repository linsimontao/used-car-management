"""番号正規化の境界値テスト（SPEC §11）。

漢数字、カナ読み（イチマルイチ）、全角、「番の車」等の接尾辞、
位取り読み、不正入力で None になること。
"""

import pytest

from app.llm.normalize import normalize_vehicle_no


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("イチマルイチ", "101"),
        ("イチマルイチ番の車", "101"),
        ("ニーゼロゴ", "205"),
        ("サンイチマル", "310"),
        ("にせんさんじゅうご", "2035"),
        ("いちまるいち", "101"),
    ],
)
def test_カナ読みを数字に変換する(raw: str, expected: str) -> None:
    """「イチマルイチ番の車」→ "101"。"""
    assert normalize_vehicle_no(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("一〇一番", "101"),
        ("二〇三五", "2035"),
        ("三一〇", "310"),
        ("二零五", "205"),
    ],
)
def test_漢数字を数字に変換する(raw: str, expected: str) -> None:
    """「一〇一番」→ "101"。"""
    assert normalize_vehicle_no(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("１０１", "101"),
        ("２０３５番", "2035"),
        ("１０１番の車", "101"),
    ],
)
def test_全角数字を半角に変換する(raw: str, expected: str) -> None:
    """全角で入力された番号も半角として扱う。"""
    assert normalize_vehicle_no(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["101番", "101番の車", "101号車", "101番車", "101の車", "101さん", "101"],
)
def test_接尾辞と指示語を除去する(raw: str) -> None:
    """「番」「番の車」「号車」等が付いていても同じ番号になる。"""
    assert normalize_vehicle_no(raw) == "101"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ひゃくいちばん", "101"),
        ("にせんさんじゅうご", "2035"),
        ("さんびゃくじゅう", "310"),
        ("はっぴゃくろくじゅうに", "862"),
        ("百一番", "101"),
        ("二千三十五", "2035"),
    ],
)
def test_位取りの読みを解決する(raw: str, expected: str) -> None:
    """「ひゃく」は100の位、「せん」は1000の位として解決する（SPEC §7.5-4）。"""
    assert normalize_vehicle_no(raw) == expected


def test_数字の読みとしてのさんは敬称として除去しない() -> None:
    """「いちまるさん」は 103 であって「いちまる」＋敬称ではない。"""
    assert normalize_vehicle_no("いちまるさん") == "103"


@pytest.mark.parametrize("raw", ["101畦", "101台", "101番です"])
def test_変換後に残った漢字は無視する(raw: str) -> None:
    """LLM が「番」を字形の近い漢字として返す事象を吸収する（実測あり）。"""
    assert normalize_vehicle_no(raw) == "101"


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "あの車",
        "12",  # 2桁は不正
        "12345",  # 5桁は不正
        "そこの白いプリウス",
        "番号わかりません",
    ],
)
def test_正規化できない入力はNoneを返す(raw: str | None) -> None:
    """3〜4桁の数字にならない場合は None（呼び出し元が missing に積む）。"""
    assert normalize_vehicle_no(raw) is None
