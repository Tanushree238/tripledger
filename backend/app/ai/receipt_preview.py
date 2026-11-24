from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class ReceiptFields(BaseModel):
    merchant: str | None = Field(default=None, min_length=1, max_length=255)
    amount: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    expense_date: date | None = None
    category: Literal['Meals', 'Ground transport', 'Hotel', 'Fuel', 'Rail travel', 'Airfare', 'Office supplies', 'Other'] | None = None


class ReceiptPreview(BaseModel):
    provider: Literal['mock', 'local', 'azure'] = 'mock'
    fields: ReceiptFields | None = None
    warning: str | None = None
    no_document_match: bool = Field(default=False, exclude=True)


def fixture_preview(content: bytes) -> ReceiptPreview:
    return ReceiptPreview(fields=FIXTURES.get(sha256(content).digest()))


_assets = Path(__file__).resolve().parents[1] / 'demo_receipts'
FIXTURES = {
    sha256((_assets / 'lemon-tree-demo.pdf').read_bytes()).digest(): ReceiptFields(
        merchant='Lemon Tree', amount=12600, expense_date=date(2026, 11, 16), category='Hotel',
    ),
    sha256((_assets / 'social-demo.png').read_bytes()).digest(): ReceiptFields(
        merchant='Social', amount=4200, expense_date=date(2026, 11, 15), category='Meals',
    ),
}
