from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel


class Material(BaseModel):
    part_id: str
    name: str
    quantity: float
    unit_price: float
    total_price: float


class ComplianceFlag(BaseModel):
    type: Literal["certification", "scope", "hours", "duplicate", "cost_limit", "safety"]
    severity: Literal["info", "warning", "critical"]
    description: str
    action_required: Optional[str] = None


class InvoiceItem(BaseModel):
    customer_id: str
    contract_id: str
    site_id: str
    worker_id: str
    date: str
    service_category: str
    work_type: Literal["scheduled_maintenance", "repair", "emergency_repair"]
    description: str
    hours_worked: float
    rate_type: Literal["normal", "evening", "emergency", "scheduled"]
    hourly_rate: float
    labor_cost: float
    materials: list[Material]
    materials_cost: float
    material_markup_percentage: float
    travel_cost: float
    total_cost: float
    requires_approval: bool
    approval_reason: Optional[str] = None
    certification_verified: Optional[bool] = None
    validation_notes: list[str]


class WorkLog(BaseModel):
    customer_id: str
    contract_id: str
    site_id: str
    worker_id: str
    date: str
    service_category: str
    work_type: Literal["scheduled_maintenance", "repair", "emergency_repair"]
    description: str
    hours_worked: float
    materials: list[Material]
    status: Literal["complete", "prevented", "pending_approval", "pending_review"]
    billable: bool
    billability_reasoning: str
    compliance_flags: list[ComplianceFlag]
    invoice_item: Optional[InvoiceItem] = None


class ChatMessage(BaseModel):
    role: Literal["worker", "agent"]
    content: str


class SessionCreate(BaseModel):
    worker_id: str
    date: str  # YYYY-MM-DD


class MessageRequest(BaseModel):
    session_id: str
    content: str


class MessageResponse(BaseModel):
    session_id: str
    response: str
    work_log: Optional[WorkLog] = None
    finalized: bool = False
