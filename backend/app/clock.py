"""日時の生成と比較（SPEC §8）。

DB に保持する日時は全て ISO8601 UTC の**固定長**文字列（秒精度）とする。
`lock_expires_at` の期限切れ判定は TEXT 列に対する文字列比較で行うため、
桁数が揺れると辞書順と時系列順が一致しなくなる。フォーマットはこの1箇所に閉じる。
"""

from datetime import UTC, datetime, timedelta
from math import ceil

# 例："2026-08-23T02:10:00Z"
ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def now_utc() -> datetime:
    """現在時刻（UTC、tz-aware）。"""
    return datetime.now(UTC)


def to_iso(dt: datetime) -> str:
    """datetime を固定長の ISO8601 UTC 文字列に変換する。"""
    return dt.astimezone(UTC).strftime(ISO_FORMAT)


def from_iso(value: str) -> datetime:
    """ISO8601 UTC 文字列を tz-aware な datetime に戻す。"""
    return datetime.strptime(value, ISO_FORMAT).replace(tzinfo=UTC)


def now_iso() -> str:
    """現在時刻の ISO8601 UTC 文字列。"""
    return to_iso(now_utc())


def plus_minutes_iso(minutes: int, base: datetime | None = None) -> str:
    """base（既定は現在時刻）から minutes 分後の ISO8601 UTC 文字列。"""
    return to_iso((base or now_utc()) + timedelta(minutes=minutes))


def remaining_minutes(expires_at: str, now: datetime | None = None) -> int:
    """ロックの残り分数。

    切り上げにするのは、残り30秒の状態で「残り0分」と表示されるのを避けるため。
    既に期限を過ぎている場合は 0 を返す。
    """
    delta = (from_iso(expires_at) - (now or now_utc())).total_seconds()
    return max(0, ceil(delta / 60))
