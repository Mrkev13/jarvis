"""Finance import REST (MRK-62). Inherits app auth and the Finance module gate (`/finance` prefix).

The statement is the raw request body (no multipart, no filename), streamed with a hard cap into a temporary file
outside MEDIA_DIR. Responses and errors carry counts, row numbers and allowlisted codes only – never row values.
"""
from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

import database
from modules.finance.importing import core, storage
from modules.finance.importing.rows import ImportFailure

STATEMENT_MEDIA_TYPES = frozenset({"text/csv", "text/plain", "application/csv", "application/vnd.ms-excel",
                                   "application/octet-stream"})

router = APIRouter(prefix="/finance/imports", tags=["finance"])


def _run(fn):
    db = database.SessionLocal()
    try:
        return fn(db)
    except ImportFailure as failure:
        db.rollback()
        raise HTTPException(status_code=failure.status, detail={"category": failure.code}) from None
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail={"category": "import_operation_failed"}) from None
    finally:
        db.close()


@router.get("")
def imports_list():
    return _run(core.list_imports)


@router.post("/preview")
async def imports_preview(request: Request, account_id: int = Query(ge=1)):
    """Nahrání výpisu + dry run. Nic se nezapíše do transakcí; vrací preview_token pro commit (platí 30 min)."""
    media_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if media_type not in STATEMENT_MEDIA_TYPES:
        raise HTTPException(status_code=415, detail={"category": "unsupported_media_type"})
    limit = storage.max_upload_bytes()
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail={"category": "file_too_large"})
    upload = storage.new_upload_path()
    try:
        size = 0
        with open(upload, "wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail={"category": "file_too_large"})
                fh.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail={"category": "file_empty"})
        return await run_in_threadpool(_run, lambda db: core.preview_import(db, account_id=account_id, upload=upload))
    finally:
        storage.discard(upload)  # po úspěchu už je přesunutý pod id importu; jinak ho tady smažeme


@router.post("/{token}/commit")
def imports_commit(token: str, skip_invalid: bool = False):
    return _run(lambda db: core.commit_import(db, token, skip_invalid=skip_invalid))


@router.post("/{token}/cancel")
def imports_cancel(token: str):
    return _run(lambda db: core.cancel_import(db, token))
