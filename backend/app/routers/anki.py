from fastapi import APIRouter, File, HTTPException, UploadFile

from ..anki_import import AnkiImportError, parse_apkg

router = APIRouter(tags=["anki"])

MAX_UPLOAD_BYTES = 200 * 1024 * 1024


@router.post("/import")
async def import_apkg(file: UploadFile = File(...)) -> dict:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large.")
    try:
        return parse_apkg(data)
    except AnkiImportError as exc:
        raise HTTPException(422, str(exc)) from exc
