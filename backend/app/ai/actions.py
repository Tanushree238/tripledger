from sqlalchemy import or_
from .. import models as m
from .contracts import Context
from ..policy import policy_for

def build_context(db, user):
    # No model-generated SQL or mutations. Scope is derived from the database identity.
    q = db.query(m.Expense)
    if user.role == 'employee': q = q.filter(m.Expense.employee_id == user.id)
    elif user.role == 'manager':
        reports = db.query(m.Employee.id).filter(m.Employee.manager_id == user.id)
        q = q.filter(or_(m.Expense.employee_id == user.id, m.Expense.employee_id.in_(reports)))
    elif user.role != 'finance': raise PermissionError('Unknown role')
    rows = q.all()
    selected = policy_for(db, user, '*')
    policies = [selected] if selected else []
    applicable = [dict(name=p.name, max_expense=p.max_expense, receipt_threshold=p.receipt_threshold) for p in policies if p.role in (user.role, '*') and p.department in (user.department, '*') and p.project_code == '*']
    return Context(role=user.role, department=user.department, expense_count=len(rows), total_amount=sum(x.amount for x in rows), exception_count=sum(bool(x.policy_flag) for x in rows), policies=applicable)

from collections import defaultdict
from datetime import date
from .contracts import ExpenseReport, ReportFilters


def _visible_expenses(db, user):
    q = db.query(m.Expense).join(m.Employee, m.Employee.id == m.Expense.employee_id)
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
                       reason=x.policy_flag, receipt_attached=bool(x.receipt_path)) for x in flagged]
    insights = []
    if rows:
        largest = by_category[0]
        insights.append(dict(kind='distribution', title='Largest spending category',
                             detail=f"{largest['category']} accounts for {largest['share_pct']}% of visible spending (INR {largest['amount']:,.2f})."))
        if flagged:
            insights.append(dict(kind='attention', title='Policy exceptions need review',
                                 detail=f'{len(flagged)} of {len(rows)} expenses are flagged. Review the individual reasons below.'))
        else:
            insights.append(dict(kind='positive', title='No recorded policy exceptions',
                                 detail='No visible expenses currently have a policy flag.'))
        if len(rows) < 10:
            insights.append(dict(kind='context', title='Small reporting sample',
                                 detail='Fewer than 10 expenses are in this view. Avoid drawing broad spending trends from this sample.'))
    return ExpenseReport(role=user.role, filters=filters,
        metrics=dict(total=total, count=len(rows), average=round(total/len(rows), 2) if rows else 0,
                     exceptions=len(flagged), exception_rate=round(100*len(flagged)/len(rows), 1) if rows else 0,
                     pending=sum(1 for x in rows if x.status.startswith('pending'))),
        categories=by_category, departments=by_department,
        statuses=[dict(status=k, count=v) for k,v in sorted(statuses.items())],
        exceptions=exceptions, insights=insights)
