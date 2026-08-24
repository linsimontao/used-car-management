"""pytest 共通フィクスチャ。

全てのテストは MockParser を使用し、ネットワーク接続を行わない（SPEC §7.8）。

DB は tmp_path 配下の一時ファイルを使う。`:memory:` は使えない——
同時実行テストが複数スレッド・複数接続から同じ DB を叩くため。
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.clock import now_iso, plus_minutes_iso
from app.db import create_sqlite_engine, get_db
from app.llm import get_parser
from app.llm.mock import MockParser
from app.main import app
from app.models import Base, User, Vehicle, VehicleEvent


@pytest.fixture
def engine(tmp_path) -> Iterator[Engine]:
    """一時ファイル DB のエンジン。本番と同じ PRAGMA が適用される。"""
    eng = create_sqlite_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker:
    """アプリ本体と同じ設定のセッションファクトリ。"""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db(session_factory: sessionmaker) -> Iterator[Session]:
    """テストが DB を直接検証するためのセッション。"""
    with session_factory() as session:
        yield session


@pytest.fixture
def client(session_factory: sessionmaker) -> Iterator[TestClient]:
    """TestClient。get_db を一時 DB のセッションに差し替える。"""

    def override_get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    # GEMINI_API_KEY が設定されていても実通信させない（SPEC §7.8）
    app.dependency_overrides[get_parser] = lambda: MockParser()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def parser() -> MockParser:
    """パーサーを直接検証するためのフィクスチャ。"""
    return MockParser()


@pytest.fixture
def users(db: Session) -> dict[str, User]:
    """担当者3名（SPEC §11.1）。管理者は田中 隆のみ。"""
    created = {
        "sato": User(name="佐藤 健", role="staff", active=True, created_at=now_iso()),
        "suzuki": User(name="鈴木 美咲", role="staff", active=True, created_at=now_iso()),
        "tanaka": User(name="田中 隆", role="admin", active=True, created_at=now_iso()),
    }
    db.add_all(created.values())
    db.commit()
    return created


@pytest.fixture
def vehicle(db: Session) -> Vehicle:
    """在庫状態の車両 1 台（101番）。"""
    return make_vehicle(db, "101")


@pytest.fixture
def vehicles(db: Session, vehicle: Vehicle) -> list[Vehicle]:
    """一覧テスト用の複数台。101番に加えて 205番・310番。"""
    return [
        vehicle,
        make_vehicle(db, "205", maker="日産", model="ノート e-POWER X"),
        make_vehicle(db, "310", maker="ホンダ", model="N-BOX カスタム G・Lターボ"),
    ]


def make_vehicle(
    db: Session,
    vehicle_no: str,
    maker: str = "トヨタ",
    model: str = "プリウス S ツーリングセレクション",
    status: str = "IN_STOCK",
) -> Vehicle:
    """テスト用の車両を 1 台作って commit する。"""
    now = now_iso()
    created = Vehicle(
        vehicle_no=vehicle_no,
        maker=maker,
        model=model,
        model_year=2019,
        mileage_km=62000,
        color="パールホワイト",
        displacement="1.8L",
        price_yen=1780000,
        shaken_expires_on="2027-03-31",
        repair_history=False,
        location="A区画 3番",
        remark="禁煙車・ワンオーナー・記録簿あり",
        status=status,
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(created)
    db.commit()
    return created


def auth(user: User) -> dict[str, str]:
    """X-User-Id ヘッダー（SPEC §3）。"""
    return {"X-User-Id": str(user.id)}


@pytest.fixture
def reload_vehicle(db: Session):
    """API 呼び出し後の DB の実際の状態を読み直すヘルパー。

    セッションは読み取りスナップショットを保持するため、rollback で破棄してから読む。
    """

    def _reload(vehicle_no: str) -> Vehicle:
        db.rollback()
        db.expire_all()
        return db.query(Vehicle).filter(Vehicle.vehicle_no == vehicle_no).one()

    return _reload


@pytest.fixture
def events_of(db: Session):
    """車両のイベントを時系列で取得するヘルパー。"""

    def _events(vehicle_no: str) -> list[VehicleEvent]:
        db.rollback()
        db.expire_all()
        vehicle = db.query(Vehicle).filter(Vehicle.vehicle_no == vehicle_no).one()
        return (
            db.query(VehicleEvent)
            .filter(VehicleEvent.vehicle_id == vehicle.id)
            .order_by(VehicleEvent.id)
            .all()
        )

    return _events


def make_expired_lock(db: Session, vehicle: Vehicle, owner: User) -> None:
    """期限切れのロックを DB へ直接書き込む（遅延期限切れテスト用）。"""
    vehicle.status = "NEGOTIATING"
    vehicle.locked_by = owner.id
    vehicle.locked_at = plus_minutes_iso(-180)
    vehicle.lock_expires_at = plus_minutes_iso(-60)
    vehicle.lock_note = "田中様と商談中"
    vehicle.version += 1
    db.commit()
