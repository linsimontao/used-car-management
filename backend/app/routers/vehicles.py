"""車両 API（SPEC §8.3〜§8.5）。

読み書きいずれの入口でも、業務ロジックに入る前に
vehicle_service.expire_if_needed() を実行すること（SPEC §5.3）。
"""

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.deps import CurrentUser, DbSession
from app.errors import InvalidVehicleNoError
from app.schemas import (
    LockRequest,
    SoldRequest,
    UnlockRequest,
    UnsoldRequest,
    VehicleEventOut,
    VehicleListOut,
    VehicleOut,
)
from app.services import lock_service, vehicle_service

router = APIRouter(prefix="/api/vehicles", tags=["vehicles"])

# 管理番号は3〜4桁の数字（SPEC §7.5）
VEHICLE_NO_PATTERN = re.compile(r"^\d{3,4}$")


def _validate_vehicle_no(vehicle_no: str) -> str:
    """管理番号の形式を検証する。不正なら DB を引かずに 400 を返す。"""
    if not VEHICLE_NO_PATTERN.match(vehicle_no):
        raise InvalidVehicleNoError()
    return vehicle_no


@router.get("", response_model=VehicleListOut)
def list_vehicles(
    db: DbSession,
    user: CurrentUser,
    status: Annotated[Literal["IN_STOCK", "NEGOTIATING", "SOLD"] | None, Query()] = None,
    q: Annotated[str | None, Query(description="管理番号・メーカー・車種の部分一致")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> VehicleListOut:
    """車両一覧。検索前に一括で期限切れ処理を行う。"""
    vehicle_service.expire_all_if_needed(db)
    total, vehicles = vehicle_service.list_vehicles(
        db, status=status, q=q, page=page, page_size=page_size
    )
    return VehicleListOut(
        total=total, items=[vehicle_service.to_out(v) for v in vehicles]
    )


@router.get("/{vehicle_no}", response_model=VehicleOut)
def get_vehicle(vehicle_no: str, db: DbSession, user: CurrentUser) -> VehicleOut:
    """単一車両の詳細。フロントはここで version を取得する（SPEC §6.4）。"""
    _validate_vehicle_no(vehicle_no)
    vehicle_service.expire_if_needed(db, vehicle_no)
    return vehicle_service.to_out(vehicle_service.get_vehicle(db, vehicle_no))


@router.post("/{vehicle_no}/lock", response_model=VehicleOut)
def lock_vehicle(
    vehicle_no: str, body: LockRequest, db: DbSession, user: CurrentUser
) -> VehicleOut:
    """T1 ロック／T5 延長。"""
    _validate_vehicle_no(vehicle_no)
    vehicle = lock_service.lock(
        db,
        vehicle_no,
        actor=user,
        version=body.version,
        note=body.note,
        raw_text=body.raw_text,
        parsed_intent=body.parsed_intent,
    )
    return vehicle_service.to_out(vehicle)


@router.post("/{vehicle_no}/unlock", response_model=VehicleOut)
def unlock_vehicle(
    vehicle_no: str, body: UnlockRequest, db: DbSession, user: CurrentUser
) -> VehicleOut:
    """T2 解除／T3 強制解除（admin かつ force=true）。"""
    _validate_vehicle_no(vehicle_no)
    vehicle = lock_service.unlock(
        db,
        vehicle_no,
        actor=user,
        version=body.version,
        force=body.force,
        reason=body.reason,
        raw_text=body.raw_text,
        parsed_intent=body.parsed_intent,
    )
    return vehicle_service.to_out(vehicle)


@router.post("/{vehicle_no}/sold", response_model=VehicleOut)
def sell_vehicle(
    vehicle_no: str, body: SoldRequest, db: DbSession, user: CurrentUser
) -> VehicleOut:
    """T6 / T7 売却済。"""
    raise NotImplementedError("骨組みのみ。実装は次段階")


@router.post("/{vehicle_no}/unsold", response_model=VehicleOut)
def unsell_vehicle(
    vehicle_no: str, body: UnsoldRequest, db: DbSession, user: CurrentUser
) -> VehicleOut:
    """T8 売却済の取り消し（admin のみ）。"""
    raise NotImplementedError("骨組みのみ。実装は次段階")


@router.get("/{vehicle_no}/events", response_model=list[VehicleEventOut])
def list_vehicle_events(
    vehicle_no: str, db: DbSession, user: CurrentUser
) -> list[VehicleEventOut]:
    """車両のイベントタイムライン（SPEC §8.5）。MVP ではフロント未対応。"""
    raise NotImplementedError("骨組みのみ。実装は次段階")
