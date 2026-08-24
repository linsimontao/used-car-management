"""ロック操作の状態遷移（SPEC §5、§6）。

全ての書き込みは「条件付き UPDATE + version による楽観ロック」で行う。
rowcount == 0 の場合は該当行を再読み込みして原因を特定し、
的確なエラー（VEHICLE_NOT_FOUND / VEHICLE_LOCKED / INVALID_TRANSITION /
VERSION_CONFLICT）に振り分ける（SPEC §6.2）。

「SELECT で前提を確認してから UPDATE」は決して書かない。
前提条件は必ず UPDATE の WHERE 句に入れる。
"""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import clock
from app.config import get_settings
from app.db import immediate_transaction
from app.errors import (
    AppError,
    ForceRequiredError,
    InvalidTransitionError,
    NotLockOwnerError,
    VehicleLockedError,
    VehicleNotFoundError,
    VersionConflictError,
)
from app.models import EventType, User, UserRole, Vehicle, VehicleStatus
from app.services import event_service, vehicle_service

settings = get_settings()


def lock(
    db: Session,
    vehicle_no: str,
    actor: User,
    version: int,
    note: str | None = None,
    raw_text: str | None = None,
    parsed_intent: str | None = None,
) -> Vehicle:
    """T1 ロック／T5 延長（SPEC §8.4）。

    - 在庫 → ロック（イベント locked）
    - 商談中かつ locked_by == 実行者 → 延長（イベント lock_renewed）
    - 商談中かつ他人のロック → 409 VEHICLE_LOCKED
    - 売却済 → 409 INVALID_TRANSITION
    """
    vehicle_service.expire_if_needed(db, vehicle_no)
    now = clock.now_utc()
    now_iso = clock.to_iso(now)
    expires_at = clock.plus_minutes_iso(settings.lock_ttl_minutes, base=now)

    # T1 と T5 のどちらを撃つかを決めるためだけの読み取り。
    # 前提条件は UPDATE の WHERE に入っているので、この値が古くても安全側に倒れる
    current = vehicle_service.get_vehicle(db, vehicle_no)
    is_renewal = (
        current.status == VehicleStatus.NEGOTIATING and current.locked_by == actor.id
    )

    with immediate_transaction(db) as tx:
        if is_renewal:
            # T5 延長：locked_at は初回のまま。note は指定があれば上書き
            result = tx.execute(
                update(Vehicle)
                .where(
                    Vehicle.vehicle_no == vehicle_no,
                    Vehicle.status == VehicleStatus.NEGOTIATING,
                    Vehicle.locked_by == actor.id,
                    Vehicle.version == version,
                )
                .values(
                    lock_expires_at=expires_at,
                    lock_note=note if note is not None else Vehicle.lock_note,
                    version=Vehicle.version + 1,
                    updated_at=now_iso,
                )
            )
        else:
            # T1 ロック：在庫であることを WHERE で保証する
            result = tx.execute(
                update(Vehicle)
                .where(
                    Vehicle.vehicle_no == vehicle_no,
                    Vehicle.status == VehicleStatus.IN_STOCK,
                    Vehicle.version == version,
                )
                .values(
                    status=VehicleStatus.NEGOTIATING,
                    locked_by=actor.id,
                    locked_at=now_iso,
                    lock_expires_at=expires_at,
                    lock_note=note,
                    version=Vehicle.version + 1,
                    updated_at=now_iso,
                )
            )

        if result.rowcount == 0:
            raise _diagnose(
                tx,
                vehicle_no,
                actor,
                version,
                sold_message="売却済の車両は商談中にできません",
            )

        event_service.record(
            tx,
            vehicle_id=current.id,
            event_type=EventType.LOCK_RENEWED if is_renewal else EventType.LOCKED,
            actor_id=actor.id,
            from_status=VehicleStatus.NEGOTIATING
            if is_renewal
            else VehicleStatus.IN_STOCK,
            to_status=VehicleStatus.NEGOTIATING,
            raw_text=raw_text,
            parsed_intent=parsed_intent,
            detail=note,
        )

    return vehicle_service.get_vehicle(db, vehicle_no)


def unlock(
    db: Session,
    vehicle_no: str,
    actor: User,
    version: int,
    force: bool = False,
    reason: str | None = None,
    raw_text: str | None = None,
    parsed_intent: str | None = None,
) -> Vehicle:
    """T2 解除／T3 強制解除（SPEC §8.4）。

    - 実行者 == locked_by → 解除（イベント unlocked）
    - 実行者 != locked_by かつ admin かつ force == true → 強制解除（force_unlocked）
    - 実行者 != locked_by かつ admin でない → 403 NOT_LOCK_OWNER
    - admin だが force != true → 409 FORCE_REQUIRED
    - 商談中でない → 409 INVALID_TRANSITION
    """
    vehicle_service.expire_if_needed(db, vehicle_no)
    now_iso = clock.now_iso()

    # 権限判定は UPDATE の前に行う。どのエラーを返すか、
    # メッセージに誰の名前を出すかを決めるためにロック所有者の情報が要る
    current = vehicle_service.get_vehicle(db, vehicle_no)
    if current.status != VehicleStatus.NEGOTIATING:
        raise InvalidTransitionError("この車両は商談中ではありません")

    is_owner = current.locked_by == actor.id
    if not is_owner:
        if actor.role != UserRole.ADMIN:
            raise NotLockOwnerError(
                f"この車両は{current.locker.name}さんが商談中のため操作できません",
                detail={"locked_by_name": current.locker.name},
            )
        if not force:
            raise ForceRequiredError(
                f"{current.locker.name}さんのロックを強制的に解除しますか？",
                detail={"locked_by_name": current.locker.name},
            )

    with immediate_transaction(db) as tx:
        conditions = [
            Vehicle.vehicle_no == vehicle_no,
            Vehicle.status == VehicleStatus.NEGOTIATING,
            Vehicle.version == version,
        ]
        if is_owner:
            # T2：所有者本人であることも WHERE で保証する
            conditions.append(Vehicle.locked_by == actor.id)

        result = tx.execute(
            update(Vehicle)
            .where(*conditions)
            .values(vehicle_service.released_values(now_iso))
        )
        if result.rowcount == 0:
            raise _diagnose(
                tx,
                vehicle_no,
                actor,
                version,
                sold_message="売却済の車両は解除できません",
            )

        event_service.record(
            tx,
            vehicle_id=current.id,
            event_type=EventType.UNLOCKED if is_owner else EventType.FORCE_UNLOCKED,
            actor_id=actor.id,
            from_status=VehicleStatus.NEGOTIATING,
            to_status=VehicleStatus.IN_STOCK,
            raw_text=raw_text,
            parsed_intent=parsed_intent,
            detail=reason,
        )

    return vehicle_service.get_vehicle(db, vehicle_no)


def mark_sold(
    db: Session,
    vehicle_no: str,
    actor: User,
    version: int,
    raw_text: str | None = None,
    parsed_intent: str | None = None,
) -> Vehicle:
    """T6 / T7 売却済（SPEC §8.4）。商談中からの遷移ではロック関連フィールドもクリアする。"""
    raise NotImplementedError("骨組みのみ。実装は次段階")


def mark_unsold(
    db: Session,
    vehicle_no: str,
    actor: User,
    version: int,
    reason: str | None = None,
    raw_text: str | None = None,
    parsed_intent: str | None = None,
) -> Vehicle:
    """T8 売却済の取り消し（admin のみ。SPEC §8.4）。"""
    raise NotImplementedError("骨組みのみ。実装は次段階")


def _diagnose(
    db: Session,
    vehicle_no: str,
    actor: User,
    client_version: int,
    sold_message: str,
) -> AppError:
    """rowcount == 0 の原因を特定して返すべきエラーを組み立てる（SPEC §6.2）。

    条件付き UPDATE が 0 件だった理由は「行が無い」「状態が違う」「version が古い」
    のいずれか。ここで該当行を再読み込みして振り分ける。
    """
    vehicle = (
        db.scalars(
            select(Vehicle)
            .where(Vehicle.vehicle_no == vehicle_no)
            .execution_options(populate_existing=True)
        )
        .unique()
        .one_or_none()
    )
    if vehicle is None:
        return VehicleNotFoundError(f"{vehicle_no}番の車両は登録されていません")
    if vehicle.status == VehicleStatus.SOLD:
        return InvalidTransitionError(sold_message)
    if vehicle.status == VehicleStatus.NEGOTIATING and vehicle.locked_by != actor.id:
        return _locked_error(vehicle)
    if vehicle.version != client_version:
        return VersionConflictError()
    # 状態も version も合っているのに 0 件だった場合（許可されない遷移）
    return InvalidTransitionError("現在の状態ではこの操作はできません")


def _locked_error(vehicle: Vehicle) -> VehicleLockedError:
    """他人のロックに対する 409 VEHICLE_LOCKED を組み立てる（SPEC §5.2）。

    担当者同士がその場で調整できるよう、所有者の氏名と残り分数を必ず含める。
    """
    remaining = clock.remaining_minutes(vehicle.lock_expires_at)
    name = vehicle.locker.name
    return VehicleLockedError(
        f"{vehicle.vehicle_no}番の車両は{name}さんが商談中です（残り{remaining}分）",
        detail={"locked_by_name": name, "remaining_minutes": remaining},
    )
