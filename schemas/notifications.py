from pydantic import BaseModel, Field


class RetryNotification(BaseModel):
    confirm_possible_duplicate: bool = False


class ProcessNotifications(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
