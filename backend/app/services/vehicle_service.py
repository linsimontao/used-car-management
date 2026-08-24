"""車両の照会・一覧・期限切れの遅延書き戻し（SPEC §5.3）。

車両を読み書きする全ての入口で、業務ロジックに入る前に
`expire_if_needed()` を実行すること。これにより
「いかなる時点でも DB を直接 SELECT した結果が正しい現在状態である」
ことが保証される。
"""

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app import clock
from app.config import get_settings
from app.db import immediate_transaction
from app.errors import VehicleNotFoundError
from app.models import STATUS_LABELS, EventType, Vehicle, VehicleStatus
from app.schemas import ActorOut, LockOut, VehicleOut
from app.services import event_service

settings = get_settings()


def to_out(vehicle: Vehicle) -> VehicleOut:
    """車両モデルを API のレスポンス形式へ変換する（SPEC §8.3）。

    読み取り・書き込みを問わず全ての車両レスポンスがこの1箇所を通る。
    lock 部を組み立てるのは status が NEGOTIATING のときだけ。
    """
    lock: LockOut | None = None
    if vehicle.status == VehicleStatus.NEGOTIATING:
        lock = LockOut(
            locked_by=ActorOut(id=vehicle.locker.id, name=vehicle.locker.name),
            locked_at=vehicle.locked_at,
            expires_at=vehicle.lock_expires_at,
            remaining_minutes=clock.remaining_minutes(vehicle.lock_expires_at),
            note=vehicle.lock_note,
        )
    return VehicleOut(
        vehicle_no=vehicle.vehicle_no,
        maker=vehicle.maker,
        model=vehicle.model,
        model_year=vehicle.model_year,
        mileage_km=vehicle.mileage_km,
        color=vehicle.color,
        displacement=vehicle.displacement,
        price_yen=vehicle.price_yen,
        shaken_expires_on=vehicle.shaken_expires_on,
        repair_history=vehicle.repair_history,
        location=vehicle.location,
        remark=vehicle.remark,
        status=vehicle.status,
        status_label=STATUS_LABELS[vehicle.status],
        lock=lock,
        version=vehicle.version,
        updated_at=vehicle.updated_at,
    )


def expire_if_needed(db: Session, vehicle_no: str) -> bool:
    """単一車両の期限切れロックを解放する（SPEC §5.3、T4）。

    BEGIN IMMEDIATE の中で status / lock_expires_at / version を読み、
    期限切れなら version 条件付き UPDATE で IN_STOCK に戻し、
    lock_expired イベントを記録する。戻り値は解放したかどうか。
    """
    now = clock.now_iso()
    with immediate_transaction(db) as tx:
        row = tx.execute(
            select(Vehicle.id, Vehicle.lock_expires_at, Vehicle.version).where(
                Vehicle.vehicle_no == vehicle_no,
                Vehicle.status == VehicleStatus.NEGOTIATING,
            )
        ).one_or_none()
        # 対象外（存在しない／商談中でない／期限内）なら何もしない
        if row is None or row.lock_expires_at > now:
            return False

        result = tx.execute(
            update(Vehicle)
            .where(Vehicle.id == row.id, Vehicle.version == row.version)
            .values(released_values(now))
        )
        if result.rowcount == 0:
            # 直前に他の経路が更新した。その経路が正しい状態を書いているので何もしない
            return False

        event_service.record(
            tx,
            vehicle_id=row.id,
            event_type=EventType.LOCK_EXPIRED,
            actor_id=None,  # システムによる自動処理
            from_status=VehicleStatus.NEGOTIATING,
            to_status=VehicleStatus.IN_STOCK,
        )
    db.expire_all()
    return True


def expire_all_if_needed(db: Session) -> int:
    """一覧 API 用の一括期限切れ処理（SPEC §5.3）。

    対象行の id を集めてから一括 UPDATE し、同一トランザクションで
    lock_expired イベントをまとめて INSERT する。戻り値は解放した件数。
    """
    now = clock.now_iso()
    with immediate_transaction(db) as tx:
        expired_ids = list(
            tx.scalars(
                select(Vehicle.id).where(
                    Vehicle.status == VehicleStatus.NEGOTIATING,
                    Vehicle.lock_expires_at <= now,
                )
            ).all()
        )
        if not expired_ids:
            return 0

        tx.execute(
            update(Vehicle)
            .where(Vehicle.id.in_(expired_ids))
            .values(released_values(now))
        )
        for vehicle_id in expired_ids:
            event_service.record(
                tx,
                vehicle_id=vehicle_id,
                event_type=EventType.LOCK_EXPIRED,
                actor_id=None,
                from_status=VehicleStatus.NEGOTIATING,
                to_status=VehicleStatus.IN_STOCK,
            )
    db.expire_all()
    return len(expired_ids)


def released_values(now: str) -> dict:
    """ロックを解放して在庫に戻すときの更新値。

    ロック関連4フィールドは常に運命を共にするため、必ずまとめて NULL にする。
    """
    return {
        "status": VehicleStatus.IN_STOCK,
        "locked_by": None,
        "locked_at": None,
        "lock_expires_at": None,
        "lock_note": None,
        "version": Vehicle.version + 1,
        "updated_at": now,
    }


def get_vehicle(db: Session, vehicle_no: str) -> Vehicle:
    """管理番号で車両を 1 件取得する。存在しなければ VEHICLE_NOT_FOUND。

    populate_existing で必ず DB の最新値を読み直す。Core の UPDATE は
    Session の identity map を更新しないため、これを怠ると古い version を返す。
    """
    vehicle = db.scalars(
        select(Vehicle)
        .where(Vehicle.vehicle_no == vehicle_no)
        .execution_options(populate_existing=True)
    ).unique().one_or_none()
    if vehicle is None:
        raise VehicleNotFoundError(f"{vehicle_no}番の車両は登録されていません")
    return vehicle


def list_vehicles(
    db: Session,
    status: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[int, list[Vehicle]]:
    """車両一覧を返す（SPEC §8.3）。戻り値は (総件数, 該当ページの車両)。"""
    conditions = []
    if status is not None:
        conditions.append(Vehicle.status == status)
    if q:
        pattern = f"%{q}%"
        conditions.append(
            or_(
                Vehicle.vehicle_no.like(pattern),
                Vehicle.maker.like(pattern),
                Vehicle.model.like(pattern),
            )
        )

    # total はページング前の件数
    total = db.scalar(select(func.count()).select_from(Vehicle).where(*conditions)) or 0
    items = (
        db.scalars(
            select(Vehicle)
            .where(*conditions)
            .order_by(Vehicle.vehicle_no)
            .limit(page_size)
            .offset((page - 1) * page_size)
            .execution_options(populate_existing=True)
        )
        .unique()
        .all()
    )
    return total, list(items)
