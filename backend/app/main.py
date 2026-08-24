"""FastAPI アプリのエントリポイント（SPEC §10）。

CORS 設定と、業務例外を SPEC §8.6 のエラー形式へ変換する例外ハンドラを持つ。
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.errors import AppError
from app.routers import parse, users, vehicles

settings = get_settings()

app = FastAPI(
    title="中古車在庫管理システム API",
    description="中古車販売店向け在庫車両管理システムのバックエンド（SPEC v1.1 / MVP）",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """業務例外を SPEC §8.6 の形式で返す。"""
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Pydantic のバリデーションエラーも同一の形式に揃える。"""
    return JSONResponse(
        status_code=400,
        content={
            "code": "INVALID_REQUEST",
            "message": "リクエストの形式が正しくありません",
            "detail": {"errors": exc.errors()},
        },
    )


@app.exception_handler(NotImplementedError)
async def not_implemented_handler(
    request: Request, exc: NotImplementedError
) -> JSONResponse:
    """骨組み段階の未実装エンドポイント。実装完了後はこのハンドラを削除する。"""
    return JSONResponse(
        status_code=501,
        content={
            "code": "NOT_IMPLEMENTED",
            "message": "この機能はまだ実装されていません",
            "detail": {"path": request.url.path},
        },
    )


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """ヘルスチェック。起動確認と疎通確認に使う。"""
    return {"status": "ok"}


app.include_router(users.router)
app.include_router(parse.router)
app.include_router(vehicles.router)
