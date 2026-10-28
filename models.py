"""
Pydantic models for AI Workforce API.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from enum import Enum


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class AgentType(str, Enum):
    ORCHESTRATOR = "orchestrator"
    CRM = "crm"
    EMAIL = "email"
    LEAD = "lead"
    ANALYTICS = "analytics"
    FOLLOWUP = "followup"


class BusinessRequest(BaseModel):
    title: str = Field(..., description="Short title of the business request")
    description: str = Field(..., description="Full description of what needs to be done")


class BusinessRequestResponse(BaseModel):
    id: str
    title: str
    description: str
    status: str
    created_at: str
    tasks: List[Dict[str, Any]] = []


class TaskApproval(BaseModel):
    decision: str = Field(..., description="'approve' or 'reject'")
    reason: Optional[str] = None


class ContactCreate(BaseModel):
    name: str
    email: str
    company: Optional[str] = None
    phone: Optional[str] = None


class DealCreate(BaseModel):
    contact_id: str
    title: str
    value: float = 0.0
    stage: str = "prospecting"
    probability: int = 10
    close_date: Optional[str] = None
