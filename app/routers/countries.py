import logging
from typing import List

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.supabase import supabase

logger = logging.getLogger(__name__)
router = APIRouter()


class Country(BaseModel):
    code: str
    max_members: int


@router.get("/countries", response_model=List[Country])
def list_countries():
    """Return the canonical country list from the DB (country_quotas).
    FE must use this as the single source of truth for allowed registration countries."""
    result = supabase.table("country_quotas").select("country_code, max_members").order("country_code").execute()
    return [Country(code=row["country_code"], max_members=row["max_members"]) for row in (result.data or [])]
