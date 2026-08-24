"""担当者 API（SPEC §8.1）。"""

from fastapi import APIRouter
from sqlalchemy import select

from app.deps import DbSession
from app.models import User
from app.schemas import UserOut

router = APIRouter(prefix="/api", tags=["users"])


@router.get("/users", response_model=list[UserOut])
def list_users(db: DbSession) -> list[UserOut]:
    """選択可能な担当者一覧（ログイン画面用）。active な担当者のみ返す。

    このエンドポイントのみ X-User-Id ヘッダーを要求しない。
    """
    users = db.scalars(
        select(User).where(User.active.is_(True)).order_by(User.id)
    ).all()
    return [UserOut(id=u.id, name=u.name, role=u.role) for u in users]
