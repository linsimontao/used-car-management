"""番号正規化の境界値テスト（SPEC §11）。

漢数字、カナ読み（イチマルイチ）、全角、「番の車」等の接尾辞、
位取り読み、不正入力で None になること。
"""

import pytest

pytestmark = pytest.mark.skip(reason="骨組みのみ。実装は次段階")


def test_カナ読みを数字に変換する() -> None:
    """「イチマルイチ番の車」→ "101"。"""
