"""業務例外と HTTP エラーコードの対応（SPEC §8.6）。

2xx 以外のレスポンスは全て以下の構造に統一する。
    { "code": "...", "message": "<そのまま画面に表示できる日本語>", "detail": {...} }
"""

from typing import Any


class AppError(Exception):
    """業務例外の基底クラス。ハンドラがそのまま JSON へ変換する。"""

    status_code: int = 500
    code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_payload(self) -> dict[str, Any]:
        """エラーレスポンスの JSON 表現を返す。"""
        return {"code": self.code, "message": self.message, "detail": self.detail}


class InvalidVehicleNoError(AppError):
    """管理番号の形式が不正（3〜4桁の数字でない）。"""

    status_code = 400
    code = "INVALID_VEHICLE_NO"

    def __init__(self, message: str = "管理番号は3〜4桁の数字で指定してください", **kw: Any) -> None:
        super().__init__(message, **kw)


class NoIdentityError(AppError):
    """X-User-Id が無いか不正。"""

    status_code = 401
    code = "NO_IDENTITY"

    def __init__(
        self, message: str = "担当者が選択されていません。再度ログインしてください", **kw: Any
    ) -> None:
        super().__init__(message, **kw)


class NotLockOwnerError(AppError):
    """ロック所有者以外による解除・売却。"""

    status_code = 403
    code = "NOT_LOCK_OWNER"


class ForbiddenError(AppError):
    """ロール権限が不足（admin 以外による unsold 等）。"""

    status_code = 403
    code = "FORBIDDEN"

    def __init__(self, message: str = "この操作には管理者権限が必要です", **kw: Any) -> None:
        super().__init__(message, **kw)


class VehicleNotFoundError(AppError):
    """管理番号が存在しない。"""

    status_code = 404
    code = "VEHICLE_NOT_FOUND"


class VehicleLockedError(AppError):
    """他の担当者がロック済み。"""

    status_code = 409
    code = "VEHICLE_LOCKED"


class VersionConflictError(AppError):
    """楽観ロックのバージョン不一致。"""

    status_code = 409
    code = "VERSION_CONFLICT"

    def __init__(
        self, message: str = "車両情報が更新されました。もう一度お試しください", **kw: Any
    ) -> None:
        super().__init__(message, **kw)


class InvalidTransitionError(AppError):
    """現在のステータスでは許可されない遷移。"""

    status_code = 409
    code = "INVALID_TRANSITION"


class ForceRequiredError(AppError):
    """管理者が他人のロックを解除するには明示的な force=true が必要。"""

    status_code = 409
    code = "FORCE_REQUIRED"


class LLMUnavailableError(AppError):
    """Gemini の呼び出しに失敗。"""

    status_code = 502
    code = "LLM_UNAVAILABLE"

    def __init__(
        self,
        message: str = "音声解析サービスに接続できません。しばらくしてお試しください",
        **kw: Any,
    ) -> None:
        super().__init__(message, **kw)
