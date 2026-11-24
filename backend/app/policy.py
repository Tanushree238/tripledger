import json, hashlib, os
from pathlib import Path
from sqlalchemy import case
from . import models as m
UPLOAD_DIR=Path(os.getenv('UPLOAD_DIR','./uploads'))

def receipt_requests(db):
    return db.query(m.AuditLog.item_id).filter(
        m.AuditLog.item_type == 'expense',
        m.AuditLog.action == 'receipt_requested',
    )

def policy_for(db, person, project):
    return db.query(m.Policy).filter(m.Policy.enabled.is_(True),m.Policy.role==person.role,m.Policy.department.in_(['*',person.department]),m.Policy.project_code.in_(['*',project])).order_by(case((m.Policy.department==person.department,1),else_=0).desc(),case((m.Policy.project_code==project,1),else_=0).desc(),m.Policy.id.desc()).first()
def receipt_file(x):
    name=x.receipt_path
    if not name or Path(name).name!=name: return None
    path=UPLOAD_DIR/name
    return path if path.is_file() else None
def snapshot(p):
    if not p:return None
    d={k:getattr(p,k) for k in ('id','name','role','department','project_code','max_expense','receipt_threshold','max_travel','flag_mode')}
    d['version']=hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest()[:12]
    return d
def evaluate(amount,attached,p):
    if not p:return {'policy':None,'checks':[],'violations':[],'receipt_attached':attached}
    checks=[{'name':'Maximum expense','actual':amount,'limit':p['max_expense'],'passed':amount<=p['max_expense'],'reason':f"Amount exceeds expense limit of ₹{p['max_expense']:,.0f}"},{'name':'Receipt requirement','actual':amount,'limit':p['receipt_threshold'],'passed':amount<=p['receipt_threshold'] or attached,'reason':f"Receipt required above ₹{p['receipt_threshold']:,.0f}"}]
    return {'policy':p,'checks':checks,'violations':[c['reason'] for c in checks if not c['passed']],'receipt_attached':attached}
def refresh(db,x,actor=None,latest=False):
    old=db.query(m.PolicyEvaluation).filter_by(expense_id=x.id).order_by(m.PolicyEvaluation.id.desc()).first()
    previous=json.loads(old.payload) if old else None
    p=previous['policy'] if previous and not latest else snapshot(policy_for(db,x.employee,x.project_code))
    result=evaluate(x.amount,bool(receipt_file(x)),p)
    x.policy_flag='; '.join(result['violations'])
    if result!=previous:
        db.add(m.PolicyEvaluation(expense_id=x.id,payload=json.dumps(result),actor_id=actor.id if actor else x.employee_id))
    return result
