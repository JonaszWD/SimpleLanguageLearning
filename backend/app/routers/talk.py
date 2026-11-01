"""Talking unit API: is it available, and a signed URL to start a conversation."""

from fastapi import APIRouter, HTTPException

from .. import talk

router = APIRouter(tags=["talk"])


@router.get("/status")
def status() -> dict:
    return {"available": talk.available(), "scenarios": talk.SCENARIOS}


@router.post("/session")
def session() -> dict:
    if not talk.available():
        raise HTTPException(503, "Set ELEVENLABS_API_KEY on the server")
    try:
        return talk.start_session()
    except RuntimeError as e:
        raise HTTPException(502, str(e))
