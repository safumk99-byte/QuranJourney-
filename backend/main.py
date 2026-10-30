"""Quran Journey API: Teacher and Parent login only. Student accounts are not login users."""
from __future__ import annotations

import os
import json
import random
import uuid
from urllib.error import URLError, HTTPError
from urllib.request import urlopen
from datetime import date, datetime, timedelta, timezone
from typing import Generator
from zoneinfo import ZoneInfo

import jwt
from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator, model_validator
from pwdlib import PasswordHash
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, select, text as sql_text
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
TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "43200"))  # 30-day persistent sessions by default

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
    total_pages: Mapped[int] = mapped_column(Integer, default=604)
    completed_pages: Mapped[float] = mapped_column(Float, default=0.0)
    current_juz: Mapped[int] = mapped_column(Integer, default=1)
    journey_start_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    photo_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    cleanliness_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discipline_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    worship_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    legacy_id: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
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
    start_surah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_ayah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_surah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_ayah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recent_start_surah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recent_start_ayah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recent_end_surah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recent_end_ayah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    general_start_surah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    general_start_ayah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    general_end_surah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    general_end_ayah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recent_pages: Mapped[str | None] = mapped_column(String(20), nullable=True)
    general_pages: Mapped[str | None] = mapped_column(String(20), nullable=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    entry_date: Mapped[datetime] = mapped_column(Date, index=True)
    new_lesson: Mapped[str | None] = mapped_column(Text, nullable=True)
    pages: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recent_revision: Mapped[str | None] = mapped_column(Text, nullable=True)
    general_revision: Mapped[str | None] = mapped_column(Text, nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    legacy_id: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Attendance(Base):
    __tablename__ = "attendance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    attendance_date: Mapped[datetime] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20))  # present, late, absent, leave
    period: Mapped[int] = mapped_column(Integer, default=1, index=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    legacy_id: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)

class DailyMark(Base):
    __tablename__ = "daily_marks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    mark_date: Mapped[datetime] = mapped_column(Date, index=True)
    points: Mapped[int] = mapped_column(Integer, default=0)
    score_s: Mapped[int] = mapped_column(Integer, default=0)
    score_ms: Mapped[int] = mapped_column(Integer, default=0)
    score_mu: Mapped[int] = mapped_column(Integer, default=0)
    legacy_id: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)


class ParentNotification(Base):
    __tablename__ = "parent_notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    event_key: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(180))
    message: Mapped[str] = mapped_column(Text)
    notification_type: Mapped[str] = mapped_column(String(40), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DisciplineEntry(Base):
    __tablename__ = "discipline_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(String(200))
    points_deducted: Mapped[int] = mapped_column(Integer)
    incident_date: Mapped[date] = mapped_column(Date, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    is_reversed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reversed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversal_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)


class ChallengeRange(Base):
    __tablename__ = "challenge_ranges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    surah: Mapped[int] = mapped_column(Integer, default=1)
    start_ayah: Mapped[int] = mapped_column(Integer, default=1)
    end_ayah: Mapped[int] = mapped_column(Integer, default=1)
    start_juz: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_juz: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="Learning")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class ChallengeSession(Base):
    __tablename__ = "challenge_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    challenge_date: Mapped[date] = mapped_column(Date, index=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    questions: Mapped[list["ChallengeQuestion"]] = relationship(back_populates="session", cascade="all, delete-orphan", order_by="ChallengeQuestion.question_no")

class ChallengeQuestion(Base):
    __tablename__ = "challenge_questions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("challenge_sessions.id", ondelete="CASCADE"), index=True)
    question_no: Mapped[int] = mapped_column(Integer)
    question_text: Mapped[str] = mapped_column(Text, default="")
    expected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    audio_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    review_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    teacher_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    session: Mapped[ChallengeSession] = relationship(back_populates="questions")

class ExamSession(Base):
    __tablename__ = "exam_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    exam_date: Mapped[date] = mapped_column(Date, index=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    total_marks: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    questions: Mapped[list["ExamQuestion"]] = relationship(back_populates="session", cascade="all, delete-orphan", order_by="ExamQuestion.question_no")

class ExamQuestion(Base):
    __tablename__ = "exam_questions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("exam_sessions.id", ondelete="CASCADE"), index=True)
    question_no: Mapped[int] = mapped_column(Integer)
    question_text: Mapped[str] = mapped_column(Text, default="")
    expected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_marks: Mapped[int] = mapped_column(Integer, default=5)
    awarded_marks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    teacher_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    session: Mapped[ExamSession] = relationship(back_populates="questions")

class ChallengeAudioInput(BaseModel):
    audio_base64: str = Field(min_length=1, max_length=7_000_000)
    audio_type: str = Field(default="audio/webm", max_length=100)

class ChallengeRangeInput(BaseModel):
    start_juz: int = Field(ge=1, le=30)
    end_juz: int = Field(ge=1, le=30)
    status: str = Field(default="Learning", pattern="^(Learning|Completed)$")
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_juz_range(self):
        if self.end_juz < self.start_juz:
            raise ValueError("End Juz must be greater than or equal to Start Juz")
        return self

class ChallengeQuestionInput(BaseModel):
    text: str = Field(default="", max_length=3000)
    expected: str | None = Field(default=None, max_length=1000)
    submitted: bool = False
    review: int | None = Field(default=None)
    note: str | None = Field(default=None, max_length=1000)
    audio_base64: str | None = Field(default=None, max_length=7_000_000)
    audio_type: str | None = Field(default=None, max_length=100)

    @field_validator("review")
    @classmethod
    def valid_review(cls, value):
        if value not in (None, 0, 10, 20):
            raise ValueError("Review score must be 0, 10 or 20")
        return value

class ChallengeSessionInput(BaseModel):
    date: date
    questions: list[ChallengeQuestionInput] = Field(min_length=5, max_length=5)
    confirmed: bool = False
    score: int = Field(default=0, ge=0, le=100)

class ExamGenerateInput(BaseModel):
    date: date
    question_count: int = Field(ge=1, le=100)

class ExamQuestionInput(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    expected: str | None = Field(default=None, max_length=1000)
    max_marks: int = Field(ge=1, le=1000)
    awarded_marks: int | None = Field(default=None, ge=0, le=1000)
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_marks(self):
        if self.awarded_marks is not None and self.awarded_marks > self.max_marks:
            raise ValueError("Awarded marks cannot exceed maximum marks")
        return self

class ExamSaveInput(BaseModel):
    date: date
    confirmed: bool = False
    questions: list[ExamQuestionInput] = Field(min_length=1, max_length=100)

class TeacherNotificationInput(BaseModel):
    student_id: int | None = Field(default=None, gt=0)
    title: str = Field(min_length=2, max_length=180)
    message: str = Field(min_length=2, max_length=2000)

    @field_validator("title", "message")
    @classmethod
    def notification_text_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title and message cannot be blank")
        return value


class DisciplineInput(BaseModel):
    student_id: int = Field(gt=0)
    reason: str = Field(min_length=2, max_length=200)
    points_deducted: int = Field(gt=0, le=100)
    incident_date: date
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Reason cannot be blank")
        return value.strip()

    @field_validator("notes")
    @classmethod
    def clean_notes(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

class DisciplineReverseInput(BaseModel):
    reason: str = Field(min_length=3, max_length=300)

    @field_validator("reason")
    @classmethod
    def reversal_reason_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A correction reason is required")
        return value.strip()

class LegacyMigrationInput(BaseModel):
    students: list[dict] = Field(default_factory=list, max_length=5000)
    photos: dict[str, str] = Field(default_factory=dict)
    daily_marks: list[dict] = Field(default_factory=list, max_length=20000)
    reading_entries: list[dict] = Field(default_factory=list, max_length=50000)
    reading_base_pages: dict[str, int | float] = Field(default_factory=dict)

class LoginInput(BaseModel):
    login_id: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)

class StudentInput(BaseModel):
    student_code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    class_name: str | None = Field(default=None, max_length=100)
    total_pages: int = Field(default=604, ge=1, le=2000)
    completed_pages: float = Field(default=0, ge=0, le=2000)
    current_juz: int = Field(default=1, ge=1, le=30)
    journey_start_date: date | None = None
    photo_data: str | None = None

    @model_validator(mode="after")
    def validate_progress(self):
        if self.completed_pages > self.total_pages:
            raise ValueError("Completed pages cannot exceed total pages")
        return self

    @field_validator("student_code", "name")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value

    @field_validator("class_name")
    @classmethod
    def normalize_class_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

class StudentUpdateInput(BaseModel):
    student_code: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    class_name: str | None = Field(default=None, max_length=100)
    total_pages: int | None = Field(default=None, ge=1, le=2000)
    completed_pages: float | None = Field(default=None, ge=0, le=2000)
    current_juz: int | None = Field(default=None, ge=1, le=30)
    journey_start_date: date | None = None
    photo_data: str | None = None
    cleanliness_points: int | None = Field(default=None, ge=0, le=100000)
    discipline_points: int | None = Field(default=None, ge=0, le=100000)
    worship_points: int | None = Field(default=None, ge=0, le=100000)

    @field_validator("student_code", "name")
    @classmethod
    def strip_optional_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value

    @field_validator("class_name")
    @classmethod
    def normalize_optional_class_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_progress(self):
        if self.total_pages is not None and self.completed_pages is not None and self.completed_pages > self.total_pages:
            raise ValueError("Completed pages cannot exceed total pages")
        return self


class ParentInput(BaseModel):
    login_id: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=10, max_length=256)
    student_ids: list[int] = Field(min_length=1)

SURAH_AYAH_COUNTS = [7,286,200,176,120,165,206,75,129,109,123,111,43,52,99,128,111,110,98,135,112,78,118,64,77,227,93,88,69,60,34,30,73,54,45,83,182,88,75,85,54,53,89,59,37,35,38,29,18,45,60,49,62,55,78,96,29,22,24,13,14,11,11,18,12,12,30,52,52,44,28,28,20,56,40,31,50,40,46,42,29,19,36,25,22,17,19,26,30,20,15,21,11,8,8,19,5,8,8,11,11,8,3,9,5,4,7,3,6,3,5,4,5,6]

def validate_quran_range(start_surah: int, start_ayah: int, end_surah: int, end_ayah: int) -> None:
    if not (1 <= start_surah <= 114 and 1 <= end_surah <= 114):
        raise ValueError("Surah number must be between 1 and 114")
    if start_ayah < 1 or end_ayah < 1 or start_ayah > SURAH_AYAH_COUNTS[start_surah - 1] or end_ayah > SURAH_AYAH_COUNTS[end_surah - 1]:
        raise ValueError("Ayah number exceeds the selected Surah's length")
    # Reject a backwards range; start must precede or equal end in Quran order.
    if (start_surah, start_ayah) > (end_surah, end_ayah):
        raise ValueError("End Surah/Ayah must be after or equal to Start Surah/Ayah")

class ReadingInput(BaseModel):
    entry_date: datetime
    # Optional for backwards compatibility with older clients and imported records.
    start_surah: int | None = Field(default=None, ge=1, le=114)
    start_ayah: int | None = Field(default=None, ge=1, le=286)
    end_surah: int | None = Field(default=None, ge=1, le=114)
    end_ayah: int | None = Field(default=None, ge=1, le=286)
    recent_start_surah: int | None = Field(default=None, ge=1, le=114)
    recent_start_ayah: int | None = Field(default=None, ge=1, le=286)
    recent_end_surah: int | None = Field(default=None, ge=1, le=114)
    recent_end_ayah: int | None = Field(default=None, ge=1, le=286)
    general_start_surah: int | None = Field(default=None, ge=1, le=114)
    general_start_ayah: int | None = Field(default=None, ge=1, le=286)
    general_end_surah: int | None = Field(default=None, ge=1, le=114)
    general_end_ayah: int | None = Field(default=None, ge=1, le=286)

    @model_validator(mode="after")
    def validate_range(self):
        for value, maximum in ((self.pages, 5), (self.recent_pages, 10), (self.general_pages, 10)):
            if value is not None:
                try:
                    n = float(value)
                except (TypeError, ValueError):
                    raise ValueError("Lesson pages must be 0–5; revision pages must be 0–10, in half-page increments")
                if n < 0 or n > maximum or abs(n * 2 - round(n * 2)) > 1e-9:
                    raise ValueError("Lesson pages must be 0–5; revision pages must be 0–10, in half-page increments")
        for prefix in ("", "recent_", "general_"):
            keys = (f"{prefix}start_surah", f"{prefix}start_ayah", f"{prefix}end_surah", f"{prefix}end_ayah")
            values = tuple(getattr(self, key) for key in keys)
            if any(value is not None for value in values):
                if any(value is None for value in values):
                    raise ValueError(f"All four Surah/Ayah fields must be provided together for {prefix or 'new lesson'}")
                validate_quran_range(*values)
        return self

    new_lesson: str | None = None
    pages: str | None = Field(default=None, max_length=200)
    recent_revision: str | None = None
    recent_pages: str | None = Field(default="0", max_length=20)
    general_revision: str | None = None
    general_pages: str | None = Field(default="0", max_length=20)
    remarks: str | None = None

class ReadingUpdateInput(BaseModel):
    entry_date: datetime | None = None
    start_surah: int | None = Field(default=None, ge=1, le=114)
    start_ayah: int | None = Field(default=None, ge=1, le=286)
    end_surah: int | None = Field(default=None, ge=1, le=114)
    end_ayah: int | None = Field(default=None, ge=1, le=286)
    recent_start_surah: int | None = Field(default=None, ge=1, le=114)
    recent_start_ayah: int | None = Field(default=None, ge=1, le=286)
    recent_end_surah: int | None = Field(default=None, ge=1, le=114)
    recent_end_ayah: int | None = Field(default=None, ge=1, le=286)
    general_start_surah: int | None = Field(default=None, ge=1, le=114)
    general_start_ayah: int | None = Field(default=None, ge=1, le=286)
    general_end_surah: int | None = Field(default=None, ge=1, le=114)
    general_end_ayah: int | None = Field(default=None, ge=1, le=286)
    new_lesson: str | None = None
    pages: str | None = Field(default=None, max_length=200)
    recent_revision: str | None = None
    recent_pages: str | None = Field(default=None, max_length=20)
    general_revision: str | None = None
    general_pages: str | None = Field(default=None, max_length=20)
    remarks: str | None = None

    @model_validator(mode="after")
    def validate_activity_pages(self):
        for value, maximum in ((self.pages, 5), (self.recent_pages, 10), (self.general_pages, 10)):
            if value is not None:
                try:
                    n = float(value)
                except (TypeError, ValueError):
                    raise ValueError("Lesson pages must be 0–5; revision pages must be 0–10, in half-page increments")
                if n < 0 or n > maximum or abs(n * 2 - round(n * 2)) > 1e-9:
                    raise ValueError("Lesson pages must be 0–5; revision pages must be 0–10, in half-page increments")
        return self

class AttendanceInput(BaseModel):
    attendance_date: datetime
    status: str
    period: int = Field(default=1, ge=1, le=3)
    remarks: str | None = None

class MarkInput(BaseModel):
    mark_date: datetime
    points: int = Field(ge=0, le=1000)
    s: int = Field(default=0, ge=0, le=1000)
    ms: int = Field(default=0, ge=0, le=1000)
    mu: int = Field(default=0, ge=0, le=1000)
    remarks: str | None = None

    @model_validator(mode="after")
    def validate_score_total(self):
        score_total = self.s + self.ms + self.mu
        if score_total > 1000:
            raise ValueError("S + MS + MU cannot exceed 1000")
        # Older API clients may submit points without the S/MS/MU breakdown.
        # Keep that payload compatible while validating the new breakdown.
        if any((self.s, self.ms, self.mu)) and self.points != score_total:
            raise ValueError("points must equal S + MS + MU when a breakdown is provided")
        return self

app = FastAPI(title="Quran Journey API", version="0.1.0")
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "https://safumk99-byte.github.io").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])

def current_month_bounds(reference: date | None = None) -> tuple[date, date]:
    """Return the inclusive date range for the current calendar month.
    Point records remain in storage; aggregate point boards use this range so totals
    automatically start fresh on the first day of each month without deleting history.
    """
    today = reference or datetime.now(ZoneInfo("Asia/Kolkata")).date()
    first = today.replace(day=1)
    if first.month == 12:
        next_month = first.replace(year=first.year + 1, month=1)
    else:
        next_month = first.replace(month=first.month + 1)
    return first, next_month - timedelta(days=1)


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
    student = db.get(Student, student_id)
    if student is None or not student.is_active:
        raise HTTPException(status_code=404, detail="Student not found")
    if user.role == "teacher":
        return
    if user.role != "parent" or student_id not in (allowed_student_ids(user, db) or set()):
        raise HTTPException(status_code=403, detail="You cannot access this student's records")

def notify_student_parents(db: Session, student_id: int, event_key: str, title: str, message: str, notification_type: str) -> None:
    """Create one in-app notification per linked parent; unique event keys prevent duplicates."""
    parent_ids = db.scalars(select(ParentStudent.parent_user_id).where(ParentStudent.student_id == student_id)).all()
    for parent_id in set(parent_ids):
        key = f"{event_key}:parent:{parent_id}"
        if db.scalar(select(ParentNotification.id).where(ParentNotification.event_key == key)):
            continue
        db.add(ParentNotification(parent_user_id=parent_id, student_id=student_id, event_key=key,
                                  title=title, message=message, notification_type=notification_type))


def reading_page_count(value: str | None) -> float:
    """Count non-negative whole and half-page values; ignore labels/ranges."""
    if value is None:
        return 0.0
    try:
        number = float(value.strip())
        if number < 0 or number == float("inf") or number != number:
            return 0.0
        doubled = number * 2
        if abs(doubled - round(doubled)) > 1e-9:
            return 0.0
        return round(number, 1)
    except (ValueError, TypeError):
        return 0.0

def adjust_completed_pages(db: Session, student_id: int, delta: float) -> None:
    if not delta:
        return
    student = db.get(Student, student_id)
    if student is None:
        return
    old_percent = round((float(student.completed_pages or 0) / max(int(student.total_pages or 1), 1)) * 100, 1)
    student.completed_pages = min(
        student.total_pages,
        max(0, student.completed_pages + delta),
    )
    new_percent = round((float(student.completed_pages or 0) / max(int(student.total_pages or 1), 1)) * 100, 1)
    if new_percent > old_percent:
        notify_student_parents(db, student.id, f"progress-percent:{new_percent}", "Quran progress updated",
                               f"{student.name}'s Quran progress has reached {new_percent}%.", "progress")

@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    # Add Juz columns in a SQLite- and PostgreSQL-compatible way.
    from sqlalchemy import inspect
    inspector = inspect(engine)
    if "challenge_ranges" in inspector.get_table_names():
        existing_columns = {column["name"] for column in inspector.get_columns("challenge_ranges")}
        with engine.begin() as conn:
            if "start_juz" not in existing_columns:
                conn.execute(sql_text('ALTER TABLE "challenge_ranges" ADD COLUMN "start_juz" INTEGER NULL'))
            if "end_juz" not in existing_columns:
                conn.execute(sql_text('ALTER TABLE "challenge_ranges" ADD COLUMN "end_juz" INTEGER NULL'))
    # Additive, non-destructive migration for databases created by earlier scaffold versions.
    if engine.dialect.name == "postgresql":
        additive = {
            "students": {
                "total_pages": "INTEGER NOT NULL DEFAULT 604",
                "completed_pages": "DOUBLE PRECISION NOT NULL DEFAULT 0",
                "current_juz": "INTEGER NOT NULL DEFAULT 1",
                "journey_start_date": "DATE NULL",
                "photo_data": "TEXT NULL",
                "cleanliness_points": "INTEGER NOT NULL DEFAULT 0",
                "discipline_points": "INTEGER NOT NULL DEFAULT 0",
                "worship_points": "INTEGER NOT NULL DEFAULT 0",
                "legacy_id": "VARCHAR(120) NULL",
            },
            "daily_marks": {
                "score_s": "INTEGER NOT NULL DEFAULT 0",
                "score_ms": "INTEGER NOT NULL DEFAULT 0",
                "score_mu": "INTEGER NOT NULL DEFAULT 0",
                "legacy_id": "VARCHAR(120) NULL",
            },
            "reading_entries": {"legacy_id": "VARCHAR(120) NULL", "start_surah": "INTEGER NULL", "start_ayah": "INTEGER NULL", "end_surah": "INTEGER NULL", "end_ayah": "INTEGER NULL", "recent_start_surah": "INTEGER NULL", "recent_start_ayah": "INTEGER NULL", "recent_end_surah": "INTEGER NULL", "recent_end_ayah": "INTEGER NULL", "general_start_surah": "INTEGER NULL", "general_start_ayah": "INTEGER NULL", "general_end_surah": "INTEGER NULL", "general_end_ayah": "INTEGER NULL", "recent_pages": "VARCHAR(20) NULL", "general_pages": "VARCHAR(20) NULL", "new_lesson": "TEXT NULL", "pages": "VARCHAR(200) NULL", "recent_revision": "TEXT NULL", "general_revision": "TEXT NULL", "remarks": "TEXT NULL"},
            "attendance": {"legacy_id": "VARCHAR(120) NULL", "period": "INTEGER NOT NULL DEFAULT 1"},
        }
        with engine.begin() as conn:
            for table, columns in additive.items():
                for column, definition in columns.items():
                    conn.execute(sql_text(f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{column}" {definition}'))
            # Convert legacy integer progress to a fractional type without losing existing values.
            conn.execute(sql_text('ALTER TABLE "students" ALTER COLUMN "completed_pages" TYPE DOUBLE PRECISION USING "completed_pages"::double precision'))
            conn.execute(sql_text('ALTER TABLE "students" ALTER COLUMN "completed_pages" SET DEFAULT 0'))
            for table in ("students", "daily_marks", "reading_entries", "attendance"):
                conn.execute(sql_text(f'CREATE UNIQUE INDEX IF NOT EXISTS "uq_{table}_legacy_id" ON "{table}" ("legacy_id") WHERE "legacy_id" IS NOT NULL'))
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
    return [{"id": s.id, "student_code": s.student_code, "name": s.name, "class_name": s.class_name, "total_pages": s.total_pages, "completed_pages": s.completed_pages, "current_juz": s.current_juz, "journey_start_date": s.journey_start_date.isoformat() if s.journey_start_date else None, "photo_data": s.photo_data, "cleanliness_points": s.cleanliness_points, "discipline_points": s.discipline_points, "worship_points": s.worship_points} for s in db.scalars(query.order_by(Student.name)).all()]

@app.post("/students", status_code=201)
def create_student(data: StudentInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    if db.scalar(select(Student).where(Student.student_code == data.student_code.strip())):
        raise HTTPException(status_code=409, detail="Student code already exists")
    student = Student(
        student_code=data.student_code.strip(), name=data.name.strip(), class_name=data.class_name,
        total_pages=data.total_pages, completed_pages=data.completed_pages, current_juz=data.current_juz,
        journey_start_date=data.journey_start_date, photo_data=data.photo_data,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return {"id": student.id, "student_code": student.student_code, "name": student.name, "class_name": student.class_name,
            "total_pages": student.total_pages, "completed_pages": student.completed_pages, "current_juz": student.current_juz,
            "journey_start_date": student.journey_start_date.isoformat() if student.journey_start_date else None,
            "photo_data": student.photo_data, "cleanliness_points": student.cleanliness_points, "discipline_points": student.discipline_points, "worship_points": student.worship_points}

@app.patch("/students/{student_id}")
def update_student(student_id: int, data: StudentUpdateInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    student = db.scalar(select(Student).where(Student.id == student_id, Student.is_active.is_(True)))
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    values = data.model_dump(exclude_unset=True)
    old_percent = round((float(student.completed_pages or 0) / max(int(student.total_pages or 1), 1)) * 100, 1)
    old_juz = int(student.current_juz or 1)
    if "student_code" in values and db.scalar(select(Student).where(Student.student_code == values["student_code"], Student.id != student_id)):
        raise HTTPException(status_code=409, detail="Student code already exists")
    total_pages = values.get("total_pages", student.total_pages)
    completed_pages = values.get("completed_pages", student.completed_pages)
    if completed_pages > total_pages:
        raise HTTPException(status_code=422, detail="Completed pages cannot exceed total pages")
    for key, value in values.items():
        setattr(student, key, value)
    new_percent = round((float(student.completed_pages or 0) / max(int(student.total_pages or 1), 1)) * 100, 1)
    if new_percent > old_percent:
        notify_student_parents(db, student.id, f"progress-percent:{new_percent}", "Quran progress updated",
                               f"{student.name}'s Quran progress has reached {new_percent}%.", "progress")
    if int(student.current_juz or 1) > old_juz:
        notify_student_parents(db, student.id, f"current-juz:{student.current_juz}", "New Juz reached",
                               f"{student.name} has reached Juz {student.current_juz}.", "juz")
    db.commit()
    db.refresh(student)
    return {"id": student.id, "student_code": student.student_code, "name": student.name, "class_name": student.class_name,
            "total_pages": student.total_pages, "completed_pages": student.completed_pages, "current_juz": student.current_juz,
            "journey_start_date": student.journey_start_date.isoformat() if student.journey_start_date else None,
            "photo_data": student.photo_data}


@app.delete("/students/{student_id}", status_code=204)
def delete_student(student_id: int, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    student = db.scalar(select(Student).where(Student.id == student_id, Student.is_active.is_(True)))
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    # Soft-delete so accidental removal does not cascade-delete reading, attendance, marks, or parent links.
    student.is_active = False
    db.commit()
    return Response(status_code=204)


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

@app.get("/parent/notifications")
def get_parent_notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "parent":
        raise HTTPException(status_code=403, detail="Parent access required")
    rows = db.scalars(select(ParentNotification).where(ParentNotification.parent_user_id == user.id)
                      .order_by(ParentNotification.created_at.desc()).limit(100)).all()
    return [{"id": r.id, "student_id": r.student_id, "title": r.title, "message": r.message,
             "type": r.notification_type, "created_at": r.created_at.isoformat(),
             "read": r.read_at is not None} for r in rows]


@app.post("/parent/notifications/{notification_id}/read")
def mark_parent_notification_read(notification_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "parent":
        raise HTTPException(status_code=403, detail="Parent access required")
    row = db.scalar(select(ParentNotification).where(ParentNotification.id == notification_id,
                                                      ParentNotification.parent_user_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    if row.read_at is None:
        row.read_at = datetime.now(timezone.utc)
        db.commit()
    return {"id": row.id, "read": True}


@app.post("/teacher/notifications", status_code=201)
def create_teacher_notification(data: TeacherNotificationInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Send a manually composed in-app notification to parents of one student or all active students."""
    if data.student_id is not None:
        student = db.get(Student, data.student_id)
        if student is None or not student.is_active:
            raise HTTPException(status_code=404, detail="Active student not found")
        students = [student]
    else:
        students = db.scalars(select(Student).where(Student.is_active.is_(True)).order_by(Student.name)).all()
    if not students:
        raise HTTPException(status_code=400, detail="No active students are available")

    event_id = uuid.uuid4().hex
    recipients = 0
    students_notified = 0
    for student in students:
        parent_ids = set(db.scalars(select(ParentStudent.parent_user_id).where(
            ParentStudent.student_id == student.id
        )).all())
        if not parent_ids:
            continue
        notify_student_parents(
            db, student.id, f"manual:{event_id}:{student.id}",
            data.title.strip(), data.message.strip(), "announcement"
        )
        recipients += len(parent_ids)
        students_notified += 1
    if recipients == 0:
        raise HTTPException(status_code=400, detail="No parents are linked to the selected student(s)")
    db.commit()
    return {"sent": True, "recipients": recipients, "students_notified": students_notified}


@app.post("/migration/localstorage")
def import_legacy_localstorage(data: LegacyMigrationInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Idempotently import a downloaded Quran Journey localStorage backup. Never deletes existing records."""
    imported = {"students_created": 0, "students_updated": 0, "reading_entries_created": 0, "attendance_created": 0, "daily_marks_created": 0, "skipped": 0}
    by_legacy = {}
    by_name = {}
    # Create/update students first. Legacy IDs make repeated uploads safe.
    for item in data.students:
        try:
            legacy_id = str(item.get("id", "")).strip()
            name = str(item.get("name", "")).strip()
            if not legacy_id or not name:
                imported["skipped"] += 1
                continue
            row = db.scalar(select(Student).where(Student.legacy_id == legacy_id))
            code = "QJ-LEGACY-" + legacy_id[:60]
            if row is None:
                row = db.scalar(select(Student).where(Student.student_code == code))
            values = {
                "student_code": code, "name": name[:160],
                "class_name": str(item.get("className") or "Unassigned class")[:100],
                "total_pages": max(1, min(2000, int(item.get("totalPages") or 604))),
                "completed_pages": max(0.0, min(max(1, min(2000, int(item.get("totalPages") or 604))), float(item.get("completedPages") or 0))),
                "current_juz": max(1, min(30, int(item.get("currentJuz") or 1))),
                "journey_start_date": datetime.fromisoformat(str(item.get("journeyStartDate") or item.get("createdAt") or datetime.now(timezone.utc).date()).replace("Z","+00:00")).date(),
                "photo_data": data.photos.get(name) if name in data.photos else (row.photo_data if row is not None else None),
            }
            if row is None:
                row = Student(**values, legacy_id=legacy_id)
                db.add(row); db.flush()
                imported["students_created"] += 1
            else:
                for key, value in values.items():
                    setattr(row, key, value)
                imported["students_updated"] += 1
            by_legacy[legacy_id] = row
            by_name[name.strip().lower()] = row
        except (ValueError, TypeError):
            imported["skipped"] += 1
    db.flush()
    # Legacy reading entries reference local student IDs. Persist original values and stable IDs.
    for item in data.reading_entries:
        try:
            sid = str(item.get("studentId", "")).strip()
            student = by_legacy.get(sid) or db.scalar(select(Student).where(Student.legacy_id == sid))
            if not student:
                imported["skipped"] += 1; continue
            legacy_id = "reading:" + str(item.get("id") or f"{sid}:{item.get('date')}:{item.get('newLesson','')}")
            if db.scalar(select(ReadingEntry).where(ReadingEntry.legacy_id == legacy_id)):
                continue
            entry_date = datetime.fromisoformat(str(item.get("date"))).date()
            row = ReadingEntry(student_id=student.id, entry_date=entry_date, new_lesson=item.get("newLesson"), pages=str(item.get("pages") or 0), recent_revision=item.get("recentRevision"), general_revision=item.get("generalRevision"), remarks=item.get("remarks"), legacy_id=legacy_id)
            db.add(row); imported["reading_entries_created"] += 1
            if item.get("attendance") in {"Present","Absent","Leave","present","absent","leave"}:
                status_value = str(item.get("attendance")).lower()
                aid = f"attendance:{sid}:{item.get('date')}:{item.get('id','')}"
                if not db.scalar(select(Attendance).where(Attendance.legacy_id == aid)):
                    db.add(Attendance(student_id=student.id, attendance_date=entry_date, status=status_value.lower(), remarks=item.get("remarks"), legacy_id=aid))
                    imported["attendance_created"] += 1
        except (ValueError, TypeError):
            imported["skipped"] += 1
    # Recompute progress from valid entries in the complete backup. Do not add to
    # the existing DB value, so repeated imports remain idempotent.
    base_pages = data.reading_base_pages or {}
    pages_by_student = {}
    for item in data.reading_entries:
        sid = str(item.get("studentId", "")).strip()
        if sid not in by_legacy:
            continue
        try:
            # An entry with an invalid date is skipped by the import loop and must
            # not contribute to the completed-page total either.
            datetime.fromisoformat(str(item.get("date"))).date()
            pages = reading_page_count(str(item.get("pages") or 0))
        except (ValueError, TypeError):
            continue
        pages_by_student[sid] = pages_by_student.get(sid, 0.0) + pages
    for legacy_id, student in by_legacy.items():
        if legacy_id not in base_pages:
            continue
        try:
            base = max(0.0, float(base_pages.get(legacy_id) or 0))
        except (ValueError, TypeError):
            imported["skipped"] += 1
            continue
        student.completed_pages = min(student.total_pages, base + pages_by_student.get(legacy_id, 0))

    # Marks are name/date based in the legacy UI; preserve S/MS/MU and total.
    for item in data.daily_marks:
        try:
            name = str(item.get("name") or "").strip().lower()
            student = by_name.get(name)
            if not student:
                student = db.scalar(select(Student).where(Student.name.ilike(name))) if name else None
            if not student:
                imported["skipped"] += 1; continue
            legacy_id = "mark:" + str(item.get("id") or f"{name}:{item.get('date')}:{item.get('total',0)}")
            if db.scalar(select(DailyMark).where(DailyMark.legacy_id == legacy_id)):
                continue
            mark_date = datetime.fromisoformat(str(item.get("date"))).date()
            s, ms, mu = int(item.get("s") or 0), int(item.get("ms") or 0), int(item.get("mu") or 0)
            points = int(item.get("total") or s + ms + mu)
            # Reject malformed negative marks rather than importing corrupt scores.
            if min(s, ms, mu, points) < 0 or max(s, ms, mu, points) > 1000:
                imported["skipped"] += 1
                continue
            db.add(DailyMark(student_id=student.id, mark_date=mark_date, points=points, score_s=s, score_ms=ms, score_mu=mu, legacy_id=legacy_id))
            imported["daily_marks_created"] += 1
        except (ValueError, TypeError):
            imported["skipped"] += 1
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"status": "ok", "imported": imported, "message": "Import is additive; existing records were not deleted."}


@app.get("/discipline/summary")
def discipline_summary(user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    month_start, month_end = current_month_bounds()
    students = db.scalars(select(Student).where(Student.is_active.is_(True)).order_by(Student.name)).all()
    rows = db.scalars(select(DisciplineEntry).where(
        DisciplineEntry.is_reversed.is_(False),
        DisciplineEntry.incident_date >= month_start,
        DisciplineEntry.incident_date <= month_end,
    )).all()
    totals: dict[int, int] = {}
    for row in rows:
        totals[row.student_id] = totals.get(row.student_id, 0) + row.points_deducted
    earned: dict[int, float] = {}
    reading_rows = db.scalars(select(ReadingEntry).join(Student, ReadingEntry.student_id == Student.id).where(
        Student.is_active.is_(True),
        ReadingEntry.entry_date >= month_start,
        ReadingEntry.entry_date <= month_end,
    )).all()
    for entry in reading_rows:
        earned[entry.student_id] = earned.get(entry.student_id, 0.0) + reading_page_count(entry.pages) * 10 + reading_page_count(entry.recent_pages) + reading_page_count(entry.general_pages)
    return [{"student_id": s.id, "name": s.name, "class_name": s.class_name,
        "month": month_start.strftime("%Y-%m"),
        "academic_points": round(earned.get(s.id, 0), 1),
        "discipline_points_deducted": totals.get(s.id, 0),
        "final_points": round(earned.get(s.id, 0) - totals.get(s.id, 0), 1)} for s in students]

@app.get("/discipline/{student_id}")
def discipline_history(student_id: int, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    check_student_access(student_id, user, db)
    rows = db.scalars(select(DisciplineEntry).where(DisciplineEntry.student_id == student_id).order_by(DisciplineEntry.incident_date.desc(), DisciplineEntry.id.desc())).all()
    return [{"id": r.id, "student_id": r.student_id, "reason": r.reason, "points_deducted": r.points_deducted, "incident_date": r.incident_date.isoformat(), "notes": r.notes, "created_by": r.created_by, "created_at": r.created_at.isoformat(), "is_reversed": r.is_reversed, "reversal_reason": r.reversal_reason, "reversed_at": r.reversed_at.isoformat() if r.reversed_at else None} for r in rows]

@app.post("/discipline", status_code=201)
def add_discipline_entry(data: DisciplineInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    fixed_deductions = {"Disrespectful speech": 2, "Rude behavior to teacher": 5, "Repeated disobedience": 5, "Serious discipline violation": 10}
    required_points = next((points for reason, points in fixed_deductions.items() if reason.casefold() == data.reason.strip().casefold()), None)
    if required_points is not None and data.points_deducted != required_points:
        raise HTTPException(status_code=422, detail=f"This reason requires a deduction of {required_points} points")
    student = db.scalar(select(Student).where(Student.id == data.student_id, Student.is_active.is_(True)))
    if student is None:
        raise HTTPException(status_code=404, detail="Active student not found")
    row = DisciplineEntry(student_id=student.id, reason=data.reason, points_deducted=data.points_deducted, incident_date=data.incident_date, notes=data.notes, created_by=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "student_id": row.student_id, "reason": row.reason, "points_deducted": row.points_deducted, "incident_date": row.incident_date.isoformat(), "is_reversed": row.is_reversed}

@app.post("/discipline/{entry_id}/reverse")
def reverse_discipline_entry(entry_id: int, data: DisciplineReverseInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    row = db.get(DisciplineEntry, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Discipline record not found")
    if row.is_reversed:
        raise HTTPException(status_code=409, detail="This record has already been corrected")
    row.is_reversed = True
    row.reversed_by = user.id
    row.reversed_at = datetime.now(timezone.utc)
    row.reversal_reason = data.reason
    db.commit()
    return {"id": row.id, "is_reversed": True, "reversal_reason": row.reversal_reason}

@app.get("/points/leaderboard")
def points_leaderboard(user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Rank reading activity points for the current calendar month; keep older entries as history."""
    month_start, month_end = current_month_bounds()
    active_students = db.scalars(select(Student).where(Student.is_active.is_(True))).all()
    totals = {student.id: {"new_lesson_points": 0.0, "recent_revision_points": 0.0, "general_revision_points": 0.0} for student in active_students}
    rows = db.scalars(select(ReadingEntry).join(Student, ReadingEntry.student_id == Student.id).where(
        Student.is_active.is_(True),
        ReadingEntry.entry_date >= month_start,
        ReadingEntry.entry_date <= month_end,
    )).all()
    def page_value(value):
        try:
            number = float(value or 0)
            return number if number >= 0 else 0.0
        except (TypeError, ValueError):
            return 0.0
    for entry in rows:
        bucket = totals.get(entry.student_id)
        if bucket is None:
            continue
        bucket["new_lesson_points"] += page_value(entry.pages) * 10
        bucket["recent_revision_points"] += page_value(entry.recent_pages)
        bucket["general_revision_points"] += page_value(entry.general_pages)
    students_by_id = {student.id: student for student in active_students}
    result = []
    for student_id, values in totals.items():
        student = students_by_id[student_id]
        total = values["new_lesson_points"] + values["recent_revision_points"] + values["general_revision_points"]
        result.append({"student_id": student.id, "name": student.name, "class_name": student.class_name,
            "month": month_start.strftime("%Y-%m"),
            "new_lesson_points": values["new_lesson_points"], "recent_revision_points": values["recent_revision_points"],
            "general_revision_points": values["general_revision_points"], "total_points": total})
    result.sort(key=lambda item: (-item["total_points"], item["name"].casefold()))
    for rank, item in enumerate(result, start=1):
        item["rank"] = rank
    return result

@app.get("/students/{student_id}/reading")
def get_reading(student_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    check_student_access(student_id, user, db)
    rows = db.scalars(select(ReadingEntry).where(ReadingEntry.student_id == student_id).order_by(ReadingEntry.entry_date.desc(), ReadingEntry.id.desc())).all()
    return [{"id": r.id, "date": r.entry_date.isoformat(), "start_surah": r.start_surah, "start_ayah": r.start_ayah, "end_surah": r.end_surah, "end_ayah": r.end_ayah, "recent_start_surah": r.recent_start_surah, "recent_start_ayah": r.recent_start_ayah, "recent_end_surah": r.recent_end_surah, "recent_end_ayah": r.recent_end_ayah, "general_start_surah": r.general_start_surah, "general_start_ayah": r.general_start_ayah, "general_end_surah": r.general_end_surah, "general_end_ayah": r.general_end_ayah, "new_lesson": r.new_lesson, "pages": r.pages, "recent_revision": r.recent_revision, "recent_pages": r.recent_pages or "0", "general_revision": r.general_revision, "general_pages": r.general_pages or "0", "remarks": r.remarks} for r in rows]

@app.patch("/students/{student_id}/reading/{entry_id}")
def update_reading(student_id: int, entry_id: int, data: ReadingUpdateInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    check_student_access(student_id, user, db)
    row = db.scalar(select(ReadingEntry).where(ReadingEntry.id == entry_id, ReadingEntry.student_id == student_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Reading entry not found")
    old_pages = reading_page_count(row.pages)
    values = data.model_dump(exclude_unset=True)
    combined = {"start_surah": row.start_surah, "start_ayah": row.start_ayah, "end_surah": row.end_surah, "end_ayah": row.end_ayah}
    combined.update(values)
    for prefix in ("", "recent_", "general_"):
        keys = (f"{prefix}start_surah", f"{prefix}start_ayah", f"{prefix}end_surah", f"{prefix}end_ayah")
        range_values = {key: getattr(row, key) for key in keys}
        range_values.update({key: values[key] for key in keys if key in values})
        supplied = tuple(range_values[key] for key in keys)
        if any(value is not None for value in supplied):
            if any(value is None for value in supplied):
                raise HTTPException(status_code=422, detail=f"All four Surah/Ayah fields must be provided together for {prefix or 'new lesson'}")
            try:
                validate_quran_range(*supplied)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
    for key, value in values.items():
        if key == "entry_date":
            if value is None:
                raise HTTPException(status_code=422, detail="Entry date cannot be null")
            value = value.date()
        setattr(row, key, value)
    if "pages" in values:
        adjust_completed_pages(db, student_id, reading_page_count(row.pages) - old_pages)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "student_id": row.student_id, "date": row.entry_date.isoformat()}

@app.delete("/students/{student_id}/reading/{entry_id}", status_code=204)
def delete_reading(student_id: int, entry_id: int, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    check_student_access(student_id, user, db)
    row = db.scalar(select(ReadingEntry).where(ReadingEntry.id == entry_id, ReadingEntry.student_id == student_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Reading entry not found")
    adjust_completed_pages(db, student_id, -reading_page_count(row.pages))
    db.delete(row)
    db.commit()
    return Response(status_code=204)

@app.post("/students/{student_id}/reading", status_code=201)
def add_reading(student_id: int, data: ReadingInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    check_student_access(student_id, user, db)
    if not db.get(Student, student_id):
        raise HTTPException(status_code=404, detail="Student not found")
    for prefix in ("", "recent_", "general_"):
        keys = (f"{prefix}start_surah", f"{prefix}start_ayah", f"{prefix}end_surah", f"{prefix}end_ayah")
        supplied = tuple(getattr(data, key) for key in keys)
        if any(value is not None for value in supplied):
            if any(value is None for value in supplied):
                raise HTTPException(status_code=422, detail=f"All four Surah/Ayah fields must be provided together for {prefix or 'new lesson'}")
            try:
                validate_quran_range(*supplied)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = ReadingEntry(student_id=student_id, entry_date=data.entry_date.date(), start_surah=data.start_surah, start_ayah=data.start_ayah, end_surah=data.end_surah, end_ayah=data.end_ayah, recent_start_surah=data.recent_start_surah, recent_start_ayah=data.recent_start_ayah, recent_end_surah=data.recent_end_surah, recent_end_ayah=data.recent_end_ayah, general_start_surah=data.general_start_surah, general_start_ayah=data.general_start_ayah, general_end_surah=data.general_end_surah, general_end_ayah=data.general_end_ayah, new_lesson=data.new_lesson, pages=data.pages, recent_revision=data.recent_revision, recent_pages=data.recent_pages, general_revision=data.general_revision, general_pages=data.general_pages, remarks=data.remarks)
    adjust_completed_pages(db, student_id, reading_page_count(data.pages))
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "student_id": row.student_id, "date": row.entry_date.isoformat()}

@app.get("/students/{student_id}/attendance")
def get_attendance(student_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    check_student_access(student_id, user, db)
    rows = db.scalars(select(Attendance).where(Attendance.student_id == student_id).order_by(Attendance.attendance_date.desc(), Attendance.period)).all()
    return [{"id": r.id, "date": r.attendance_date.isoformat(), "status": r.status, "period": r.period, "remarks": r.remarks} for r in rows]

@app.post("/students/{student_id}/attendance", status_code=201)
def add_attendance(student_id: int, data: AttendanceInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    check_student_access(student_id, user, db)
    if data.status not in {"present", "late", "absent", "leave"}:
        raise HTTPException(status_code=422, detail="Status must be present, late, absent, or leave")
    if not db.get(Student, student_id):
        raise HTTPException(status_code=404, detail="Student not found")
    day = data.attendance_date.date()
    row = db.scalar(select(Attendance).where(Attendance.student_id == student_id, Attendance.attendance_date == day, Attendance.period == data.period).order_by(Attendance.id.desc()))
    previous_status = row.status if row else None
    if row:
        row.status = data.status
        row.remarks = data.remarks
    else:
        row = Attendance(student_id=student_id, attendance_date=day, period=data.period, status=data.status, remarks=data.remarks)
        db.add(row)
    if data.status in {"absent", "leave"} and previous_status != data.status:
        student = db.get(Student, student_id)
        status_label = "Absent" if data.status == "absent" else "Leave"
        notify_student_parents(db, student_id, f"attendance:{day.isoformat()}:period:{data.period}:status:{data.status}",
                               f"Attendance: {status_label}", f"{student.name} was marked {status_label.lower()} on {day.isoformat()} (period {data.period}).",
                               "attendance")
    db.commit()
    db.refresh(row)
    return {"id": row.id, "student_id": row.student_id, "date": row.attendance_date.isoformat(), "period": row.period, "status": row.status}

@app.get("/students/{student_id}/marks")
def get_marks(student_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    check_student_access(student_id, user, db)
    rows = db.scalars(select(DailyMark).where(DailyMark.student_id == student_id).order_by(DailyMark.mark_date.desc())).all()
    return [{"id": r.id, "date": r.mark_date.isoformat(), "points": r.points, "s": r.score_s, "ms": r.score_ms, "mu": r.score_mu, "remarks": r.remarks} for r in rows]

@app.post("/students/{student_id}/marks", status_code=201)
def add_mark(student_id: int, data: MarkInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    check_student_access(student_id, user, db)
    if not db.get(Student, student_id):
        raise HTTPException(status_code=404, detail="Student not found")
    row = DailyMark(student_id=student_id, mark_date=data.mark_date.date(), points=data.points, score_s=data.s, score_ms=data.ms, score_mu=data.mu, remarks=data.remarks)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "student_id": row.student_id, "date": row.mark_date.isoformat(), "points": row.points, "s": row.score_s, "ms": row.score_ms, "mu": row.score_mu, "remarks": row.remarks}

@app.delete("/students/{student_id}/marks/{mark_id}", status_code=204)
def delete_mark(student_id: int, mark_id: int, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    check_student_access(student_id, user, db)
    row = db.scalar(select(DailyMark).where(DailyMark.id == mark_id, DailyMark.student_id == student_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Daily mark not found")
    db.delete(row)
    db.commit()
    return Response(status_code=204)


# Challenge Zone: durable, authenticated storage shared across devices.
def _challenge_student(student_id: int, user: User, db: Session) -> Student:
    check_student_access(student_id, user, db)
    student = db.get(Student, student_id)
    if student is None or not student.is_active:
        raise HTTPException(status_code=404, detail="Active student not found")
    return student

def _challenge_session_json(row: ChallengeSession):
    return {"id": row.id, "date": row.challenge_date.isoformat(), "confirmed": row.confirmed,
        "score": row.score, "q": [{"text": q.question_text, "expected": q.expected_answer or "",
        "submitted": q.submitted, "review": q.review_score, "note": q.teacher_note or "",
        "has_audio": bool(q.audio_data), "audio_type": q.audio_type, "audio_base64": q.audio_data} for q in row.questions]}

@app.get("/challenge/leaderboard")
def challenge_leaderboard(user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Show only current-month confirmed challenge marks; preserve all older sessions as history."""
    month_start, month_end = current_month_bounds()
    rows = db.execute(
        select(Student, ChallengeSession)
        .join(ChallengeSession, ChallengeSession.student_id == Student.id)
        .where(
            ChallengeSession.confirmed.is_(True),
            Student.is_active.is_(True),
            ChallengeSession.challenge_date >= month_start,
            ChallengeSession.challenge_date <= month_end,
        )
        .order_by(ChallengeSession.challenge_date.desc())
    ).all()
    totals = {}
    for student, session in rows:
        entry = totals.setdefault(student.id, {
            "student_id": student.id, "name": student.name,
            "class_name": student.class_name or "Unassigned class",
            "month": month_start.strftime("%Y-%m"),
            "total_marks": 0, "challenges_completed": 0,
        })
        entry["total_marks"] += int(session.score or 0)
        entry["challenges_completed"] += 1
    ranked = sorted(totals.values(), key=lambda item: (-item["total_marks"], item["name"].casefold()))
    for rank, entry in enumerate(ranked, start=1):
        entry["rank"] = rank
    return ranked

@app.get("/students/{student_id}/challenge/ranges")
def list_challenge_ranges(student_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _challenge_student(student_id, user, db)
    rows = db.scalars(select(ChallengeRange).where(ChallengeRange.student_id == student_id).order_by(ChallengeRange.id)).all()
    return [{"id": r.id, "start_juz": r.start_juz, "end_juz": r.end_juz, "status": r.status, "note": r.note or ""} for r in rows]

@app.post("/students/{student_id}/challenge/ranges", status_code=201)
def add_challenge_range(student_id: int, data: ChallengeRangeInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    _challenge_student(student_id, user, db)
    row = ChallengeRange(student_id=student_id, surah=1, start_ayah=1, end_ayah=1, start_juz=data.start_juz, end_juz=data.end_juz, status=data.status, note=data.note)
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "surah": row.surah, "start": row.start_ayah, "end": row.end_ayah, "status": row.status, "note": row.note or ""}

@app.patch("/students/{student_id}/challenge/ranges/{range_id}")
def edit_challenge_range(student_id: int, range_id: int, data: ChallengeRangeInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    _challenge_student(student_id, user, db)
    row = db.scalar(select(ChallengeRange).where(ChallengeRange.id == range_id, ChallengeRange.student_id == student_id))
    if row is None: raise HTTPException(status_code=404, detail="Learning range not found")
    for k, v in {"start_juz":data.start_juz,"end_juz":data.end_juz,"status":data.status,"note":data.note}.items(): setattr(row,k,v)
    db.commit()
    return {"id": row.id, "start_juz": row.start_juz, "end_juz": row.end_juz, "status": row.status, "note": row.note or ""}

@app.delete("/students/{student_id}/challenge/ranges/{range_id}", status_code=204)
def delete_challenge_range(student_id: int, range_id: int, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    _challenge_student(student_id, user, db)
    row = db.scalar(select(ChallengeRange).where(ChallengeRange.id == range_id, ChallengeRange.student_id == student_id))
    if row is None: raise HTTPException(status_code=404, detail="Learning range not found")
    db.delete(row); db.commit()
    return Response(status_code=204)

def _exam_json(row: ExamSession):
    return {
        "id": row.id, "date": row.exam_date.isoformat(), "confirmed": row.confirmed,
        "total_marks": row.total_marks,
        "questions": [{
            "text": q.question_text, "expected": q.expected_answer or "",
            "max_marks": q.max_marks, "awarded_marks": q.awarded_marks,
            "note": q.teacher_note or ""
        } for q in row.questions]
    }

@app.get("/students/{student_id}/exam/ranges")
def exam_learning_ranges(student_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _challenge_student(student_id, user, db)
    rows = db.scalars(select(ChallengeRange).where(ChallengeRange.student_id == student_id).order_by(ChallengeRange.id)).all()
    return [{"id": r.id, "start_juz": r.start_juz, "end_juz": r.end_juz, "status": r.status, "note": r.note or ""} for r in rows]

@app.get("/students/{student_id}/exam/sessions")
def exam_sessions(student_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _challenge_student(student_id, user, db)
    rows = db.scalars(select(ExamSession).where(ExamSession.student_id == student_id).order_by(ExamSession.exam_date.desc(), ExamSession.id.desc())).all()
    return [_exam_json(row) for row in rows]

@app.post("/students/{student_id}/exam/generate")
def generate_exam(student_id: int, data: ExamGenerateInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    _challenge_student(student_id, user, db)
    row = db.scalar(select(ExamSession).where(ExamSession.student_id == student_id, ExamSession.exam_date == data.date).order_by(ExamSession.id.desc()))
    if row and row.confirmed:
        raise HTTPException(status_code=409, detail="This exam is confirmed. Create a new exam date to generate another.")
    ranges = db.scalars(select(ChallengeRange).where(ChallengeRange.student_id == student_id)).all()
    juz_numbers = sorted({j for r in ranges if r.start_juz and r.end_juz and r.status in ("Learning", "Completed") for j in range(r.start_juz, r.end_juz + 1)})
    if not juz_numbers:
        raise HTTPException(status_code=400, detail="Save the student's learning range in the Challenge section first.")
    refs_by_key = {}
    for juz_no in juz_numbers:
        for ref in _juz_ayah_refs(juz_no):
            refs_by_key[(ref["surah"], ref["ayah"])] = (ref, juz_no)
    refs = list(refs_by_key.values())
    if len(refs) < data.question_count:
        raise HTTPException(status_code=400, detail=f"Only {len(refs)} ayahs are available in the saved learning range.")
    chosen = random.SystemRandom().sample(refs, data.question_count)
    if row:
        row.questions.clear()
        db.flush()
        row.confirmed = False
        row.total_marks = 0
    else:
        row = ExamSession(student_id=student_id, exam_date=data.date, confirmed=False, total_marks=0)
        db.add(row)
        db.flush()
    for idx, (ref, juz_no) in enumerate(chosen, start=1):
        row.questions.append(ExamQuestion(
            question_no=idx, question_text=ref["text"],
            expected_answer=f"Surah {ref['surah']}: {ref['surah_name']} {ref['ayah']} (Juz {juz_no})",
            max_marks=5
        ))
    db.commit()
    db.refresh(row)
    return _exam_json(row)

@app.put("/students/{student_id}/exam/sessions/{exam_date}")
def save_exam(student_id: int, exam_date: date, data: ExamSaveInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    _challenge_student(student_id, user, db)
    if data.date != exam_date:
        raise HTTPException(status_code=422, detail="Exam date does not match URL")
    row = db.scalar(select(ExamSession).where(ExamSession.student_id == student_id, ExamSession.exam_date == exam_date).order_by(ExamSession.id.desc()))
    if row is None:
        row = ExamSession(student_id=student_id, exam_date=exam_date)
        db.add(row)
        db.flush()
    if row.confirmed:
        raise HTTPException(status_code=409, detail="Confirmed exam marks cannot be edited.")
    row.questions.clear()
    db.flush()
    total = 0
    for idx, q in enumerate(data.questions, start=1):
        awarded = q.awarded_marks
        if data.confirmed and awarded is None:
            raise HTTPException(status_code=422, detail=f"Enter marks for question {idx} before confirming.")
        total += int(awarded or 0)
        row.questions.append(ExamQuestion(
            question_no=idx, question_text=q.text.strip(), expected_answer=q.expected,
            max_marks=q.max_marks, awarded_marks=awarded, teacher_note=q.note
        ))
    row.confirmed = data.confirmed
    row.total_marks = total if data.confirmed else 0
    db.commit()
    db.refresh(row)
    return _exam_json(row)

_JUZ_AYAH_CACHE: dict[int, list[dict]] = {}

def _juz_ayah_refs(juz_no: int) -> list[dict]:
    """Fetch verified Arabic ayah text and references for a Juz from AlQuran Cloud."""
    if juz_no not in _JUZ_AYAH_CACHE:
        try:
            with urlopen(f"https://api.alquran.cloud/v1/juz/{juz_no}/quran-uthmani", timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("code") != 200 or not isinstance(payload.get("data", {}).get("ayahs"), list):
                raise ValueError("Unexpected Quran API response")
            _JUZ_AYAH_CACHE[juz_no] = [
                {"surah": int(a["surah"]["number"]), "surah_name": str(a["surah"]["englishName"]),
                 "ayah": int(a["numberInSurah"]), "text": str(a["text"]).strip()}
                for a in payload["data"]["ayahs"]
                if a.get("surah", {}).get("number") and a.get("numberInSurah") and a.get("text")
            ]
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=502, detail=f"Could not load verified Quran data for Juz {juz_no}. Please retry.") from exc
    return _JUZ_AYAH_CACHE[juz_no]

@app.post("/students/{student_id}/challenge/generate/{challenge_date}")
def generate_daily_challenge(student_id: int, challenge_date: date, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Generate and persist five recitation prompts restricted to the student's saved Juz ranges."""
    _challenge_student(student_id, user, db)
    existing = db.scalar(select(ChallengeSession).where(
        ChallengeSession.student_id == student_id,
        ChallengeSession.challenge_date == challenge_date,
    ))
    if existing and existing.confirmed:
        raise HTTPException(status_code=409, detail="Today's challenge score is confirmed and cannot be regenerated.")
    ranges = db.scalars(select(ChallengeRange).where(ChallengeRange.student_id == student_id)).all()
    juz_numbers = sorted({j for r in ranges if r.start_juz and r.end_juz for j in range(r.start_juz, r.end_juz + 1)})
    if not juz_numbers:
        raise HTTPException(status_code=400, detail="Save a Student Learning Range first.")
    refs_by_key = {}
    for juz_no in juz_numbers:
        for ref in _juz_ayah_refs(juz_no):
            refs_by_key[(ref["surah"], ref["ayah"])] = ref
    refs = list(refs_by_key.values())
    if len(refs) < 5:
        raise HTTPException(status_code=400, detail="The saved learning range does not contain enough ayah references.")
    chosen = random.SystemRandom().sample(refs, 5)
    if existing:
        existing.questions.clear()
        db.flush()
        row = existing
        row.confirmed = False
        row.score = 0
    else:
        row = ChallengeSession(student_id=student_id, challenge_date=challenge_date, confirmed=False, score=0)
        db.add(row)
        db.flush()
    for idx, ref in enumerate(chosen, start=1):
        # Show the actual Quran ayah in Arabic, not an instruction phrased as a question.
        ayah_text = ref.get("text", "").strip()
        if not ayah_text:
            raise HTTPException(status_code=502, detail=f"Verified Arabic text is missing for Surah {ref['surah']} Ayah {ref['ayah']}.")
        expected = f"Surah {ref['surah']}: {ref['surah_name']} {ref['ayah']} (Juz {next((j for j in juz_numbers if any((a['surah'], a['ayah']) == (ref['surah'], ref['ayah']) for a in _JUZ_AYAH_CACHE.get(j, []))), juz_numbers[0])})"
        row.questions.append(ChallengeQuestion(question_no=idx, question_text=ayah_text, expected_answer=expected))
    db.commit()
    db.refresh(row)
    return _challenge_session_json(row)

@app.get("/students/{student_id}/challenge/sessions")
def list_challenge_sessions(student_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _challenge_student(student_id, user, db)
    rows = db.scalars(select(ChallengeSession).where(ChallengeSession.student_id == student_id).order_by(ChallengeSession.challenge_date.desc())).all()
    return [_challenge_session_json(row) for row in rows]

@app.put("/students/{student_id}/challenge/sessions/{challenge_date}")
def save_challenge_session(student_id: int, challenge_date: date, data: ChallengeSessionInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    _challenge_student(student_id, user, db)
    if data.date != challenge_date: raise HTTPException(status_code=422, detail="Session date does not match URL")
    row = db.scalar(select(ChallengeSession).where(ChallengeSession.student_id == student_id, ChallengeSession.challenge_date == challenge_date))
    if row is None:
        row = ChallengeSession(student_id=student_id, challenge_date=challenge_date)
        db.add(row); db.flush()
    if row.confirmed and data.confirmed is False:
        # A confirmed score is immutable through ordinary save; teacher must re-review explicitly.
        raise HTTPException(status_code=409, detail="Confirmed challenge cannot be changed. Create a new challenge date.")
    row.confirmed = data.confirmed
    row.score = sum(q.review or 0 for q in data.questions) if data.confirmed else 0
    row.questions.clear()
    db.flush()
    for idx, q in enumerate(data.questions, start=1):
        row.questions.append(ChallengeQuestion(question_no=idx, question_text=q.text.strip(), expected_answer=q.expected,
            submitted=q.submitted, review_score=q.review, teacher_note=q.note, audio_data=q.audio_base64, audio_type=q.audio_type))
    db.commit(); db.refresh(row)
    return _challenge_session_json(row)

@app.put("/students/{student_id}/challenge/sessions/{challenge_date}/audio/{question_no}")
def save_challenge_audio(student_id: int, challenge_date: date, question_no: int, data: ChallengeAudioInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    _challenge_student(student_id, user, db)
    if question_no < 1 or question_no > 5:
        raise HTTPException(status_code=422, detail="Question number must be between 1 and 5.")
    row = db.scalar(select(ChallengeSession).where(
        ChallengeSession.student_id == student_id,
        ChallengeSession.challenge_date == challenge_date,
    ))
    if row is None:
        raise HTTPException(status_code=404, detail="Daily challenge was not found. Generate it before recording an answer.")
    question = db.scalar(select(ChallengeQuestion).where(
        ChallengeQuestion.session_id == row.id,
        ChallengeQuestion.question_no == question_no,
    ))
    if question is None:
        raise HTTPException(status_code=404, detail="Challenge question was not found. Save the five questions before recording.")
    question.audio_data = data.audio_base64
    question.audio_type = data.audio_type
    question.submitted = True
    db.commit()
    return {"saved": True, "question_no": question_no}

