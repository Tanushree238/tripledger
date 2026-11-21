from pydantic import BaseModel
from typing import Optional

class TravelCreate(BaseModel):
    project_code: str
    purpose: str
    origin: str
    destination: str
    depart_date: str
    return_date: str
    flight: str
    hotel: str
    estimated_cost: float

class ExpenseCreate(BaseModel):
    project_code: str
    category: str
    merchant: str
    expense_date: str
    amount: float
    description: str = ""

class ExpenseUpdate(BaseModel):
    project_code: Optional[str] = None
    category: Optional[str] = None
    merchant: Optional[str] = None
    expense_date: Optional[str] = None
    amount: Optional[float] = None
    description: Optional[str] = None

class Decision(BaseModel):
    decision: str
    comment: str = ""

class PolicyUpdate(BaseModel):
    max_travel: float
    max_expense: float
    receipt_threshold: float
    flag_mode: str
    enabled: bool = True
