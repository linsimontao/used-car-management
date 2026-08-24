"""イベント履歴の記録と取得（SPEC §4.3、§8.5）。

vehicle_events は追記のみの不変ログ。更新・削除は行わない。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import now_iso
from app.models import Vehicle, VehicleEvent


def record(
    db: Session,
    vehicle_id: int,
    event_type: str,
    actor_id: int | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    raw_text: str | None = None,
    parsed_intent: str | None = None,
    detail: str | None = None,
) -> VehicleEvent:
    """イベントを 1 件記録する。呼び出し元のトランザクションに参加する。

    ここでは commit しない。車両の UPDATE と同一トランザクションに載せることで、
    「書き込みが成功したのにイベントが残っていない」状態を作らない。
    """
    event = VehicleEvent(
        vehicle_id=vehicle_id,
        event_type=event_type,
        actor_id=actor_id,
        from_status=from_status,
        to_status=to_status,
        raw_text=raw_text,
        parsed_intent=parsed_intent,
        detail=detail,
        created_at=now_iso(),
    )
    db.add(event)
    db.flush()
    return event


def list_events(db: Session, vehicle_no: str) -> list[VehicleEvent]:
    """車両のイベントタイムラインを時系列で返す。"""
    return list(
        db.scalars(
            select(VehicleEvent)
            .join(Vehicle, Vehicle.id == VehicleEvent.vehicle_id)
            .where(Vehicle.vehicle_no == vehicle_no)
            .order_by(VehicleEvent.created_at, VehicleEvent.id)
        ).all()
    )
