"""Quran Journey API: Teacher and Parent login only. Student accounts are not login users."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Generator

import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from pwdlib import PasswordHash
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")
if len(JWT_SECRET) < 32:
    raise RuntimeError("JWT_SECRET must contain at least 32 characters")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
password_hash = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)
TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "60"))

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    login_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), index=True)  # teacher or parent
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Student(Base):
    __tablename__ = "students"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    class_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    parent_links: Mapped[list["ParentStudent"]] = relationship(back_populates="student", cascade="all, delete-orphan")

class ParentStudent(Base):
    __tablename__ = "parent_students"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    student: Mapped[Student] = relationship(back_populates="parent_links")

class ReadingEntry(Base):
    __tablename__ = "reading_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    entry_date: Mapped[datetime] = mapped_column(Date, index=True)
    new_lesson: Mapped[str | None] = mapped_column(Text, nullable=True)
    pages: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recent_revision: Mapped[str | None] = mapped_column(Text, nullable=True)
    general_revision: Mapped[str | None] = mapped_column(Text, nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Attendance(Base):
    __tablename__ = "attendance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    attendance_date: Mapped[datetime] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20))  # present, absent, leave
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

class DailyMark(Base):
    __tablename__ = "daily_marks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    mark_date: Mapped[datetime] = mapped_column(Date, index=True)
    points: Mapped[int] = mapped_column(Integer, default=0)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

class LoginInput(BaseModel):
    login_id: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)

class StudentInput(BaseModel):
    student_code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    class_name: str | None = Field(default=None, max_length=100)

class ParentInput(BaseModel):
    login_id: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=10, max_length=256)
    student_ids: list[int] = Field(min_length=1)

class ReadingInput(BaseModel):
    entry_date: datetime
    new_lesson: str | None = None
    pages: str | None = Field(default=None, max_length=200)
    recent_revision: str | None = None
    general_revision: str | None = None
    remarks: str | None = None

class AttendanceInput(BaseModel):
    attendance_date: datetime
    status: str
    remarks: str | None = None

class MarkInput(BaseModel):
    mark_date: datetime
    points: int = Field(ge=0, le=1000)
    remarks: str | None = None

app = FastAPI(title="Quran Journey API", version="0.1.0")
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "https://safumk99-byte.github.io").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Login required")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
        user_id = int(payload.get("sub", 0))
    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Account inactive")
    return user

def require_teacher(user: User = Depends(current_user)) -> User:
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teacher access required")
    return user

def allowed_student_ids(user: User, db: Session) -> set[int] | None:
    if user.role == "teacher":
        return None
    return set(db.scalars(select(ParentStudent.student_id).where(ParentStudent.parent_user_id == user.id)).all())

def check_student_access(student_id: int, user: User, db: Session) -> None:
    if user.role == "teacher":
        return
    if user.role != "parent" or student_id not in (allowed_student_ids(user, db) or set()):
        raise HTTPException(status_code=403, detail="You cannot access this student's records")

@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    # Create the first teacher only when explicitly configured; never seed a default password.
    login_id = os.getenv("INITIAL_TEACHER_ID", "").strip()
    password = os.getenv("INITIAL_TEACHER_PASSWORD", "")
    if login_id and password:
        with SessionLocal() as db:
            existing = db.scalar(select(User).where(User.login_id == login_id))
            if not existing:
                if len(password) < 12:
                    raise RuntimeError("INITIAL_TEACHER_PASSWORD must be at least 12 characters")
                db.add(User(login_id=login_id, password_hash=password_hash.hash(password), role="teacher"))
                db.commit()

@app.get("/health")
def health():
    return {"status": "ok", "service": "quran-journey-api"}

@app.post("/auth/login")
def login(data: LoginInput, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.login_id == data.login_id.strip()))
    if not user or not user.is_active or not password_hash.verify(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid login ID or password")
    token = jwt.encode({"sub": str(user.id), "role": user.role, "exp": datetime.now(timezone.utc) + timedelta(minutes=TOKEN_MINUTES)}, JWT_SECRET, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer", "expires_in": TOKEN_MINUTES * 60, "user": {"id": user.id, "login_id": user.login_id, "role": user.role}}

@app.get("/auth/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "login_id": user.login_id, "role": user.role}

@app.get("/students")
def list_students(user: User = Depends(current_user), db: Session = Depends(get_db)):
    ids = allowed_student_ids(user, db)
    query = select(Student).where(Student.is_active.is_(True))
    if ids is not None:
        if not ids:
            return []
        query = query.where(Student.id.in_(ids))
    return [{"id": s.id, "student_code": s.student_code, "name": s.name, "class_name": s.class_name} for s in db.scalars(query.order_by(Student.name)).all()]

@app.post("/students", status_code=201)
def create_student(data: StudentInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    if db.scalar(select(Student).where(Student.student_code == data.student_code.strip())):
        raise HTTPException(status_code=409, detail="Student code already exists")
    student = Student(student_code=data.student_code.strip(), name=data.name.strip(), class_name=data.class_name)
    db.add(student)
    db.commit()
    db.refresh(student)
    return {"id": student.id, "student_code": student.student_code, "name": student.name, "class_name": student.class_name}

@app.post("/parents", status_code=201)
def create_parent(data: ParentInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    login_id = data.login_id.strip()
    if db.scalar(select(User).where(User.login_id == login_id)):
        raise HTTPException(status_code=409, detail="Login ID already exists")
    if len(set(data.student_ids)) != len(data.student_ids):
        raise HTTPException(status_code=422, detail="Duplicate student IDs")
    students = db.scalars(select(Student).where(Student.id.in_(data.student_ids), Student.is_active.is_(True))).all()
    if len(students) != len(data.student_ids):
        raise HTTPException(status_code=422, detail="One or more student IDs do not exist")
    parent = User(login_id=login_id, password_hash=password_hash.hash(data.password), role="parent")
    db.add(parent)
    db.flush()
    for student in students:
        db.add(ParentStudent(parent_user_id=parent.id, student_id=student.id))
    db.commit()
    return {"id": parent.id, "login_id": parent.login_id, "role": parent.role, "linked_students": len(students)}

@app.get("/students/{student_id}/reading")
def get_reading(student_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    check_student_access(student_id, user, db)
    rows = db.scalars(select(ReadingEntry).where(ReadingEntry.student_id == student_id).order_by(ReadingEntry.entry_date.desc(), ReadingEntry.id.desc())).all()
    return [{"id": r.id, "date": r.entry_date.isoformat(), "new_lesson": r.new_lesson, "pages": r.pages, "recent_revision": r.recent_revision, "general_revision": r.general_revision, "remarks": r.remarks} for r in rows]

@app.post("/students/{student_id}/reading", status_code=201)
def add_reading(student_id: int, data: ReadingInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    if not db.get(Student, student_id):
        raise HTTPException(status_code=404, detail="Student not found")
    row = ReadingEntry(student_id=student_id, entry_date=data.entry_date.date(), new_lesson=data.new_lesson, pages=data.pages, recent_revision=data.recent_revision, general_revision=data.general_revision, remarks=data.remarks)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "student_id": row.student_id, "date": row.entry_date.isoformat()}

@app.get("/students/{student_id}/attendance")
def get_attendance(student_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    check_student_access(student_id, user, db)
    rows = db.scalars(select(Attendance).where(Attendance.student_id == student_id).order_by(Attendance.attendance_date.desc())).all()
    return [{"id": r.id, "date": r.attendance_date.isoformat(), "status": r.status, "remarks": r.remarks} for r in rows]

@app.post("/students/{student_id}/attendance", status_code=201)
def add_attendance(student_id: int, data: AttendanceInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    if data.status not in {"present", "absent", "leave"}:
        raise HTTPException(status_code=422, detail="Status must be present, absent, or leave")
    if not db.get(Student, student_id):
        raise HTTPException(status_code=404, detail="Student not found")
    row = Attendance(student_id=student_id, attendance_date=data.attendance_date.date(), status=data.status, remarks=data.remarks)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "student_id": row.student_id, "date": row.attendance_date.isoformat(), "status": row.status}

@app.get("/students/{student_id}/marks")
def get_marks(student_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    check_student_access(student_id, user, db)
    rows = db.scalars(select(DailyMark).where(DailyMark.student_id == student_id).order_by(DailyMark.mark_date.desc())).all()
    return [{"id": r.id, "date": r.mark_date.isoformat(), "points": r.points, "remarks": r.remarks} for r in rows]

@app.post("/students/{student_id}/marks", status_code=201)
def add_mark(student_id: int, data: MarkInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    if not db.get(Student, student_id):
        raise HTTPException(status_code=404, detail="Student not found")
    row = DailyMark(student_id=student_id, mark_date=data.mark_date.date(), points=data.points, remarks=data.remarks)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "student_id": row.student_id, "date": row.mark_date.isoformat(), "points": row.points}
