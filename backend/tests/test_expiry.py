"""遅延期限切れ書き戻しのテスト（SPEC §5.3）。

期限切れロックを作った上で GET を呼ぶと、DB 上の status が IN_STOCK になり
lock_expired イベントが存在すること。
"""

from sqlalchemy.orm import Session

from tests.conftest import auth, make_expired_lock, make_vehicle


def test_期限切れロックはGET時に解放される(
    client, db: Session, users, vehicle, reload_vehicle, events_of
) -> None:
    """遅延書き戻しにより DB が正しい現在状態になる。"""
    make_expired_lock(db, vehicle, users["sato"])
    before_version = vehicle.version

    body = client.get("/api/vehicles/101", headers=auth(users["suzuki"])).json()

    assert body["status"] == "IN_STOCK"
    assert body["lock"] is None
    # バックグラウンドタスクは無く、DB を直接 SELECT した結果が正しい現在状態になる
    released = reload_vehicle("101")
    assert released.status == "IN_STOCK"
    assert released.locked_by is None
    assert released.lock_expires_at is None
    # 書き戻しでも version は 1 増える
    assert released.version == before_version + 1

    events = events_of("101")
    assert [e.event_type for e in events] == ["lock_expired"]
    # システムによる自動処理なので実行者は無い
    assert events[0].actor_id is None


def test_期限切れロックは一覧取得時に一括解放される(
    client, db: Session, users, vehicle, reload_vehicle, events_of
) -> None:
    """一覧 API も検索前に一括で期限切れ処理を行う（SPEC §5.3）。"""
    other = make_vehicle(db, "205", maker="日産", model="ノート e-POWER X")
    make_expired_lock(db, vehicle, users["sato"])
    make_expired_lock(db, other, users["suzuki"])

    body = client.get(
        "/api/vehicles", params={"status": "IN_STOCK"}, headers=auth(users["tanaka"])
    ).json()

    assert [v["vehicle_no"] for v in body["items"]] == ["101", "205"]
    assert reload_vehicle("101").status == "IN_STOCK"
    assert reload_vehicle("205").status == "IN_STOCK"
    assert [e.event_type for e in events_of("101")] == ["lock_expired"]
    assert [e.event_type for e in events_of("205")] == ["lock_expired"]


def test_期限切れ後は別の担当者がロックできる(
    client, db: Session, users, vehicle, reload_vehicle
) -> None:
    """期限切れロックは他人のロックを妨げない。"""
    make_expired_lock(db, vehicle, users["sato"])
    current = reload_vehicle("101")

    response = client.post(
        "/api/vehicles/101/lock",
        json={"version": current.version + 1},  # 期限切れ書き戻しで version が 1 進む
        headers=auth(users["suzuki"]),
    )

    assert response.status_code == 200
    assert response.json()["lock"]["locked_by"]["name"] == "鈴木 美咲"
