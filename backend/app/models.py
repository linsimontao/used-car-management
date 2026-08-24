"""SQLAlchemy モデル（SPEC §4）。

DB に格納する enum 値は英語、画面表示のラベルは日本語（SPEC §1.2）。
日時カラムは全て ISO8601 UTC の文字列として保持する。
"""

from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """全モデルの基底クラス。Alembic の autogenerate はこのメタデータを参照する。"""


class VehicleStatus(StrEnum):
    """車両ステータス（SPEC §4.2）。"""

    IN_STOCK = "IN_STOCK"
    NEGOTIATING = "NEGOTIATING"
    SOLD = "SOLD"


# ステータスの表示ラベル対応表（SPEC §4.2）
STATUS_LABELS: dict[str, str] = {
    VehicleStatus.IN_STOCK: "在庫",
    VehicleStatus.NEGOTIATING: "商談中",
    VehicleStatus.SOLD: "売却済",
}


class UserRole(StrEnum):
    """担当者のロール（SPEC §3）。"""

    STAFF = "staff"
    ADMIN = "admin"


class EventType(StrEnum):
    """イベント種別（SPEC §4.3）。"""

    LOCKED = "locked"
    UNLOCKED = "unlocked"
    FORCE_UNLOCKED = "force_unlocked"
    LOCK_EXPIRED = "lock_expired"
    LOCK_RENEWED = "lock_renewed"
    SOLD = "sold"
    UNSOLD = "unsold"


class User(Base):
    """担当者（SPEC §4.1）。"""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('staff', 'admin')", name="ck_users_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 表示名（例：「佐藤 健」）
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    # 退職者は 0 にして選択肢から除外する
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    # ISO8601 UTC
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class Vehicle(Base):
    """車両（SPEC §4.2）。

    不変条件（実装が保証すること）：
      - status = 'NEGOTIATING' ⟺ locked_by IS NOT NULL AND lock_expires_at IS NOT NULL
      - status = 'IN_STOCK' / 'SOLD' ⟹ ロック関連3フィールドは全て NULL
      - version は全ての書き込み成功後に 1 増加する（遅延期限切れ書き戻しを含む）
    """

    __tablename__ = "vehicles"
    __table_args__ = (
        CheckConstraint(
            "status IN ('IN_STOCK', 'NEGOTIATING', 'SOLD')", name="ck_vehicles_status"
        ),
        Index("idx_vehicles_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 管理番号：3〜4桁の数字文字列（例："101" / "2035"）
    vehicle_no: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    maker: Mapped[str] = mapped_column(Text, nullable=False)  # メーカー（例：「トヨタ」）
    model: Mapped[str] = mapped_column(Text, nullable=False)  # 車種・グレード
    model_year: Mapped[int] = mapped_column(Integer, nullable=False)  # 初度登録年（西暦）
    mileage_km: Mapped[int] = mapped_column(Integer, nullable=False)  # 走行距離（km）
    color: Mapped[str] = mapped_column(Text, nullable=False)  # ボディカラー
    displacement: Mapped[str | None] = mapped_column(Text)  # 排気量（例：「1.8L」）
    price_yen: Mapped[int] = mapped_column(Integer, nullable=False)  # 車両本体価格（円）
    # 車検満了日（YYYY-MM-DD）。車検切れは NULL
    shaken_expires_on: Mapped[str | None] = mapped_column(Text)
    # 修復歴の有無
    repair_history: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    location: Mapped[str | None] = mapped_column(Text)  # 展示場所（例：「A区画 3番」）
    remark: Mapped[str | None] = mapped_column(Text)  # 車両状態に関する備考

    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=VehicleStatus.IN_STOCK, server_default="IN_STOCK"
    )

    # ロック情報：3フィールドは常に運命を共にする（全て NULL か、全て値を持つか）
    locked_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    locked_at: Mapped[str | None] = mapped_column(Text)  # ISO8601 UTC
    lock_expires_at: Mapped[str | None] = mapped_column(Text)  # ISO8601 UTC
    lock_note: Mapped[str | None] = mapped_column(Text)  # ロック時のメモ

    # 楽観ロックのバージョン番号。書き込みごとに +1
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    locker: Mapped["User | None"] = relationship("User", lazy="joined")


class VehicleEvent(Base):
    """イベント履歴（SPEC §4.3）。追記のみの不変ログ。"""

    __tablename__ = "vehicle_events"
    __table_args__ = (Index("idx_events_vehicle", "vehicle_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("vehicles.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    # システムによる自動処理（期限切れ）の場合は NULL
    actor_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str | None] = mapped_column(Text)
    # ユーザーの入力原文。非音声経路からの操作では NULL
    raw_text: Mapped[str | None] = mapped_column(Text)
    # LLM が返した JSON 全体の文字列。非音声経路では NULL
    parsed_intent: Mapped[str | None] = mapped_column(Text)
    # 補足（強制解除の理由、メモの内容など）
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    actor: Mapped["User | None"] = relationship("User", lazy="joined")
