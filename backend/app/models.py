from sqlalchemy import String, Integer, Float, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
from .database import Base

def now():
    return datetime.now(timezone.utc)

class Employee(Base):
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(150), unique=True)
    role: Mapped[str] = mapped_column(String(30))
    department: Mapped[str] = mapped_column(String(80))
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(100), default="Employee")

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    department: Mapped[str] = mapped_column(String(80))

class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(30))
    department: Mapped[str] = mapped_column(String(80), default="*")
    project_code: Mapped[str] = mapped_column(String(20), default="*")
    max_travel: Mapped[float] = mapped_column(Float, default=50000)
    max_expense: Mapped[float] = mapped_column(Float, default=15000)
    receipt_threshold: Mapped[float] = mapped_column(Float, default=2000)
    flag_mode: Mapped[str] = mapped_column(String(10), default="soft") # soft | hard
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

class TravelRequest(Base):
    __tablename__ = "travel_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    project_code: Mapped[str] = mapped_column(String(20))
    purpose: Mapped[str] = mapped_column(String(250))
    origin: Mapped[str] = mapped_column(String(80))
    destination: Mapped[str] = mapped_column(String(80))
    depart_date: Mapped[str] = mapped_column(String(20))
    return_date: Mapped[str] = mapped_column(String(20))
    flight: Mapped[str] = mapped_column(String(160))
    hotel: Mapped[str] = mapped_column(String(160))
    estimated_cost: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), default="pending_manager")
    policy_flag: Mapped[str] = mapped_column(String(250), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    employee = relationship("Employee")

class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    project_code: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(50))
    merchant: Mapped[str] = mapped_column(String(120))
    expense_date: Mapped[str] = mapped_column(String(20))
    amount: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(String(250), default="")
    receipt_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending_manager")
    policy_flag: Mapped[str] = mapped_column(String(250), default="")
    card_transaction_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    employee = relationship("Employee")

class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_type: Mapped[str] = mapped_column(String(20))
    item_id: Mapped[int] = mapped_column(Integer)
    step: Mapped[str] = mapped_column(String(30))
    approver_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    decision: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    approver = relationship("Employee")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_type: Mapped[str] = mapped_column(String(20))
    item_id: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    action: Mapped[str] = mapped_column(String(100))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    actor = relationship("Employee")

class PolicyEvaluation(Base):
    __tablename__ = 'policy_evaluations'
    id: Mapped[int] = mapped_column(primary_key=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey('expenses.id'))
    actor_id: Mapped[int] = mapped_column(ForeignKey('employees.id'))
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
