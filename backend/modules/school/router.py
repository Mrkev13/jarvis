"""Study materials REST (MRK-42). Inherits application auth and the School module gate (`/school` prefix).
No URL or credential is accepted from or returned to clients; errors are allowlisted categories only."""
import tempfile
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import database
from modules.school import reading, service, zip_import
from modules.school.moodle import MoodleSyncError

ZIP_MEDIA_TYPES = frozenset({'application/zip', 'application/x-zip-compressed', 'application/octet-stream'})
SPOOL_MEMORY_BYTES = 32 * 1024 * 1024

router = APIRouter(prefix='/school/materials', tags=['school'])


class CourseMappingRequest(BaseModel):
    subject_id: int | None = None


def _run(fn, *, commit=False):
    db = database.SessionLocal()
    try:
        result = fn(db)
        if commit:
            db.commit()
        return result
    except (service.MaterialError, reading.ReadingError) as error:
        db.rollback()
        raise HTTPException(status_code=error.status, detail={'category': error.category}) from None
    except MoodleSyncError as error:
        db.rollback()
        raise HTTPException(status_code=503, detail={'category': error.category}) from None
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail={'category': 'materials_operation_failed'}) from None
    finally:
        db.close()


@router.get('')
def materials_list(subject_id: int | None = Query(default=None, ge=1), course_id: int | None = Query(default=None, ge=1),
                   type: Literal['pdf', 'pptx', 'docx', 'txt', 'other'] | None = None,
                   state: Literal['active', 'missing', 'all'] = 'active'):
    return _run(lambda db: service.list_materials(db, subject_id=subject_id, course_id=course_id,
                                                  material_type=type, state=state))


@router.post('/sync')
def materials_sync():
    """Commits per course inside the service; a failed course is rolled back on its own."""
    return _run(service.sync_materials)


@router.post('/import-zip')
async def materials_import_zip(request: Request):
    """MRK-56: one official Moodle course ZIP („Stáhnout obsah kurzu") as the raw request body. Streamed with a hard
    size cap into a spooled temp file (deleted afterwards), then the shared import core; never extracted to disk."""
    media_type = (request.headers.get('content-type') or '').split(';', 1)[0].strip().lower()
    if media_type not in ZIP_MEDIA_TYPES:
        raise HTTPException(status_code=415, detail={'category': 'unsupported_media_type'})
    limit = zip_import.max_archive_bytes()
    declared = request.headers.get('content-length', '')
    if declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail={'category': 'archive_too_large'})
    with tempfile.SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES) as spool:
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise HTTPException(status_code=413, detail={'category': 'archive_too_large'})
            spool.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail={'category': 'archive_invalid'})
        spool.seek(0)
        return await run_in_threadpool(_run, lambda db: zip_import.import_course_export(db, spool))


@router.put('/courses/{course_id}')
def materials_course_mapping(course_id: int, request: CourseMappingRequest):
    return _run(lambda db: service.set_course_subject(db, course_id, request.subject_id), commit=True)


@router.get('/{material_id}')
def materials_detail(material_id: int):
    return _run(lambda db: service.get_material(db, material_id))


@router.get('/{material_id}/content')
def materials_content(material_id: int, q: str | None = Query(default=None, max_length=reading.MAX_QUERY_CHARS),
                      max_chunks: int = Query(default=reading.DEFAULT_CHUNKS, ge=1, le=reading.MAX_CHUNKS),
                      max_chars: int = Query(default=reading.DEFAULT_CHARS, ge=200, le=reading.MAX_CHARS)):
    """MRK-44: bounded text of one material (beginning + outline, or the chunks best matching `q`)."""
    return _run(lambda db: reading.read_material(db, material_id, query=q, max_chunks=max_chunks, max_chars=max_chars))


@router.get('/{material_id}/file')
def materials_file(material_id: int):
    path, media_type, name = _run(lambda db: service.material_file(db, material_id))
    return FileResponse(path, media_type=media_type, filename=name, content_disposition_type='attachment',
                        headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-store'})
