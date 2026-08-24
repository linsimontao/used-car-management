"""E2E API テスト（MockParser を注入。SPEC §11）。"""

from sqlalchemy.orm import Session

from tests.conftest import auth, make_vehicle


def test_ヘルスチェックが応答する(client) -> None:
    """GET /health が 200 を返す。"""
    assert client.get("/health").json() == {"status": "ok"}


def test_担当者一覧が取得できる(client, users) -> None:
    """GET /api/users は X-User-Id を要求しない（SPEC §8.1）。"""
    response = client.get("/api/users")

    assert response.status_code == 200
    names = [u["name"] for u in response.json()]
    assert names == ["佐藤 健", "鈴木 美咲", "田中 隆"]
    assert response.json()[2]["role"] == "admin"


def test_番号照会で車両の詳細が取得できる(client, users, vehicle) -> None:
    """在庫車の照会。lock は null で、version が返る（SPEC §6.4）。"""
    response = client.get("/api/vehicles/101", headers=auth(users["sato"]))

    assert response.status_code == 200
    body = response.json()
    assert body["vehicle_no"] == "101"
    assert body["maker"] == "トヨタ"
    assert body["model"] == "プリウス S ツーリングセレクション"
    assert body["model_year"] == 2019
    assert body["mileage_km"] == 62000
    assert body["price_yen"] == 1780000
    assert body["status"] == "IN_STOCK"
    assert body["status_label"] == "在庫"
    assert body["lock"] is None
    assert body["version"] == 1


def test_商談中の車両の照会ではロック情報が返る(client, users, vehicle) -> None:
    """商談中なら所有者・期限・残り分数が付く（SPEC §8.3）。"""
    client.post(
        "/api/vehicles/101/lock",
        json={"version": 1, "note": "田中様と商談中"},
        headers=auth(users["sato"]),
    )

    body = client.get("/api/vehicles/101", headers=auth(users["suzuki"])).json()

    assert body["status_label"] == "商談中"
    assert body["lock"]["locked_by"]["name"] == "佐藤 健"
    assert body["lock"]["note"] == "田中様と商談中"
    assert body["lock"]["remaining_minutes"] > 0


def test_存在しない番号は404を返す(client, users) -> None:
    """未登録の管理番号は VEHICLE_NOT_FOUND。"""
    response = client.get("/api/vehicles/999", headers=auth(users["sato"]))

    assert response.status_code == 404
    assert response.json()["code"] == "VEHICLE_NOT_FOUND"
    assert "999番" in response.json()["message"]


def test_管理番号の形式が不正なら400を返す(client, users) -> None:
    """3〜4桁の数字でなければ DB を引かずに INVALID_VEHICLE_NO。"""
    response = client.get("/api/vehicles/12", headers=auth(users["sato"]))

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_VEHICLE_NO"


def test_担当者未選択なら401を返す(client, vehicle) -> None:
    """X-User-Id が無ければ NO_IDENTITY。"""
    response = client.get("/api/vehicles/101")

    assert response.status_code == 401
    assert response.json()["code"] == "NO_IDENTITY"


def test_不正な担当者IDは401を返す(client, vehicle) -> None:
    """数値でない・存在しない X-User-Id も NO_IDENTITY。"""
    assert (
        client.get("/api/vehicles/101", headers={"X-User-Id": "abc"}).status_code == 401
    )
    assert (
        client.get("/api/vehicles/101", headers={"X-User-Id": "999"}).status_code == 401
    )


def test_一覧は管理番号昇順で全件返す(client, users, vehicles) -> None:
    """GET /api/vehicles の total とページング前提の並び順。"""
    response = client.get("/api/vehicles", headers=auth(users["sato"]))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert [v["vehicle_no"] for v in body["items"]] == ["101", "205", "310"]


def test_一覧はステータスで絞り込める(client, db: Session, users, vehicles) -> None:
    """status パラメータでの絞り込み。"""
    make_vehicle(db, "420", status="SOLD")
    client.post(
        "/api/vehicles/101/lock", json={"version": 1}, headers=auth(users["sato"])
    )

    negotiating = client.get(
        "/api/vehicles", params={"status": "NEGOTIATING"}, headers=auth(users["sato"])
    ).json()
    in_stock = client.get(
        "/api/vehicles", params={"status": "IN_STOCK"}, headers=auth(users["sato"])
    ).json()
    sold = client.get(
        "/api/vehicles", params={"status": "SOLD"}, headers=auth(users["sato"])
    ).json()

    assert [v["vehicle_no"] for v in negotiating["items"]] == ["101"]
    assert [v["vehicle_no"] for v in in_stock["items"]] == ["205", "310"]
    assert [v["vehicle_no"] for v in sold["items"]] == ["420"]


def test_一覧はキーワードで部分一致検索できる(client, users, vehicles) -> None:
    """q は管理番号・メーカー・車種に対する部分一致。"""
    by_maker = client.get(
        "/api/vehicles", params={"q": "日産"}, headers=auth(users["sato"])
    ).json()
    by_model = client.get(
        "/api/vehicles", params={"q": "N-BOX"}, headers=auth(users["sato"])
    ).json()
    by_no = client.get(
        "/api/vehicles", params={"q": "10"}, headers=auth(users["sato"])
    ).json()

    assert [v["vehicle_no"] for v in by_maker["items"]] == ["205"]
    assert [v["vehicle_no"] for v in by_model["items"]] == ["310"]
    # 管理番号も部分一致なので「10」は 101 と 310 の両方に当たる
    assert [v["vehicle_no"] for v in by_no["items"]] == ["101", "310"]


def test_一覧はページングできる(client, users, vehicles) -> None:
    """total はページング前の件数、items は該当ページのみ。"""
    page2 = client.get(
        "/api/vehicles",
        params={"page": 2, "page_size": 2},
        headers=auth(users["sato"]),
    ).json()

    assert page2["total"] == 3
    assert [v["vehicle_no"] for v in page2["items"]] == ["310"]
