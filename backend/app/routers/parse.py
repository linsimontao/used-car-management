"""意図解析 API（SPEC §8.2）。副作用は一切発生しない。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import CurrentUser
from app.llm import IntentParser, get_parser
from app.schemas import ParseParams, ParseRequest, ParseResponse

router = APIRouter(prefix="/api", tags=["parse"])

# パーサーは依存性注入で差し替える（テストは MockParser。SPEC §7.8）
ParserDep = Annotated[IntentParser, Depends(get_parser)]


@router.post("/parse", response_model=ParseResponse)
def parse_text(body: ParseRequest, user: CurrentUser, parser: ParserDep) -> ParseResponse:
    """発話テキストを単一意図に解析する。DB は参照しない（SPEC §7.5）。

    LLM の出力した vehicle_no には normalize_vehicle_no() を必ず適用する
    （build_parse_result() 内で実施。SPEC §7.5）。
    番号が存在するかどうかは判定しない —— 存在確認は後続の
    GET /api/vehicles/{no} が 404 を返すことで表現される。
    """
    result = parser.parse(body.text)
    return ParseResponse(
        intent=result.intent,
        params=ParseParams(vehicle_no=result.vehicle_no, note=result.note),
        confidence=result.confidence,
        missing=result.missing,
        # raw_text は LLM の出力ではなくバックエンドが埋め戻す（SPEC §7.3）
        raw_text=body.text,
    )
