import json
from collections import defaultdict

from sqlalchemy import or_
from sqlalchemy.orm import contains_eager
from .. import models as m
from .contracts import Context, ExpenseReport, ReportFilters
from ..policy import policy_for, receipt_file, receipt_requests

def build_context(db, user):
    # No model-generated SQL or mutations. Scope is derived from the database identity.
    rows = _visible_expenses(db, user).all()
    selected = policy_for(db, user, '*')
    policies = [selected] if selected else []
    applicable = [dict(name=p.name, max_expense=p.max_expense, receipt_threshold=p.receipt_threshold) for p in policies if p.role in (user.role, '*') and p.department in (user.department, '*') and p.project_code == '*']
    return Context(role=user.role, department=user.department, expense_count=len(rows), total_amount=sum(x.amount for x in rows), exception_count=sum(bool(x.policy_flag) for x in rows), policies=applicable)

def _visible_expenses(db, user):
    q = db.query(m.Expense).join(m.Expense.employee).options(contains_eager(m.Expense.employee))
    if user.role == 'employee':
        q = q.filter(m.Expense.employee_id == user.id)
    elif user.role == 'manager':
        reports = db.query(m.Employee.id).filter(m.Employee.manager_id == user.id)
        q = q.filter(or_(m.Expense.employee_id == user.id, m.Expense.employee_id.in_(reports)))
    elif user.role != 'finance':
        raise PermissionError('Unknown role')
    return q


def build_expense_report(db, user, filters: ReportFilters):
    # Query-level identity scoping. The caller cannot select a different role or employee.
    q = _visible_expenses(db, user)
    if filters.scope == 'personal':
        q = q.filter(m.Expense.employee_id == user.id)
    if filters.period_start:
        q = q.filter(m.Expense.expense_date >= filters.period_start)
    if filters.period_end:
        q = q.filter(m.Expense.expense_date <= filters.period_end)
    if filters.department:
        q = q.filter(m.Employee.department == filters.department)
    if filters.category:
        q = q.filter(m.Expense.category == filters.category)
    rows = q.order_by(m.Expense.expense_date.desc(), m.Expense.id.desc()).all()
    total = round(sum(x.amount for x in rows), 2)
    flagged = [x for x in rows if x.policy_flag]
    categories = defaultdict(lambda: {'amount': 0.0, 'count': 0})
    departments = defaultdict(lambda: {'amount': 0.0, 'count': 0})
    statuses = defaultdict(int)
    for x in rows:
        categories[x.category]['amount'] += x.amount
        categories[x.category]['count'] += 1
        departments[x.employee.department]['amount'] += x.amount
        departments[x.employee.department]['count'] += 1
        statuses[x.status] += 1
    def breakdown(data, key):
        return sorted([{key: name, 'amount': round(v['amount'], 2), 'count': v['count'],
                        'share_pct': round(100*v['amount']/total, 1) if total else 0}
                       for name,v in data.items()], key=lambda r: (-r['amount'], r[key]))
    by_category = breakdown(categories, 'category')
    by_department = breakdown(departments, 'department')
    exceptions = [dict(id=x.id, merchant=x.merchant, employee=x.employee.name,
                       department=x.employee.department, amount=round(x.amount, 2),
                       category=x.category, date=x.expense_date, status=x.status,
                       reason=x.policy_flag, receipt_attached=bool(receipt_file(x))) for x in flagged]
    insights = []
    evaluations = {}
    requested = set()
    if flagged:
        flagged_ids = [row.id for row in flagged]
        for evaluation in db.query(m.PolicyEvaluation).filter(
            m.PolicyEvaluation.expense_id.in_(flagged_ids)
        ).order_by(m.PolicyEvaluation.id.desc()):
            if evaluation.expense_id not in evaluations:
                evaluations[evaluation.expense_id] = json.loads(evaluation.payload)
        requested = {item_id for (item_id,) in receipt_requests(db).filter(
            m.AuditLog.item_id.in_(flagged_ids),
        ).distinct()}
    for row, expense in zip(flagged, exceptions):
        evaluation = evaluations.get(row.id, {})
        policy = evaluation.get('policy') or {}
        missing_receipt = not expense['receipt_attached'] and any(
            reason.strip().startswith('Receipt required above')
            for reason in expense['reason'].split(';')
        )
        own_expense = user.id == row.employee_id
        pending = row.status.startswith('pending')
        receipt_requested = missing_receipt and row.id in requested
        recommendation = 'Open the expense and review the recorded policy checks.'
        if missing_receipt:
            if not own_expense:
                if receipt_requested:
                    recommendation = 'Receipt requested. Awaiting the submitter’s upload.'
                elif pending:
                    recommendation = 'Request the missing receipt from the submitter in the expense details.'
                else:
                    recommendation = 'Review the missing receipt in the closed expense record.'
            elif row.status in ('draft', 'pending_manager', 'pending_finance'):
                recommendation = 'Open the expense to attach the required receipt.'
            else:
                recommendation = 'Review the missing receipt with Finance.'
        insights.append(dict(
            kind='attention', title=f"{expense['merchant']} · {expense['employee']}",
            detail=expense['reason'], recommendation=recommendation,
            amount=expense['amount'], expense_id=expense['id'],
            source=policy.get('name') or 'Recorded expense policy flag',
            receipt_requested=receipt_requested,
            action_label='Review exception' if user.role == 'finance' else 'Open expense',
        ))
    if rows:
        largest = by_category[0]
        if not filters.category:
            insights.append(dict(
                kind='distribution', title=f"{largest['category']} leads spending",
                detail=f"{largest['count']} expenses account for {largest['share_pct']}% of visible spending.",
                recommendation='Review the expenses in this category.',
                amount=largest['amount'], category=largest['category'],
                source='Expense records in this report',
            ))
        if len(by_department) > 1 and not filters.department:
            largest_department = by_department[0]
            insights.append(dict(
                kind='distribution', title=f"{largest_department['department']} leads departmental spending",
                detail=f"{largest_department['count']} expenses account for {largest_department['share_pct']}% of visible spending.",
                amount=largest_department['amount'], department=largest_department['department'],
                source='Expense records in this report',
            ))
        if len({x.expense_date[:7] for x in rows}) < 2:
            insights.append(dict(kind='context', title='Small reporting sample',
                                 detail='This view covers one month of activity. Widen the date range to compare months.'))
    return ExpenseReport(role=user.role, filters=filters,
        metrics=dict(total=total, count=len(rows), average=round(total/len(rows), 2) if rows else 0,
                     exceptions=len(flagged), exception_rate=round(100*len(flagged)/len(rows), 1) if rows else 0,
                     pending=sum(1 for x in rows if x.status.startswith('pending'))),
        categories=by_category, departments=by_department,
        statuses=[dict(status=k, count=v) for k,v in sorted(statuses.items())],
        exceptions=exceptions, insights=insights)
