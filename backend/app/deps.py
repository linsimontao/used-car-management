"""FastAPI の依存関係：担当者の解決とロール検証（SPEC §3）。

MVP の認証は「X-User-Id ヘッダーを信じる」だけの簡易モデルであり、
セキュリティ対策ではない（SPEC §3、§12.2）。
"""

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ForbiddenError, NoIdentityError
from app.models import User, UserRole

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> User:
    """X-User-Id ヘッダーから現在の担当者を解決する。

    ヘッダーが無い・数値でない・該当ユーザーが存在しない、のいずれでも
    401 NO_IDENTITY を返す。退職者（active=0）も同様に拒否する。
    """
    if x_user_id is None:
        raise NoIdentityError()
    try:
        user_id = int(x_user_id)
    except ValueError:
        raise NoIdentityError() from None

    user = db.get(User, user_id)
    if user is None or not user.active:
        raise NoIdentityError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    """admin ロールを要求する。不足時は 403 FORBIDDEN。"""
    if user.role != UserRole.ADMIN:
        raise ForbiddenError()
    return user


AdminUser = Annotated[User, Depends(require_admin)]
