from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel

class UserCreate(BaseModel):
    chat_id: Optional[int] = None
    user_name: Optional[str] = None
    role: Optional[str] = "user"  # e.g., "user", "admin", etc.
    tier: int = 1
    expire_at: Optional[datetime] = None

class UserResponse(BaseModel):
    id: int
    chat_id: Optional[int]
    user_name: Optional[str]
    role: str
    status: str
    tier: int
    created_at: datetime
    joined_at: Optional[datetime]
    banned_at: Optional[datetime]
    messages_count: int
    active: bool
    llm_choice: Optional[str] = None

class SendMessage(BaseModel):
    chat_id: int
    message_id: Optional[int] = None
    temp_msg_id: Optional[int] = None
    message: str
    file_url: Optional[str] = None
    file_type: Optional[Literal["document", "photo", "audio", "video", "voice"]] = None 
    caption: Optional[str] = None
    file_name: Optional[str] = None
    metadata: Optional[dict] = None
