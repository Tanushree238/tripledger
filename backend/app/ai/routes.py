import logging, os, time, uuid
from typing import Literal
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from ..database import get_db
from ..receipts import read_receipt
from .contracts import AIRequest, AIResponse, ExpenseReport, ReportFilters
from .actions import build_context, build_expense_report
from .providers import get_provider
from .receipt_preview import ReceiptPreview, fixture_preview

logger = logging.getLogger(__name__)
def make_router(current_user):
    router = APIRouter(prefix='/ai', tags=['AI'])
    @router.get('/health')
    def health(user=Depends(current_user)):
        enabled = os.getenv('AI_ENABLED', 'true').lower() == 'true'
        try: get_provider(); configured = True
        except ValueError: configured = False
        return {'enabled': enabled, 'configured': configured, 'mode': os.getenv('AI_MODE','mock'), 'tasks': ['expense_summary','policy_guidance']}
    @router.get('/policy-summary')
    def policy_summary(db=Depends(get_db), user=Depends(current_user)):
        return build_context(db, user).policies

    @router.get('/expense-report', response_model=ExpenseReport)
    def expense_report(db=Depends(get_db), user=Depends(current_user),
                       period_start: str | None = None, period_end: str | None = None,
                       department: str | None = None, category: str | None = None,
                       scope: Literal['visible', 'personal'] = 'visible'):
        # Report is deterministic and available independently of the LLM provider.
        from datetime import date
        for value in (period_start, period_end):
            if value:
                try: date.fromisoformat(value)
                except ValueError: raise HTTPException(422, 'Dates must use YYYY-MM-DD')
        if period_start and period_end and period_start > period_end:
            raise HTTPException(422, 'Start date must not exceed end date')
        try:
            return build_expense_report(db, user, ReportFilters(period_start=period_start,
                period_end=period_end, department=department, category=category, scope=scope))
        except PermissionError:
            raise HTTPException(403, 'Action not permitted')

    @router.post('/receipt-preview', response_model=ReceiptPreview)
    async def receipt_preview(file: UploadFile = File(...), user=Depends(current_user)):
        if os.getenv('AI_ENABLED', 'true').lower() != 'true' or os.getenv('AI_MODE', 'mock') != 'mock':
            raise HTTPException(503, 'Demo receipt preview is unavailable. Enter expense details manually.')
        content, _ = await read_receipt(file)
        return fixture_preview(content)

    @router.post('/execute', response_model=AIResponse)
    async def execute(request: AIRequest, db=Depends(get_db), user=Depends(current_user)):
        if os.getenv('AI_ENABLED','true').lower() != 'true': raise HTTPException(503,'AI is disabled; use the regular TripLedger workflows.')
        trace = uuid.uuid4().hex
        start = time.monotonic()
        try: context = build_context(db, user)
        except PermissionError: raise HTTPException(403,'Action not permitted')
        try:
            result = await get_provider().execute(request, context)
        except Exception as exc:
            logger.warning('AI failure trace=%s task=%s type=%s', trace, request.task, type(exc).__name__)
            raise HTTPException(503,'AI unavailable; regular TripLedger workflows remain available.') from None
        logger.info('AI trace=%s task=%s provider=%s elapsed_ms=%d', trace, request.task, result.provider, (time.monotonic()-start)*1000)
        return result
    return router
