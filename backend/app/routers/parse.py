"""意図解析 API（SPEC §8.2）。副作用は一切発生しない。"""

from fastapi import APIRouter

from app.deps import CurrentUser
from app.schemas import ParseRequest, ParseResponse

router = APIRouter(prefix="/api", tags=["parse"])


@router.post("/parse", response_model=ParseResponse)
def parse_text(body: ParseRequest, user: CurrentUser) -> ParseResponse:
    """発話テキストを単一意図に解析する。DB は参照しない（SPEC §7.5）。

    LLM の出力した vehicle_no には normalize_vehicle_no() を必ず適用する。
    """
    raise NotImplementedError("骨組みのみ。実装は次段階")
