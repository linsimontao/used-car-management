"""同時実行テスト（SPEC §6.1）。

スレッドプールから N 件の lock を同時発行し、
ちょうど 1 件が 200、N-1 件が 409 であること。
"""

from concurrent.futures import ThreadPoolExecutor

from tests.conftest import auth


def test_同時ロックは1件のみ成功する(client, users, vehicle, reload_vehicle) -> None:
    """同一秒の lock 競合で成功は 1 件だけ。

    全員が同じ version=1 を持って書き込みに来る状況を再現する。
    条件付き UPDATE + version の楽観ロックにより、勝者は必ず 1 人になる。
    """
    actors = [users["sato"], users["suzuki"], users["tanaka"]] * 3

    def attempt(actor):
        return client.post(
            "/api/vehicles/101/lock", json={"version": 1}, headers=auth(actor)
        )

    with ThreadPoolExecutor(max_workers=len(actors)) as pool:
        responses = list(pool.map(attempt, actors))

    statuses = [r.status_code for r in responses]
    assert statuses.count(200) == 1
    assert statuses.count(409) == len(actors) - 1

    # 敗者のエラーは原因が特定できるものであること
    codes = {r.json()["code"] for r in responses if r.status_code == 409}
    assert codes <= {"VEHICLE_LOCKED", "VERSION_CONFLICT"}

    # ロックの所有者は成功した 1 人、version は 1 度だけ進む
    winner = next(r for r in responses if r.status_code == 200).json()
    locked = reload_vehicle("101")
    assert locked.status == "NEGOTIATING"
    assert locked.version == 2
    assert locked.locker.name == winner["lock"]["locked_by"]["name"]
