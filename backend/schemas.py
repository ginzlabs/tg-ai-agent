from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field

class TranscriptionRequest(BaseModel):
    audio_url: str
    language: Optional[str] = "en"
    task_id: Optional[str] = None

class STTRequest(BaseModel):
    audio_url: str = Field(..., alias="audio_input")
    chat_id: int
    db_thread_id: str
    message_id: int
    temp_msg_id: Optional[int] = None
    speaker_labels: Optional[bool] = False
    model: Optional[str] = "nano"
    language_detection: Optional[bool] = True
    language_code: Optional[str] = None
    
    class Config:
        populate_by_name = True

class ReportRequest(BaseModel):
    report_type: str
    parameters: Dict[Any, Any]
    task_id: Optional[str] = None

class TaskResponse(BaseModel):
    task_id: str
    status: str
    task_type: Optional[str] = None
    result: Optional[Dict[Any, Any]] = None
    error: Optional[str] = None
    queue_position: Optional[int] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class SummaryOutput(BaseModel):
    """Expected output format for the summary."""
    summary: str = Field(description="The summarized text")
    key_points: List[str] = Field(description="Key points extracted from the text")
    sentiment: str = Field(description="Overall sentiment of the text (positive, negative, neutral)")

class MarketReportRequest(BaseModel):
    """Request for generating market report and sending it to a user."""
    chat_id: str = Field(..., description="The ID of the chat to send the report to")
    message_id: Optional[int] = Field(None, description="The ID of the message to update, if applicable")
    temp_msg_id: Optional[str] = Field(None, description="Temporary message ID for status updates")