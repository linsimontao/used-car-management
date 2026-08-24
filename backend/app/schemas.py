"""Pydantic のリクエスト／レスポンスモデル（SPEC §8）。

API の入出力の形だけを定義する。値の詰め込みは services 層の責務。
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- 担当者


class UserOut(BaseModel):
    """GET /api/users の 1 要素。"""

    id: int
    name: str
    role: Literal["staff", "admin"]


class ActorOut(BaseModel):
    """イベント・ロック情報に埋め込む担当者の最小表現。"""

    id: int
    name: str


# ---------------------------------------------------------------- 解析


class ParseRequest(BaseModel):
    """POST /api/parse のリクエスト。"""

    text: str


class ParseParams(BaseModel):
    """解析結果のパラメータ部（SPEC §7.3）。"""

    # 正規化済みの3〜4桁の数字文字列。特定できない場合は null
    vehicle_no: str | None = None
    note: str | None = None


class ParseResponse(BaseModel):
    """POST /api/parse のレスポンス（SPEC §7.3）。"""

    intent: Literal[
        "query_vehicle", "lock_vehicle", "unlock_vehicle", "mark_sold", "unknown"
    ]
    params: ParseParams
    confidence: float = Field(ge=0.0, le=1.0)
    # 欠落している必須パラメータ名の配列（例：["vehicle_no"]）
    missing: list[str] = Field(default_factory=list)
    # バックエンドが埋め戻す。LLM の出力ではない
    raw_text: str


# ---------------------------------------------------------------- 車両


class LockOut(BaseModel):
    """車両オブジェクトの lock 部（status が IN_STOCK / SOLD の場合は null）。"""

    locked_by: ActorOut
    locked_at: str
    expires_at: str
    remaining_minutes: int
    note: str | None = None


class VehicleOut(BaseModel):
    """車両オブジェクト（SPEC §8.3）。全ての書き込み API もこの形を返す。"""

    vehicle_no: str
    maker: str
    model: str
    model_year: int
    mileage_km: int
    color: str
    displacement: str | None = None
    price_yen: int
    shaken_expires_on: str | None = None
    repair_history: bool
    location: str | None = None
    remark: str | None = None
    status: Literal["IN_STOCK", "NEGOTIATING", "SOLD"]
    status_label: str
    lock: LockOut | None = None
    version: int
    updated_at: str


class VehicleListOut(BaseModel):
    """GET /api/vehicles のレスポンス。"""

    total: int
    items: list[VehicleOut]


# ---------------------------------------------------------------- 書き込み操作


class WriteRequestBase(BaseModel):
    """全ての書き込み API に共通する項目（SPEC §6.2）。

    `version` はクライアントが直前の GET で取得した値で、楽観ロックの検査に使う。
    `raw_text` / `parsed_intent` はイベント履歴への記録用で任意。
    """

    version: int
    raw_text: str | None = None
    parsed_intent: str | None = None


class LockRequest(WriteRequestBase):
    """POST /api/vehicles/{vehicle_no}/lock。"""

    note: str | None = None


class UnlockRequest(WriteRequestBase):
    """POST /api/vehicles/{vehicle_no}/unlock。"""

    # 管理者が他人のロックを強制解除する場合のみ true
    force: bool = False
    reason: str | None = None


class SoldRequest(WriteRequestBase):
    """POST /api/vehicles/{vehicle_no}/sold。"""


class UnsoldRequest(WriteRequestBase):
    """POST /api/vehicles/{vehicle_no}/unsold（admin のみ）。"""

    reason: str | None = None


# ---------------------------------------------------------------- イベント履歴


class VehicleEventOut(BaseModel):
    """GET /api/vehicles/{vehicle_no}/events の 1 要素（SPEC §8.5）。"""

    id: int
    event_type: str
    actor: ActorOut | None = None
    from_status: str | None = None
    to_status: str | None = None
    raw_text: str | None = None
    detail: str | None = None
    created_at: str


# ---------------------------------------------------------------- エラー


class ErrorResponse(BaseModel):
    """エラーレスポンスの形式（SPEC §8.6）。OpenAPI ドキュメント用。"""

    code: str
    message: str
    detail: dict[str, Any] | None = None
