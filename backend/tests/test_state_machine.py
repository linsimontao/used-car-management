"""状態遷移テスト（SPEC §5.1 の T1〜T8 と、拒否されるべき遷移）。

今回の実装範囲は T1（ロック）／T5（延長）／T2（解除）／T3（強制解除）。
"""

from sqlalchemy.orm import Session

from app.clock import plus_minutes_iso
from tests.conftest import auth, make_vehicle


def test_t1_在庫から商談中へロックできる(client, users, vehicle, events_of) -> None:
    """T1：在庫 → 商談中。イベント locked が 1 件記録される。"""
    response = client.post(
        "/api/vehicles/101/lock",
        json={"version": 1, "note": "田中様と商談中", "raw_text": "101番を商談中にして"},
        headers=auth(users["sato"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NEGOTIATING"
    assert body["status_label"] == "商談中"
    assert body["lock"]["locked_by"]["name"] == "佐藤 健"
    assert body["lock"]["note"] == "田中様と商談中"
    # TTL は既定 120 分。切り上げのため 120 か 121 になる
    assert 119 <= body["lock"]["remaining_minutes"] <= 121
    assert body["version"] == 2

    events = events_of("101")
    assert [e.event_type for e in events] == ["locked"]
    assert events[0].from_status == "IN_STOCK"
    assert events[0].to_status == "NEGOTIATING"
    assert events[0].raw_text == "101番を商談中にして"
    assert events[0].actor_id == users["sato"].id


def test_他人がロック中の車両は再ロックできない(
    client, users, vehicle, reload_vehicle
) -> None:
    """商談中の車両を別の担当者が押さえようとすると 409 VEHICLE_LOCKED。

    レスポンスには所有者の氏名と残り分数を含め、担当者同士がその場で調整できるようにする。
    """
    assert (
        client.post(
            "/api/vehicles/101/lock", json={"version": 1}, headers=auth(users["sato"])
        ).status_code
        == 200
    )
    locked = reload_vehicle("101")

    response = client.post(
        "/api/vehicles/101/lock",
        json={"version": locked.version},
        headers=auth(users["suzuki"]),
    )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "VEHICLE_LOCKED"
    assert "佐藤 健" in body["message"]
    assert body["detail"]["locked_by_name"] == "佐藤 健"
    assert body["detail"]["remaining_minutes"] > 0

    # 失敗した側が成功した側のロックを上書きしていないこと（SPEC §6.1）
    after = reload_vehicle("101")
    assert after.locked_by == users["sato"].id
    assert after.version == locked.version


def test_所有者による再ロックは延長になる(
    client, db: Session, users, vehicle, reload_vehicle, events_of
) -> None:
    """T5：所有者本人の再 lock はエラーではなく延長。イベントは lock_renewed。"""
    first = client.post(
        "/api/vehicles/101/lock",
        json={"version": 1, "note": "田中様と商談中"},
        headers=auth(users["sato"]),
    ).json()

    # 秒単位の同時刻で延長差が出ないのを避けるため、期限を手前に縮めておく
    locked = reload_vehicle("101")
    locked.lock_expires_at = plus_minutes_iso(30)
    db.commit()
    shortened_expires = locked.lock_expires_at

    response = client.post(
        "/api/vehicles/101/lock",
        json={"version": locked.version},
        headers=auth(users["sato"]),
    )

    assert response.status_code == 200
    body = response.json()
    # 日時は固定長 ISO8601 なので文字列比較がそのまま時系列比較になる
    assert body["lock"]["expires_at"] > shortened_expires
    # ロック開始時刻は初回のまま。note も指定が無いので据え置き
    assert body["lock"]["locked_at"] == first["lock"]["locked_at"]
    assert body["lock"]["note"] == "田中様と商談中"
    assert body["version"] == locked.version + 1

    events = events_of("101")
    assert [e.event_type for e in events] == ["locked", "lock_renewed"]
    assert events[1].from_status == "NEGOTIATING"
    assert events[1].to_status == "NEGOTIATING"


def test_解除後は再びロックできる(
    client, users, vehicle, reload_vehicle, events_of
) -> None:
    """T2 の後に T1 が通ること。解除でロック関連フィールドが全て NULL になる。"""
    client.post(
        "/api/vehicles/101/lock", json={"version": 1}, headers=auth(users["sato"])
    )
    locked = reload_vehicle("101")

    unlocked = client.post(
        "/api/vehicles/101/unlock",
        json={"version": locked.version},
        headers=auth(users["sato"]),
    )
    assert unlocked.status_code == 200
    assert unlocked.json()["status"] == "IN_STOCK"
    assert unlocked.json()["status_label"] == "在庫"
    assert unlocked.json()["lock"] is None

    # ロック4フィールドは常に運命を共にする
    released = reload_vehicle("101")
    assert released.locked_by is None
    assert released.locked_at is None
    assert released.lock_expires_at is None
    assert released.lock_note is None

    # 別の担当者が改めて押さえられる
    relocked = client.post(
        "/api/vehicles/101/lock",
        json={"version": released.version},
        headers=auth(users["suzuki"]),
    )
    assert relocked.status_code == 200
    assert relocked.json()["lock"]["locked_by"]["name"] == "鈴木 美咲"

    assert [e.event_type for e in events_of("101")] == [
        "locked",
        "unlocked",
        "locked",
    ]


def test_所有者以外の解除は拒否される(client, users, vehicle, reload_vehicle) -> None:
    """staff は他人のロックを解除できない（403 NOT_LOCK_OWNER）。"""
    client.post(
        "/api/vehicles/101/lock", json={"version": 1}, headers=auth(users["sato"])
    )
    locked = reload_vehicle("101")

    response = client.post(
        "/api/vehicles/101/unlock",
        json={"version": locked.version},
        headers=auth(users["suzuki"]),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_LOCK_OWNER"
    assert "佐藤 健" in response.json()["message"]
    assert reload_vehicle("101").status == "NEGOTIATING"


def test_管理者はforce無しでは強制解除できない(
    client, users, vehicle, reload_vehicle
) -> None:
    """admin でも force=true が無ければ 409 FORCE_REQUIRED。"""
    client.post(
        "/api/vehicles/101/lock", json={"version": 1}, headers=auth(users["sato"])
    )
    locked = reload_vehicle("101")

    response = client.post(
        "/api/vehicles/101/unlock",
        json={"version": locked.version},
        headers=auth(users["tanaka"]),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "FORCE_REQUIRED"
    assert "佐藤 健" in response.json()["message"]


def test_t3_管理者はforce付きで強制解除できる(
    client, users, vehicle, reload_vehicle, events_of
) -> None:
    """T3：admin かつ force=true で強制解除。イベント force_unlocked に理由を残す。"""
    client.post(
        "/api/vehicles/101/lock", json={"version": 1}, headers=auth(users["sato"])
    )
    locked = reload_vehicle("101")

    response = client.post(
        "/api/vehicles/101/unlock",
        json={
            "version": locked.version,
            "force": True,
            "reason": "顧客が来店されなかったため",
        },
        headers=auth(users["tanaka"]),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "IN_STOCK"

    events = events_of("101")
    assert [e.event_type for e in events] == ["locked", "force_unlocked"]
    assert events[1].detail == "顧客が来店されなかったため"
    assert events[1].actor_id == users["tanaka"].id


def test_売却済の車両はロックできない(client, db: Session, users) -> None:
    """SOLD からの lock は 409 INVALID_TRANSITION。"""
    make_vehicle(db, "205", status="SOLD")

    response = client.post(
        "/api/vehicles/205/lock", json={"version": 1}, headers=auth(users["sato"])
    )

    assert response.status_code == 409
    assert response.json()["code"] == "INVALID_TRANSITION"


def test_商談中でない車両は解除できない(client, users, vehicle) -> None:
    """在庫の車両への unlock は 409 INVALID_TRANSITION。"""
    response = client.post(
        "/api/vehicles/101/unlock", json={"version": 1}, headers=auth(users["sato"])
    )

    assert response.status_code == 409
    assert response.json()["code"] == "INVALID_TRANSITION"


def test_古いversionでの書き込みは競合になる(client, users, vehicle) -> None:
    """楽観ロック：既に version が進んでいる車両へ古い version で書くと 409。"""
    client.post(
        "/api/vehicles/101/lock", json={"version": 1}, headers=auth(users["sato"])
    )

    # 所有者本人だが version が古い（延長の前提を満たさない）
    response = client.post(
        "/api/vehicles/101/lock", json={"version": 1}, headers=auth(users["sato"])
    )

    assert response.status_code == 409
    assert response.json()["code"] == "VERSION_CONFLICT"
