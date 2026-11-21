from sqlalchemy.orm import Session
from . import models as m

def seed(db: Session):
    if db.query(m.Employee).count(): return
    people = [
        m.Employee(name="Aarav Mehta", email="aarav@northstar.demo", role="employee", department="Engineering", title="Software Engineer"),
        m.Employee(name="Maya Iyer", email="maya@northstar.demo", role="manager", department="Engineering", title="Engineering Manager"),
        m.Employee(name="Rohan Kapoor", email="rohan@northstar.demo", role="employee", department="Sales", title="Account Executive"),
        m.Employee(name="Nisha Rao", email="nisha@northstar.demo", role="manager", department="Sales", title="Sales Director"),
        m.Employee(name="Devika Shah", email="devika@northstar.demo", role="finance", department="Finance", title="Finance Controller"),
    ]
    db.add_all(people); db.flush()
    people[0].manager_id = people[1].id
    people[2].manager_id = people[3].id
    db.add_all([
        m.Project(code="ATLAS", name="Atlas Platform", department="Engineering"),
        m.Project(code="NOVA", name="Nova Launch", department="Sales"),
        m.Project(code="CORE", name="Corporate Operations", department="Finance"),
    ])
    db.add_all([
        m.Policy(name="Employee standard", role="employee", department="*", project_code="*", max_travel=60000, max_expense=15000, receipt_threshold=2000, flag_mode="soft"),
        m.Policy(name="Manager standard", role="manager", department="*", project_code="*", max_travel=90000, max_expense=25000, receipt_threshold=1500, flag_mode="soft"),
        m.Policy(name="Finance control", role="finance", department="*", project_code="*", max_travel=100000, max_expense=30000, receipt_threshold=1000, flag_mode="hard"),
    ])
    db.flush()
    db.add_all([
        m.TravelRequest(employee_id=people[0].id, project_code="ATLAS", purpose="Architecture workshop", origin="Bengaluru", destination="Mumbai", depart_date="2026-12-03", return_date="2026-12-05", flight="IndiGo 6E 5214 · Economy", hotel="The Fern Mumbai · 2 nights", estimated_cost=28400, status="pending_manager"),
        m.TravelRequest(employee_id=people[2].id, project_code="NOVA", purpose="Customer discovery meetings", origin="Delhi", destination="Hyderabad", depart_date="2026-12-08", return_date="2026-12-10", flight="Air India AI 560 · Economy", hotel="Lemon Tree Premier · 2 nights", estimated_cost=38200, status="approved"),
        m.Expense(employee_id=people[0].id, project_code="ATLAS", category="Meals", merchant="Third Wave Coffee", expense_date="2026-11-18", amount=860, description="Team planning breakfast", status="approved"),
        m.Expense(employee_id=people[0].id, project_code="ATLAS", category="Ground transport", merchant="Uber", expense_date="2026-11-19", amount=2450, description="Airport transfer", status="pending_manager"),
        m.Expense(employee_id=people[2].id, project_code="NOVA", category="Hotel", merchant="Lemon Tree", expense_date="2026-11-16", amount=12600, description="Client visit stay", status="pending_manager"),
        m.Expense(employee_id=people[3].id, project_code="NOVA", category="Meals", merchant="Social", expense_date="2026-11-15", amount=4200, description="Customer dinner", status="pending_finance"),
    ])
    db.commit()

def upgrade_demo(db):
    from pathlib import Path
    from shutil import copyfile
    from .policy import UPLOAD_DIR, refresh
    UPLOAD_DIR.mkdir(parents=True,exist_ok=True)
    assets=Path(__file__).parent/'demo_receipts'
    samples=[('rohan@northstar.demo','Lemon Tree','2026-11-16',12600,'lemon-tree-demo.pdf'),('nisha@northstar.demo','Social','2026-11-15',4200,'social-demo.png')]
    for email,merchant,date,amount,name in samples:
        x=db.query(m.Expense).join(m.Employee).filter(m.Employee.email==email,m.Expense.merchant==merchant,m.Expense.expense_date==date,m.Expense.amount==amount).first()
        if x and not x.receipt_path:
            copyfile(assets/name,UPLOAD_DIR/name); x.receipt_path=name
    for x in db.query(m.Expense).all(): refresh(db,x)
    db.commit()
