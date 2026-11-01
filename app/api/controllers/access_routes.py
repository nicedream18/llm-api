"""Administrator-only access grant management."""

from fastapi import APIRouter

from app.container import get_container
from app.types.access import AccessGrantInput

router = APIRouter(prefix="/api/v1/access", tags=["Access"])


@router.get("/grants")
def list_grants():
    return {
        "code": "0000",
        "info": "成功",
        "data": get_container().access_service.repo.list_grants(),
    }


@router.post("/grants", status_code=201)
def create_grant(dto: AccessGrantInput):
    row = get_container().access_service.repo.create(dto.model_dump())
    return {"code": "0000", "info": "成功", "data": row}


@router.delete("/grants/{grant_id}")
def delete_grant(grant_id: str):
    get_container().access_service.repo.delete(grant_id)
    return {"code": "0000", "info": "成功", "data": None}
