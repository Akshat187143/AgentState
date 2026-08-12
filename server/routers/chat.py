import logging
import secrets

from fastapi import APIRouter, HTTPException

from server.schemas import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    # Reuse the caller's conversation as the LangGraph thread, or mint a new one.
    conversation_id = request.conversation_id or (secrets.randbelow(2**52) + 1)

    try:
        from server.agent import run_turn

        reply = run_turn(str(conversation_id), request.message)
    except Exception:
        logger.exception("Analytics agent failed for conversation %s", conversation_id)
        raise HTTPException(status_code=503, detail="Analytics agent unavailable.")

    return ChatResponse(conversation_id=conversation_id, reply=reply)
