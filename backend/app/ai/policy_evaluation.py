from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class PolicyAmount(BaseModel):
    model_config = ConfigDict(extra='forbid')
    value: Decimal = Field(gt=0, max_digits=11, decimal_places=2)
    currency: str = Field(pattern=r'^[A-Z]{3}$')


class TravelDates(BaseModel):
    model_config = ConfigDict(extra='forbid')
    start_date: date | None = None
    end_date: date | None = None

    @field_validator('end_date')
    @classmethod
    def check_date_order(cls, end_date: date | None, info: ValidationInfo) -> date | None:
        start_date = info.data.get('start_date')
        if start_date is not None and end_date is not None and end_date <= start_date:
            raise ValueError('Check-out must be after check-in.')
        return end_date


class HotelInputs(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expense_category: Literal['hotel_accommodation'] = 'hotel_accommodation'
    travel_destination: str | None = Field(default=None, min_length=1, max_length=100)
    travel_dates: TravelDates | None = None
    expense_amount: PolicyAmount | None = None


class PolicyEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: UUID | None = None
    user_query: str = Field(max_length=2000)
    structured_inputs: HotelInputs = Field(default_factory=HotelInputs)


class PolicyDecision(BaseModel):
    request_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    decision_category: Literal['WITHIN_LIMIT', 'SOFT_FLAG', 'NEEDS_INFORMATION', 'HUMAN_REVIEW']
    applicable_policy_references: list[str] = Field(default_factory=list)
    allowed_expense_amount: PolicyAmount | None = None
    violation_category: str | None = None
    violation_explanation: str
    recommended_action: str
    required_approval_level: Literal['NONE', 'LINE_MANAGER', 'HUMAN_COMPLIANCE_REVIEW']
    missing_required_fields: list[str] = Field(default_factory=list)
    requires_human_approval: bool = False
    advisory_notice: str = 'Demo assessment using a sample policy. Submit expenses through the existing workflow.'


def evaluate_demo(request: PolicyEvaluationRequest) -> PolicyDecision:
    session_id = request.session_id or uuid4()
    inputs = request.structured_inputs
    dates = inputs.travel_dates
    missing = [
        field for field, value in (
            ('travel_destination', (inputs.travel_destination or '').strip()),
            ('travel_dates.start_date', dates.start_date if dates else None),
            ('travel_dates.end_date', dates.end_date if dates else None),
            ('expense_amount', inputs.expense_amount),
        ) if not value
    ]
    if missing:
        return PolicyDecision(
            session_id=session_id, decision_category='NEEDS_INFORMATION',
            violation_explanation='The demo needs a destination, stay dates and claimed amount.',
            recommended_action='Complete the missing fields and recheck the same request.',
            required_approval_level='NONE', missing_required_fields=missing,
        )

    nights = (dates.end_date - dates.start_date).days
    amount = inputs.expense_amount
    allowed = Decimal(8000) * nights
    supported_stay = (inputs.travel_destination.strip().casefold() in ('bengaluru', 'bangalore')
                      and 0 < nights <= 365 and amount.currency == 'INR')
    if supported_stay and amount.value <= allowed:
        return PolicyDecision(
            session_id=session_id, decision_category='WITHIN_LIMIT',
            applicable_policy_references=['POL-TRV-03#2.1'],
            allowed_expense_amount=PolicyAmount(value=allowed, currency='INR'),
            violation_explanation=f'The claim of INR {amount.value:,.2f} is within the sample hotel cap.',
            recommended_action='Submit the expense through the usual approval workflow.',
            required_approval_level='NONE',
        )
    if supported_stay and allowed < amount.value <= allowed * Decimal('1.20'):
        return PolicyDecision(
            session_id=session_id, decision_category='SOFT_FLAG',
            applicable_policy_references=['POL-TRV-03#2.1', 'POL-EXC-01#1.2'],
            allowed_expense_amount=PolicyAmount(value=allowed, currency='INR'),
            violation_category='HOTEL_CAP_EXCEEDED_WITHIN_EXCEPTION_BAND',
            violation_explanation=f'The claim exceeds the sample hotel cap by INR {amount.value - allowed:,.2f}.',
            recommended_action='Include a written justification and send the expense for manager review.',
            required_approval_level='LINE_MANAGER', requires_human_approval=True,
        )
    return PolicyDecision(
        session_id=session_id, decision_category='HUMAN_REVIEW',
        violation_explanation='The supplied details fall outside the supported demo policy case.',
        recommended_action='Ask an authorized policy reviewer to check the expense.',
        required_approval_level='HUMAN_COMPLIANCE_REVIEW', requires_human_approval=True,
    )
