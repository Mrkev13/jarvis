"""Public operational health, with no business data or authentication requirement."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

import health_service

router = APIRouter()


@router.get('/health')
def health():
    result = health_service.runtime_health()
    return JSONResponse(result, status_code=503 if result['status'] == 'unhealthy' else 200,
                        headers={'Cache-Control': 'no-store'})
