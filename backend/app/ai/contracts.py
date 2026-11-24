from typing import Literal
from pydantic import BaseModel, Field, ConfigDict

Task = Literal['expense_summary', 'policy_guidance']

class AIRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    task: Task
    query: str = Field(default='', max_length=2000)

class Context(BaseModel):
    role: str
    department: str
    expense_count: int
    total_amount: float
    exception_count: int
    policies: list[dict] = Field(default_factory=list)

class AIResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    answer: str = Field(max_length=10000)
    provider: Literal['mock', 'baseline', 'rag']
    sources: list[str] = Field(default_factory=list, max_length=30)

class ReportFilters(BaseModel):
    scope: Literal['visible', 'personal'] = 'visible'
    period_start: str | None = None
    period_end: str | None = None
    department: str | None = None
    category: str | None = None

class ExpenseReport(BaseModel):
    role: str
    provider: str = 'deterministic'
    filters: ReportFilters
    metrics: dict
    categories: list[dict]
    departments: list[dict]
    statuses: list[dict]
    exceptions: list[dict]
    insights: list[dict]
    sources: list[str] = Field(default_factory=lambda: ['TripLedger expense records', 'TripLedger policy evaluations'])
