"""データベース接続管理（SPEC §6.3）。

SQLite に対する必須要件をここに集約する。
  - `PRAGMA journal_mode=WAL`（WAL モードは必須）
  - `PRAGMA foreign_keys=ON`
  - `PRAGMA busy_timeout=3000`（瞬間的な書き込み競合で即座に失敗させない）
  - 書き込みトランザクションは必ず `BEGIN IMMEDIATE` で開始する
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()

# SQLite ファイルの置き場所を確実に用意しておく
settings.db_file.parent.mkdir(parents=True, exist_ok=True)


def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """接続確立時に SPEC §6.3 の PRAGMA を適用する。"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=3000")
    cursor.close()


def create_sqlite_engine(url: str) -> Engine:
    """PRAGMA 設定込みの SQLite エンジンを生成する。

    テスト用の一時 DB も本番と同じ WAL / foreign_keys / busy_timeout で動かす必要があるため、
    エンジン生成はこのファクトリに一本化する。
    """
    new_engine = create_engine(
        url,
        # FastAPI の依存関係はリクエストごとに別スレッドで動くため接続の共有を許可する
        connect_args={"check_same_thread": False},
        future=True,
    )
    event.listen(new_engine, "connect", _set_sqlite_pragma)
    return new_engine


engine = create_sqlite_engine(settings.database_url)


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI の依存関係。リクエスト単位のセッションを供給する。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def immediate_transaction(db: Session) -> Iterator[Session]:
    """`BEGIN IMMEDIATE` で書き込みトランザクションを開始する（SPEC §6.3）。

    SQLite の遅延ロック昇格に起因するデッドロックを避けるため、
    車両を更新する全ての経路はこのコンテキストマネージャを通すこと。
    """
    # SQLAlchemy が暗黙に開始した DEFERRED トランザクションを一旦破棄してから
    # 明示的に IMMEDIATE で開き直す
    db.rollback()
    db.execute(text("BEGIN IMMEDIATE"))
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
