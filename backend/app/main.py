import os, csv, io, uuid, json
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from .database import Base, engine, get_db, SessionLocal
from . import models as m, schemas as s
from .seed import seed, upgrade_demo
from .policy import policy_for, refresh, receipt_file, receipt_requests, evaluate, snapshot

app = FastAPI(title="TripLedger API", version="1.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads")); UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed(db)
        upgrade_demo(db)

def current_user(db: Session = Depends(get_db), role: str = Header("employee", alias="X-Demo-Role"), user: str = Header("aarav@northstar.demo", alias="X-Demo-User")):
    person = db.query(m.Employee).filter(m.Employee.email == user).first()
    if not person: raise HTTPException(401, "Unknown demo user")
    return person

def log(db, typ, item, actor, action, detail=""):
    db.add(m.AuditLog(item_type=typ, item_id=item, actor_id=actor.id, action=action, detail=detail))

def item_dict(x):
    d = {c.name: getattr(x, c.name) for c in x.__table__.columns}
    d["employee"] = x.employee.name if hasattr(x, "employee") and x.employee else ""
    if isinstance(x,m.Expense):
        from sqlalchemy.orm import object_session
        db=object_session(x)
        row=db.query(m.PolicyEvaluation).filter_by(expense_id=x.id).order_by(m.PolicyEvaluation.id.desc()).first()
        d["policy_evaluation"]=json.loads(row.payload) if row else None
        d["receipt_path"]=x.receipt_path if receipt_file(x) else None
        d["receipt_requested"] = (
            not d["receipt_path"]
            and receipt_requests(db).filter(m.AuditLog.item_id == x.id).first() is not None
        )
    return d

def visible_query(db, user, model):
    q = db.query(model)
    if user.role == "employee": q = q.filter(model.employee_id == user.id)
    elif user.role == "manager": q = q.join(m.Employee, model.employee_id == m.Employee.id).filter(m.Employee.manager_id == user.id)
    return q

@app.get("/health")
def health(): return {"ok": True, "currency": "INR"}

@app.get("/bootstrap")
def bootstrap(db: Session = Depends(get_db), user: m.Employee = Depends(current_user)):
    return {"user": {"id":user.id,"name":user.name,"role":user.role,"department":user.department,"title":user.title},
      "employees":[{"id":x.id,"name":x.name,"role":x.role,"department":x.department,"email":x.email} for x in db.query(m.Employee).all()],
      "projects":[{"code":x.code,"name":x.name,"department":x.department} for x in db.query(m.Project).all()],
      "policies":[{c.name:getattr(x,c.name) for c in x.__table__.columns} for x in db.query(m.Policy).all()],
      "flights":[{"name":"IndiGo 6E 5214 · Economy","price":8900},{"name":"Air India AI 603 · Economy","price":11200},{"name":"Vistara UK 863 · Economy","price":13900}],
      "hotels":[{"name":"The Fern Mumbai · 2 nights","price":9800},{"name":"Lemon Tree Premier · 2 nights","price":12400},{"name":"ibis Mumbai · 2 nights","price":7600}]}

@app.get("/travel")
def travels(db: Session=Depends(get_db), user=Depends(current_user), scope:str="default"):
    return [item_dict(x) for x in (db.query(m.TravelRequest).filter(m.TravelRequest.employee_id==user.id) if scope=="personal" else visible_query(db,user,m.TravelRequest)).order_by(m.TravelRequest.created_at.desc()).all()]

@app.post("/travel")
def create_travel(data:s.TravelCreate, db:Session=Depends(get_db), user=Depends(current_user)):
    p=policy_for(db,user,data.project_code); flag=""
    if p and data.estimated_cost > p.max_travel: flag=f"Estimate exceeds travel limit of ₹{p.max_travel:,.0f}"
    if flag and p.flag_mode=="hard": raise HTTPException(400,flag)
    x=m.TravelRequest(employee_id=user.id, **data.model_dump(), policy_flag=flag)
    db.add(x); db.flush(); log(db,"travel",x.id,user,"submitted",flag or "Travel request submitted"); db.commit()
    return item_dict(x)

@app.get("/expenses")
def expenses(db:Session=Depends(get_db), user=Depends(current_user), scope:str="default"):
    return [item_dict(x) for x in (db.query(m.Expense).filter(m.Expense.employee_id==user.id) if scope=="personal" else visible_query(db,user,m.Expense)).order_by(m.Expense.created_at.desc()).all()]

@app.post("/expenses")
def create_expense(data:s.ExpenseCreate, db:Session=Depends(get_db), user=Depends(current_user)):
    p=policy_for(db,user,data.project_code)
    if p and p.flag_mode=='hard' and data.amount>p.max_expense: raise HTTPException(400,'Expense limit exceeded')
    x=m.Expense(employee_id=user.id, **data.model_dump(), status='pending_manager' if user.manager_id else 'pending_finance')
    db.add(x); db.flush(); refresh(db,x,user); log(db,'expense',x.id,user,'submitted',x.policy_flag or 'Expense submitted'); db.commit()
    return item_dict(x)

@app.patch("/expenses/{item_id}")
def update_expense(item_id:int, data:s.ExpenseUpdate, db:Session=Depends(get_db), user=Depends(current_user)):
    x=db.query(m.Expense).filter_by(id=item_id).first()
    if not x or x.employee_id!=user.id: raise HTTPException(404,"Expense not found")
    if x.status not in ("draft","pending_manager"): raise HTTPException(400,"This expense can no longer be edited")
    changes=data.model_dump(exclude_unset=True,exclude_none=True)
    for k,v in changes.items(): setattr(x,k,v)
    result=refresh(db,x,user,latest="project_code" in changes)
    if result["policy"] and result["policy"]["flag_mode"]=="hard" and result["checks"] and not result["checks"][0]["passed"]: raise HTTPException(400,"Expense limit exceeded")
    log(db,"expense",x.id,user,"edited","Fields updated"); db.commit(); return item_dict(x)

@app.post("/expenses/{item_id}/receipt")
async def upload_receipt(item_id:int, file:UploadFile=File(...), db:Session=Depends(get_db), user=Depends(current_user)):
    x=db.query(m.Expense).filter_by(id=item_id).first()
    if not x or x.employee_id!=user.id: raise HTTPException(404,"Expense not found")
    if x.status not in ("draft","pending_manager","pending_finance"): raise HTTPException(400,"Expense is closed")
    content=await file.read(10*1024*1024+1)
    ext=Path(file.filename or "receipt.bin").suffix.lower()
    signatures={".pdf":b"%PDF-",".png":b"\x89PNG\r\n\x1a\n",".jpg":b"\xff\xd8",".jpeg":b"\xff\xd8"}
    if ext not in signatures or not content.startswith(signatures[ext]) or len(content)>10*1024*1024: raise HTTPException(400,"Use a valid PDF, PNG or JPEG under 10 MB")
    name=f"{uuid.uuid4().hex}{ext}"
    (UPLOAD_DIR/name).write_bytes(content)
    x.receipt_path=name
    refresh(db,x,user)
    log(db,"expense",x.id,user,"receipt_uploaded",file.filename or name); db.commit()
    # Mock OCR payload: UI lets the employee review and edit these values.
    return {"receipt_path":name,"extracted":{"merchant":x.merchant,"amount":x.amount,"expense_date":x.expense_date,"category":x.category}}

@app.get("/approvals")
def approvals(db:Session=Depends(get_db), user=Depends(current_user)):
    if user.role=="finance":
        ts=db.query(m.TravelRequest).filter(m.TravelRequest.status=="pending_finance").all()
        es=db.query(m.Expense).filter(m.Expense.status=="pending_finance").all()
    elif user.role=="manager":
        ts=visible_query(db,user,m.TravelRequest).filter(m.TravelRequest.status=="pending_manager").all()
        es=visible_query(db,user,m.Expense).filter(m.Expense.status=="pending_manager").all()
    else: return []
    return [{"type":"travel","item":item_dict(x)} for x in ts]+[{"type":"expense","item":item_dict(x)} for x in es]

@app.post("/approvals/{typ}/{item_id}")
def decide(typ:str,item_id:int,data:s.Decision,db:Session=Depends(get_db),user=Depends(current_user)):
    if data.decision not in ("approved","rejected"): raise HTTPException(400,"Invalid decision")
    model=m.TravelRequest if typ=="travel" else m.Expense if typ=="expense" else None
    if model is None: raise HTTPException(404,"Unknown item type")
    x=db.query(model).filter_by(id=item_id).first()
    if not x: raise HTTPException(404,"Item not found")
    if user.role=="manager" and x.status=="pending_manager":
        owner=db.query(m.Employee).filter_by(id=x.employee_id).first()
        if owner.manager_id!=user.id: raise HTTPException(403,"Not your report")
        step="manager"
        if data.decision=="approved": x.status="pending_finance" if (x.policy_flag or (x.amount if typ=="expense" else x.estimated_cost)>=25000) else "approved"
        else: x.status="rejected"
    elif user.role=="finance" and x.status=="pending_finance":
        step="finance"; x.status=data.decision
    else: raise HTTPException(403,"This item is not awaiting your approval")
    db.add(m.Approval(item_type=typ,item_id=x.id,step=step,approver_id=user.id,decision=data.decision,comment=data.comment))
    log(db,typ,x.id,user,data.decision,f"{step}: {data.comment}"); db.commit()
    return {"ok":True,"status":x.status}

@app.get("/audit/{typ}/{item_id}")
def audit(typ:str,item_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    model=m.Expense if typ=="expense" else m.TravelRequest if typ=="travel" else None
    if model is None: raise HTTPException(404,"Unknown item type")
    item=db.query(model).filter_by(id=item_id).first()
    if not item: raise HTTPException(404,"Record not found")
    owner=db.query(m.Employee).filter_by(id=item.employee_id).first()
    if user.role!="finance" and item.employee_id!=user.id and not (user.role=="manager" and owner and owner.manager_id==user.id): raise HTTPException(403,"Access denied")
    rows=db.query(m.AuditLog).filter_by(item_type=typ,item_id=item_id).order_by(m.AuditLog.created_at.desc()).all()
    return [{"action":x.action,"detail":x.detail,"actor":x.actor.name,"created_at":x.created_at.isoformat()} for x in rows]

@app.get("/finance/summary")
def finance_summary(db:Session=Depends(get_db),user=Depends(current_user)):
    if user.role!="finance": raise HTTPException(403,"Finance role required")
    expenses=db.query(m.Expense).all()
    total=sum(x.amount for x in expenses)
    exceptions=sum(1 for x in expenses if x.policy_flag)
    by_cat={}
    for x in expenses: by_cat[x.category]=by_cat.get(x.category,0)+x.amount
    return {"total_spend":total,"expense_count":len(expenses),"exceptions":exceptions,"pending":sum(x.status.startswith("pending") for x in expenses),
      "by_category":[{"category":k,"amount":v} for k,v in by_cat.items()],
      "recent":[item_dict(x) for x in sorted(expenses,key=lambda a:a.created_at,reverse=True)[:8]]}

@app.patch("/policies/{policy_id}")
def update_policy(policy_id:int,data:s.PolicyUpdate,db:Session=Depends(get_db),user=Depends(current_user)):
    if user.role!="finance": raise HTTPException(403,"Finance role required")
    p=db.query(m.Policy).filter_by(id=policy_id).first()
    if not p: raise HTTPException(404,"Policy not found")
    for k,v in data.model_dump().items(): setattr(p,k,v)
    log(db,"policy",p.id,user,"policy_updated",f"Updated {p.name}"); db.commit()
    return {"ok":True}

@app.get("/finance/export.csv")
def export_csv(db:Session=Depends(get_db),user=Depends(current_user)):
    if user.role!="finance": raise HTTPException(403,"Finance role required")
    out=io.StringIO(); w=csv.writer(out)
    w.writerow(["Expense ID","Employee","Department","Project","Date","Category","Merchant","Amount INR","Status","Policy flag"])
    for x in db.query(m.Expense).all():
        w.writerow([x.id,x.employee.name,x.employee.department,x.project_code,x.expense_date,x.category,x.merchant,x.amount,x.status,x.policy_flag])
    return StreamingResponse(iter([out.getvalue()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=tripledger-expenses.csv"})

@app.get("/finance/card-feed")
def card_feed(user=Depends(current_user)):
    if user.role!="finance": raise HTTPException(403,"Finance role required")
    return [{"id":"CARD-8841","employee":"Aarav Mehta","merchant":"Uber","amount":2450,"date":"2026-11-19","matched":False},
      {"id":"CARD-8842","employee":"Rohan Kapoor","merchant":"Lemon Tree","amount":12600,"date":"2026-11-16","matched":True},
      {"id":"CARD-8843","employee":"Maya Iyer","merchant":"IndiGo","amount":8900,"date":"2026-11-14","matched":False}]

@app.post("/finance/accounting-export")
def accounting_export(user=Depends(current_user),db:Session=Depends(get_db)):
    if user.role!="finance": raise HTTPException(403,"Finance role required")
    count=db.query(m.Expense).filter(m.Expense.status=="approved").count()
    return {"ok":True,"system":"MockBooks ERP","exported_records":count,"batch_id":f"MOCK-{uuid.uuid4().hex[:8].upper()}","message":"Approved expenses queued for accounting export."}


def authorized_expense(db,user,item_id,*,lock=False):
    x=db.get(m.Expense,item_id,with_for_update=lock)
    if not x or not (user.role=='finance' or x.employee_id==user.id or (user.role=='manager' and x.employee.manager_id==user.id)): raise HTTPException(404,'Expense not found')
    return x

@app.get('/expenses/{item_id}/receipt')
def get_receipt(item_id:int,download:bool=False,db:Session=Depends(get_db),user=Depends(current_user)):
    x=authorized_expense(db,user,item_id); path=receipt_file(x)
    if not path: raise HTTPException(404,'Receipt not found')
    return FileResponse(path,filename=path.name,content_disposition_type='attachment' if download else 'inline',headers={'X-Content-Type-Options':'nosniff'})

@app.post('/expenses/{item_id}/reevaluate')
def reevaluate(item_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    if user.role!='finance': raise HTTPException(403,'Finance role required')
    x=authorized_expense(db,user,item_id)
    if not x.status.startswith('pending'): raise HTTPException(400,'Only pending expenses can be re-evaluated')
    refresh(db,x,user,latest=True); log(db,'expense',x.id,user,'policy_reevaluated'); db.commit(); return item_dict(x)

@app.post('/expenses/{item_id}/request-receipt')
def request_receipt(item_id:int,db:Session=Depends(get_db),user=Depends(current_user)):
    x=authorized_expense(db,user,item_id,lock=True)
    if user.role not in ('manager','finance') or x.employee_id==user.id: raise HTTPException(403,'Reviewer required')
    if receipt_file(x) or not x.status.startswith('pending'): raise HTTPException(400,'Receipt request not applicable')
    if receipt_requests(db).filter(m.AuditLog.item_id == x.id).first() is None:
        log(db,'expense',x.id,user,'receipt_requested','Please attach supporting receipt')
    db.commit()
    return {'ok':True}

from .ai.routes import make_router
app.include_router(make_router(current_user))
