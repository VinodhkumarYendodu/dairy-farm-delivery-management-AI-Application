from pydantic import BaseModel, Field, field_validator
from typing import Literal
from schemas.subscriptions import CustomerScheduleDraft


class DocumentQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=2000)

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question cannot be blank")
        return value


class CustomerIssueDraft(BaseModel):
    category: Literal["DELIVERY", "PRODUCT", "PAYMENT", "ACCOUNT", "OTHER"] | None = None
    description: str | None = Field(default=None, max_length=2000)


class CustomerAssistantQuestion(BaseModel):
    message: str = Field(min_length=1, max_length=1500)
    schedule_draft: CustomerScheduleDraft | None = None
    issue_draft: CustomerIssueDraft | None = None

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message cannot be blank")
        return value


class CustomerIssueCreate(BaseModel):
    category: Literal["DELIVERY", "PRODUCT", "PAYMENT", "ACCOUNT", "OTHER"]
    description: str = Field(min_length=8, max_length=2000)

    @field_validator("description")
    @classmethod
    def description_not_blank(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 8:
            raise ValueError("Please describe the issue in at least 8 characters")
        return value


class CustomerIssueStatusUpdate(BaseModel):
    status: Literal["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"]
    comment: str = Field(min_length=3, max_length=1000)

    @field_validator("comment")
    @classmethod
    def comment_not_blank(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Add a comment with at least 3 characters before updating the status")
        return value
