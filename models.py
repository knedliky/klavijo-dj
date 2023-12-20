from uuid import UUID

from pydantic import BaseModel, EmailStr


class User(BaseModel):
    id: UUID
    name: str
    email: EmailStr


class Flow(BaseModel):
    id: str
    name: str
    keywords: list[str]
    sample_playlist_url: str
