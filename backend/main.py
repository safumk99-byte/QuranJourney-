"""Quran Journey API: Teacher and Parent login only. Student accounts are not login users."""
from __future__ import annotations

import os
import json
import random
import base64
import binascii
import io
import re
import sqlite3
import tempfile
import zipfile
from functools import lru_cache
import secrets
import hashlib

import cloudinary
import cloudinary.uploader
import uuid
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen
from datetime import date, datetime, timedelta, timezone
from typing import Generator
from zoneinfo import ZoneInfo

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator, model_validator
from pwdlib import PasswordHash
from sqlalchemy import UniqueConstraint, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, select, func, text as sql_text
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
TOKEN_MINUTES = max(5, int(os.getenv("ACCESS_TOKEN_MINUTES", "20")))
REFRESH_DAYS = max(1, int(os.getenv("REFRESH_TOKEN_DAYS", "30")))

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    login_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), index=True)  # teacher or parent
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    auth_token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    next_juz_pages: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    juz_progress_base_juz: Mapped[int | None] = mapped_column(Integer, nullable=True)
    juz_progress_base_pages: Mapped[float | None] = mapped_column(Float, nullable=True)
    journey_start_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    photo_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_public_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cleanliness_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discipline_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    worship_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    legacy_id: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    parent_links: Mapped[list["ParentStudent"]] = relationship(back_populates="student", cascade="all, delete-orphan")

class MonthlyCharacterPoints(Base):
    __tablename__ = "monthly_character_points"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    cleanliness_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discipline_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    worship_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    __table_args__ = (UniqueConstraint("student_id", "year", "month", name="uq_monthly_character_student_month"),)

class ParentStudent(Base):
    __tablename__ = "parent_students"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    student: Mapped[Student] = relationship(back_populates="parent_links")

class CalendarHoliday(Base):
    __tablename__ = "calendar_holidays"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    holiday_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    class_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class CalendarHolidayInput(BaseModel):
    holiday_date: date
    reason: str | None = Field(default=None, max_length=240)
    class_name: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=80)

    @field_validator("reason")
    @classmethod
    def clean_holiday_reason(cls, value):
        return value.strip() or None if value is not None else None


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
    juz_progress_data: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    exam_type: Mapped[str] = mapped_column(String(20), default="monthly", nullable=False)
    start_juz: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_juz: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_source: Mapped[str] = mapped_column(String(20), default="new_lesson", nullable=False)
    start_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    exam_type: str = Field(default="monthly", pattern="^(monthly|juz|semester)$")
    year: int | None = Field(default=None, ge=2000, le=2100)
    month: int | None = Field(default=None, ge=1, le=12)
    juz_no: int | None = Field(default=None, ge=1, le=30)
    start_juz: int | None = Field(default=None, ge=1, le=30)
    end_juz: int | None = Field(default=None, ge=1, le=30)
    question_count: int = Field(ge=1, le=100)
    monthly_source: str = Field(default="new_lesson", pattern="^(new_lesson|page_range|both)$")
    start_page: int | None = Field(default=None, ge=1, le=604)
    end_page: int | None = Field(default=None, ge=1, le=604)

    @model_validator(mode="after")
    def validate_exam_scope(self):
        if self.exam_type == "monthly":
            if self.year is None or self.month is None:
                raise ValueError("Monthly Exam requires year and month.")
            if self.monthly_source in ("page_range", "both") and (self.start_page is None or self.end_page is None or self.end_page < self.start_page):
                raise ValueError("Select a valid Quran page range (1–604).")
        elif self.exam_type == "juz":
            if self.juz_no is None:
                raise ValueError("Select one Juz for Juz Completion Exam.")
        elif self.start_juz is None or self.end_juz is None or self.end_juz < self.start_juz:
            raise ValueError("Select a valid Juz range for Semester Exam.")
        return self

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
    exam_type: str = Field(default="monthly", pattern="^(monthly|juz|semester)$")
    juz_no: int | None = Field(default=None, ge=1, le=30)
    start_juz: int | None = Field(default=None, ge=1, le=30)
    end_juz: int | None = Field(default=None, ge=1, le=30)
    monthly_source: str = Field(default="new_lesson", pattern="^(new_lesson|page_range|both)$")
    start_page: int | None = Field(default=None, ge=1, le=604)
    end_page: int | None = Field(default=None, ge=1, le=604)
    confirmed: bool = False
    allow_confirmed_edit: bool = False
    session_id: int | None = Field(default=None, gt=0)
    questions: list[ExamQuestionInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_monthly_page_range(self):
        if self.exam_type == "monthly" and self.monthly_source in ("page_range", "both"):
            if self.start_page is None or self.end_page is None or self.end_page < self.start_page:
                raise ValueError("Select a valid Quran page range (1–604).")
        return self

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

class RefreshInput(BaseModel):
    refresh_token: str = Field(min_length=40, max_length=200)

class ChangePasswordInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=6, max_length=256)

class ChangeTeacherCredentialsInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_login_id: str = Field(min_length=3, max_length=80)
    new_password: str = Field(min_length=6, max_length=256)

    @field_validator("new_login_id")
    @classmethod
    def clean_login_id(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Login ID must contain at least 3 characters")
        return value

class ParentPasswordResetInput(BaseModel):
    new_password: str = Field(min_length=6, max_length=256)

class StudentInput(BaseModel):
    student_code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    class_name: str | None = Field(default=None, max_length=100)
    total_pages: int = Field(default=604, ge=1, le=2000)
    completed_pages: float = Field(default=0, ge=0, le=2000)
    current_juz: int = Field(default=30, ge=26, le=30)
    next_juz_pages: float = Field(default=0, ge=0, le=21)
    journey_start_date: date | None = None
    photo_data: str | None = Field(default=None, max_length=15_000_000)

    @model_validator(mode="after")
    def validate_progress(self):
        if self.completed_pages > self.total_pages:
            raise ValueError("Completed pages cannot exceed total pages")
        if self.current_juz == 26 and self.next_juz_pages != 0:
            raise ValueError("Juz 26 is the final Juz in this curriculum; next Juz pages must be 0")
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

class MonthlyCharacterPointsInput(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    cleanliness_points: int = Field(default=0, ge=0, le=10)
    discipline_points: int = Field(default=0, ge=0, le=10)
    worship_points: int = Field(default=0, ge=0, le=10)

class StudentUpdateInput(BaseModel):
    student_code: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    class_name: str | None = Field(default=None, max_length=100)
    total_pages: int | None = Field(default=None, ge=1, le=2000)
    completed_pages: float | None = Field(default=None, ge=0, le=2000)
    current_juz: int | None = Field(default=None, ge=26, le=30)
    next_juz_pages: float | None = Field(default=None, ge=0, le=21)
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
    if _ayah_ordinal(start_surah, start_ayah) > _ayah_ordinal(end_surah, end_ayah):
        raise ValueError("Reading range must follow Quran order from start to end")

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

def _cloudinary_ready() -> bool:
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
    api_key = os.getenv("CLOUDINARY_API_KEY", "").strip()
    api_secret = os.getenv("CLOUDINARY_API_SECRET", "").strip()
    if not (cloud_name and api_key and api_secret):
        return False
    cloudinary.config(cloud_name=cloud_name, api_key=api_key, api_secret=api_secret, secure=True)
    return True


def _store_student_photo(photo_value: str | None, student_id: int | str) -> tuple[str | None, str | None]:
    if not photo_value:
        return None, None
    if photo_value.startswith(("https://", "http://")):
        return photo_value, None
    match = re.fullmatch(r"data:image/(jpeg|jpg|png|webp);base64,([A-Za-z0-9+/=\\r\\n]+)", photo_value)
    if not match:
        raise HTTPException(status_code=422, detail="Student photo must be a valid JPEG, PNG, or WebP image.")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Invalid student photo data.") from exc
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Student photo must be smaller than 10 MB.")
    if not _cloudinary_ready():
        raise HTTPException(status_code=503, detail="Cloudinary is not configured. Check the Render environment variables.")
    try:
        result = cloudinary.uploader.upload(io.BytesIO(raw), folder="quranjourney/students",
            public_id=f"student-{student_id}-{uuid.uuid4().hex[:10]}", resource_type="image",
            overwrite=False, allowed_formats=["jpg", "jpeg", "png", "webp"])
        return result["secure_url"], result["public_id"]
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Student photo upload failed. Please retry.") from exc


def _delete_cloudinary_photo(public_id: str | None) -> None:
    if not public_id or not _cloudinary_ready():
        return
    try:
        cloudinary.uploader.destroy(public_id, resource_type="image", invalidate=True)
    except Exception:
        pass


app = FastAPI(title="Quran Journey API", version="0.1.0")
_MUSHAF_WIDTHS = {320, 480, 800, 1024, 1260}

@lru_cache(maxsize=8)
def _load_mushaf_page_image(page: int, width: int) -> bytes:
    url = f"https://android.quran.com/data/width_{width}/page{page:03d}.png"
    try:
        with urlopen(Request(url, headers={"User-Agent": "QuranJourney-Mushaf-Proxy/1.0"}), timeout=30) as response:
            return response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail=f"Official Madani Mushaf page {page} is temporarily unavailable.") from exc


@lru_cache(maxsize=4)
def _load_mushaf_ayah_coordinates(width: int) -> dict:
    url = f"https://android.quran.com/data/databases/ayahinfo/ayahinfo_{width}.zip"
    try:
        with urlopen(Request(url, headers={"User-Agent": "QuranJourney-Mushaf-Proxy/1.0"}), timeout=45) as response:
            archive_bytes = response.read()
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            database_names = [name for name in archive.namelist() if name.lower().endswith(".db")]
            if not database_names:
                raise ValueError("Official ayah-info archive contains no SQLite database.")
            database_bytes = archive.read(database_names[0])
        with tempfile.NamedTemporaryFile(suffix=".db") as database_file:
            database_file.write(database_bytes)
            database_file.flush()
            connection = sqlite3.connect(f"file:{database_file.name}?mode=ro", uri=True)
            try:
                pages = {}
                table_names = {
                    row[0] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if "glyphs" not in table_names:
                    raise ValueError("Official ayah-info database has no glyph coordinate table.")
                query = """
                    SELECT page_number, sura_number, ayah_number, line_number,
                           MIN(min_x), MIN(min_y), MAX(max_x), MAX(max_y)
                    FROM glyphs
                    GROUP BY page_number, sura_number, ayah_number, line_number
                    ORDER BY page_number, sura_number, ayah_number, line_number
                """
                for row in connection.execute(query):
                    page, surah, ayah, line, left, top, right, bottom = row
                    item = pages.setdefault(int(page), {}).setdefault(
                        f"{int(surah)}:{int(ayah)}",
                        {"surah": int(surah), "ayah": int(ayah), "rects": []},
                    )
                    item["rects"].append([int(left), int(top), int(right), int(bottom)])
                if "ayah_markers" in table_names:
                    for page, surah, ayah, x, y in connection.execute(
                        "SELECT page_number, sura_number, ayah_number, x, y FROM ayah_markers ORDER BY page_number, sura_number, ayah_number"
                    ):
                        pages.setdefault(int(page), {}).setdefault("markers", []).append(
                            {"surah": int(surah), "ayah": int(ayah), "x": int(x), "y": int(y)}
                        )
                if "sura_headers" in table_names:
                    for page, surah, x, y, width_value, height in connection.execute(
                        "SELECT page_number, sura_number, x, y, width, height FROM sura_headers ORDER BY page_number, sura_number"
                    ):
                        pages.setdefault(int(page), {}).setdefault("headers", []).append(
                            {"surah": int(surah), "x": int(x), "y": int(y),
                             "width": int(width_value), "height": int(height)}
                        )
                return {
                    "edition": "MADANI_1405",
                    "width": width,
                    "pages": {
                        str(page): {
                            "ayahs": sorted(
                                [value for key, value in content.items() if ":" in key],
                                key=lambda value: (value["surah"], value["ayah"]),
                            ),
                            "markers": content.get("markers", []),
                            "headers": content.get("headers", []),
                        }
                        for page, content in pages.items()
                    },
                }
            finally:
                connection.close()
    except HTTPException:
        raise
    except (HTTPError, URLError, TimeoutError, zipfile.BadZipFile, sqlite3.Error, OSError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Official Madani Mushaf ayah-position data is temporarily unavailable.") from exc


@app.get("/quran/mushaf/page/{page}")
def get_mushaf_page(page: int, width: int = Query(default=480)):
    if page < 1 or page > 604:
        raise HTTPException(status_code=404, detail="Mushaf page must be between 1 and 604.")
    if width not in _MUSHAF_WIDTHS:
        raise HTTPException(status_code=400, detail="Unsupported Mushaf image width.")
    image = _load_mushaf_page_image(page, width)
    return Response(
        content=image,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Mushaf-Edition": "MADANI_1405"},
    )


@app.get("/quran/mushaf/page/{page}/coordinates")
def get_mushaf_page_coordinates(page: int, width: int = Query(default=480)):
    if page < 1 or page > 604:
        raise HTTPException(status_code=404, detail="Mushaf page must be between 1 and 604.")
    if width not in _MUSHAF_WIDTHS:
        raise HTTPException(status_code=400, detail="Unsupported Mushaf coordinate width.")
    all_pages = _load_mushaf_ayah_coordinates(width)
    page_data = all_pages["pages"].get(str(page))
    if not page_data:
        raise HTTPException(status_code=404, detail=f"Coordinates for Mushaf page {page} are unavailable.")
    return {**page_data, "page": page, "width": width, "edition": "MADANI_1405"}


origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "https://safumk99-byte.github.io").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])

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
        token_version = int(payload.get("ver", 0))
    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Account inactive")
    if token_version != user.auth_token_version:
        raise HTTPException(status_code=401, detail="Session revoked. Please sign in again.")
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
    """Enforce per-student access. Never confirm another parent's student ID exists."""
    if user.role == "teacher":
        student = db.get(Student, student_id)
        if student is None or not student.is_active:
            raise HTTPException(status_code=404, detail="Student not found")
        return
    if user.role != "parent":
        raise HTTPException(status_code=403, detail="Student access required")
    linked = db.scalar(
        select(ParentStudent.id)
        .join(Student, Student.id == ParentStudent.student_id)
        .where(
            ParentStudent.parent_user_id == user.id,
            ParentStudent.student_id == student_id,
            Student.is_active.is_(True),
        )
    )
    if linked is None:
        # Same response for an unknown ID, inactive student, or another parent's child.
        raise HTTPException(status_code=404, detail="Student record not found")

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
        quartered = number * 4
        if abs(quartered - round(quartered)) > 1e-9:
            return 0.0
        return round(number, 2)
    except (ValueError, TypeError):
        return 0.0


# Quran page/Juz metadata for the standard 604-page Madinah Mushaf.
_QURAN_MAP_PATH = os.path.join(os.path.dirname(__file__), "quran_page_map.json")
with open(_QURAN_MAP_PATH, "r", encoding="utf-8") as _map_file:
    _QURAN_MAP = json.load(_map_file)
_QURAN_PAGE_STARTS = [
    (int(page), sum(SURAH_AYAH_COUNTS[:int(surah)-1]) + int(ayah)-1)
    for page, surah, ayah in _QURAN_MAP["pages"]
]
_QURAN_JUZ_STARTS = [
    (int(juz), sum(SURAH_AYAH_COUNTS[:int(surah)-1]) + int(ayah)-1)
    for juz, surah, ayah in _QURAN_MAP["juz_starts"]
]
_QURAN_PAGE_INTERVALS = [
    (page, start, (_QURAN_PAGE_STARTS[i+1][1]-1 if i+1 < len(_QURAN_PAGE_STARTS) else sum(SURAH_AYAH_COUNTS)-1))
    for i, (page, start) in enumerate(_QURAN_PAGE_STARTS)
]
_QURAN_JUZ_INTERVALS = [
    (juz, start, (_QURAN_JUZ_STARTS[i+1][1]-1 if i+1 < len(_QURAN_JUZ_STARTS) else sum(SURAH_AYAH_COUNTS)-1))
    for i, (juz, start) in enumerate(_QURAN_JUZ_STARTS)
]

def _ayah_ordinal(surah: int, ayah: int) -> int:
    return sum(SURAH_AYAH_COUNTS[:surah-1]) + ayah - 1

def _lesson_juz_page_contributions(start_surah: int | None, start_ayah: int | None,
                                   end_surah: int | None, end_ayah: int | None,
                                   pages_value: str | None) -> dict[str, int]:
    """Store exact ayah ordinals; unioning these later prevents duplicate lesson coverage."""
    if not all(v is not None for v in (start_surah, start_ayah, end_surah, end_ayah)) or reading_page_count(pages_value) <= 0:
        return {}
    start_ord = _ayah_ordinal(int(start_surah), int(start_ayah))
    end_ord = _ayah_ordinal(int(end_surah), int(end_ayah))
    # Preserve the teacher's entered direction in the record, but calculate
    # coverage over the inclusive Quran-order interval in either direction.
    return {"start": min(start_ord, end_ord), "end": max(start_ord, end_ord)}

def _juz_page_capacity(juz_no: int) -> float:
    interval = next(((start, end) for number, start, end in _QURAN_JUZ_INTERVALS if number == juz_no), None)
    if interval is None:
        return 0.0
    start, end = interval
    return sum(max(0, min(page_end, end) - max(page_start, start) + 1) /
               (page_end - page_start + 1)
               for _page, page_start, page_end in _QURAN_PAGE_INTERVALS
               if min(page_end, end) >= max(page_start, start))

def _set_reading_juz_contribution(row: ReadingEntry) -> None:
    values = _lesson_juz_page_contributions(
        row.start_surah, row.start_ayah, row.end_surah, row.end_ayah, row.pages
    )
    row.juz_progress_data = json.dumps(values, separators=(",", ":")) if values else None

# This curriculum studies only Juz 30 down to Juz 26 (Surah Al-Ahqaf).
# Values 1..5 were used by the earlier incorrect progress counter; normalize
# those existing stored values to the real Quran Juz without changing DB rows.
def _normalize_curriculum_juz(value: int | None) -> int:
    number = int(value or 30)
    if 1 <= number <= 5:
        return 31 - number
    return max(26, min(30, number))

def _sync_student_juz_progress(db: Session, student_id: int) -> None:
    """Rebuild sequential study progress from unique New Lesson ayah coverage."""
    student = db.get(Student, student_id)
    if student is None:
        return
    if student.juz_progress_base_juz is None:
        student.juz_progress_base_juz = _normalize_curriculum_juz(student.current_juz)
        student.juz_progress_base_pages = float(student.next_juz_pages or 0)

    # New Lesson coordinates are stored in the primary range columns. Revision
    # ranges use their own columns and therefore never enter this calculation.
    # Rebuild from coordinates rather than relying only on juz_progress_data so
    # older New Lesson rows created before tracking was introduced are included.
    intervals: list[tuple[int, int]] = []
    rows = db.scalars(select(ReadingEntry).where(
        ReadingEntry.student_id == student_id,
        ReadingEntry.start_surah.is_not(None),
        ReadingEntry.start_ayah.is_not(None),
        ReadingEntry.end_surah.is_not(None),
        ReadingEntry.end_ayah.is_not(None),
    ).order_by(ReadingEntry.entry_date, ReadingEntry.id)).all()
    for entry in rows:
        if reading_page_count(entry.pages) <= 0:
            continue
        try:
            start = _ayah_ordinal(int(entry.start_surah), int(entry.start_ayah))
            end = _ayah_ordinal(int(entry.end_surah), int(entry.end_ayah))
        except (TypeError, ValueError, IndexError):
            continue
        if 0 <= start <= sum(SURAH_AYAH_COUNTS) - 1 and 0 <= end <= sum(SURAH_AYAH_COUNTS) - 1:
            intervals.append((min(start, end), max(start, end)))

    # Merge overlapping/repeated ranges so duplicate Ayahs are never counted twice.
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    by_juz: dict[int, float] = {}
    for _page, page_start, page_end in _QURAN_PAGE_INTERVALS:
        page_length = page_end - page_start + 1
        for actual_juz, juz_start, juz_end in _QURAN_JUZ_INTERVALS:
            left_bound, right_bound = max(page_start, juz_start), min(page_end, juz_end)
            if left_bound > right_bound:
                continue
            covered = sum(
                max(0, min(end, right_bound) - max(start, left_bound) + 1)
                for start, end in merged
            )
            if covered:
                by_juz[actual_juz] = by_juz.get(actual_juz, 0.0) + covered / page_length

    previous_current = _normalize_curriculum_juz(student.current_juz)
    current = _normalize_curriculum_juz(student.juz_progress_base_juz)
    pending = max(0.0, float(student.juz_progress_base_pages or 0))
    # Move down from Juz 30 to Juz 26 only. Juz 26 is the final curriculum unit.
    while current > 26:
        next_actual_juz = current - 1
        available = pending + by_juz.get(next_actual_juz, 0.0)
        capacity = _juz_page_capacity(next_actual_juz)
        if capacity <= 0 or available + 1e-6 < capacity:
            pending = available
            break
        pending = max(0.0, available - capacity)
        current -= 1

    student.current_juz = current
    student.next_juz_pages = 0.0 if current == 26 else round(pending, 2)
    if current < previous_current:
        notify_student_parents(
            db, student.id, f"current-juz:{current}", "New Juz reached",
            f"{student.name} has reached Juz {current}.", "juz"
        )

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
    # Additive holiday scope migration for existing databases.
    from sqlalchemy import inspect
    holiday_columns = {c["name"] for c in inspect(engine).get_columns("calendar_holidays")}
    with engine.begin() as conn:
        if "class_name" not in holiday_columns:
            conn.execute(sql_text("ALTER TABLE calendar_holidays ADD COLUMN class_name VARCHAR(100) NULL"))
        if "category" not in holiday_columns:
            conn.execute(sql_text("ALTER TABLE calendar_holidays ADD COLUMN category VARCHAR(80) NULL"))
    # Additive auth-version migration for existing accounts.
    from sqlalchemy import inspect
    if "auth_token_version" not in {c["name"] for c in inspect(engine).get_columns("users")}:
        with engine.begin() as conn:
            conn.execute(sql_text("ALTER TABLE users ADD COLUMN auth_token_version INTEGER NOT NULL DEFAULT 0"))
    # Preserve existing profile-level character points as this month's opening values.
    # The NOT EXISTS guard makes this migration safe to run on every restart.
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    with engine.begin() as conn:
        conn.execute(sql_text("""
            INSERT INTO monthly_character_points
                (student_id, year, month, cleanliness_points, discipline_points, worship_points)
            SELECT s.id, :year, :month, s.cleanliness_points, s.discipline_points, s.worship_points
            FROM students s
            WHERE (COALESCE(s.cleanliness_points, 0) <> 0
                OR COALESCE(s.discipline_points, 0) <> 0
                OR COALESCE(s.worship_points, 0) <> 0)
              AND NOT EXISTS (
                SELECT 1 FROM monthly_character_points m
                WHERE m.student_id = s.id AND m.year = :year AND m.month = :month
              )
        """), {"year": today.year, "month": today.month})
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
    # Additive Juz-progress migration for existing SQLite databases as well as fresh installs.
    from sqlalchemy import inspect
    if engine.dialect.name == "sqlite":
        sqlite_columns = {
            "students": {
                "juz_progress_base_juz": "INTEGER NULL",
                "juz_progress_base_pages": "FLOAT NULL",
            },
            "reading_entries": {"juz_progress_data": "TEXT NULL"},
        }
        with engine.begin() as conn:
            for table, columns in sqlite_columns.items():
                existing = {column["name"] for column in inspect(conn).get_columns(table)}
                for column, definition in columns.items():
                    if column not in existing:
                        conn.execute(sql_text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}'))
    # Additive, non-destructive migration for databases created by earlier scaffold versions.
    if engine.dialect.name == "postgresql":
        additive = {
            "students": {
                "total_pages": "INTEGER NOT NULL DEFAULT 604",
                "completed_pages": "DOUBLE PRECISION NOT NULL DEFAULT 0",
                "current_juz": "INTEGER NOT NULL DEFAULT 1",
                "next_juz_pages": "DOUBLE PRECISION NOT NULL DEFAULT 0",
                "juz_progress_base_juz": "INTEGER NULL",
                "juz_progress_base_pages": "DOUBLE PRECISION NULL",
                "journey_start_date": "DATE NULL",
                "photo_data": "TEXT NULL",
                "photo_public_id": "VARCHAR(255) NULL",
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
            "reading_entries": {"legacy_id": "VARCHAR(120) NULL", "start_surah": "INTEGER NULL", "start_ayah": "INTEGER NULL", "end_surah": "INTEGER NULL", "end_ayah": "INTEGER NULL", "recent_start_surah": "INTEGER NULL", "recent_start_ayah": "INTEGER NULL", "recent_end_surah": "INTEGER NULL", "recent_end_ayah": "INTEGER NULL", "general_start_surah": "INTEGER NULL", "general_start_ayah": "INTEGER NULL", "general_end_surah": "INTEGER NULL", "general_end_ayah": "INTEGER NULL", "recent_pages": "VARCHAR(20) NULL", "general_pages": "VARCHAR(20) NULL", "new_lesson": "TEXT NULL", "pages": "VARCHAR(200) NULL", "recent_revision": "TEXT NULL", "general_revision": "TEXT NULL", "remarks": "TEXT NULL", "juz_progress_data": "TEXT NULL"},
            "attendance": {"legacy_id": "VARCHAR(120) NULL", "period": "INTEGER NOT NULL DEFAULT 1"},
            "exam_sessions": {"exam_type": "VARCHAR(20) NOT NULL DEFAULT 'monthly'", "start_juz": "INTEGER NULL", "end_juz": "INTEGER NULL", "monthly_source": "VARCHAR(20) NOT NULL DEFAULT 'new_lesson'", "start_page": "INTEGER NULL", "end_page": "INTEGER NULL"},
        }
        with engine.begin() as conn:
            for table, columns in additive.items():
                for column, definition in columns.items():
                    conn.execute(sql_text(f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{column}" {definition}'))
            # Convert legacy integer progress to a fractional type without losing existing values.
            conn.execute(sql_text('ALTER TABLE "students" ALTER COLUMN "completed_pages" TYPE DOUBLE PRECISION USING "completed_pages"::double precision'))
            conn.execute(sql_text('ALTER TABLE "students" ALTER COLUMN "completed_pages" SET DEFAULT 0'))
            conn.execute(sql_text('ALTER TABLE "students" ALTER COLUMN "next_juz_pages" TYPE DOUBLE PRECISION USING "next_juz_pages"::double precision'))
            conn.execute(sql_text('ALTER TABLE "students" ALTER COLUMN "next_juz_pages" SET DEFAULT 0'))
            for table in ("students", "daily_marks", "reading_entries", "attendance"):
                conn.execute(sql_text(f'CREATE UNIQUE INDEX IF NOT EXISTS "uq_{table}_legacy_id" ON "{table}" ("legacy_id") WHERE "legacy_id" IS NOT NULL'))
    # Bootstrap the initial teacher only when the database has no teacher account.
    # This prevents old Render INITIAL_TEACHER_* values from recreating a second
    # account after the existing teacher changes their Login ID.
    login_id = os.getenv("INITIAL_TEACHER_ID", "").strip()
    password = os.getenv("INITIAL_TEACHER_PASSWORD", "")
    if login_id and password:
        with SessionLocal() as db:
            teacher_exists = db.scalar(select(User.id).where(User.role == "teacher").limit(1))
            if not teacher_exists:
                existing_login = db.scalar(select(User).where(User.login_id == login_id))
                if not existing_login:
                    if len(password) < 12:
                        raise RuntimeError("INITIAL_TEACHER_PASSWORD must be at least 12 characters")
                    db.add(User(login_id=login_id, password_hash=password_hash.hash(password), role="teacher"))
                    db.commit()

@app.get("/health")
def health():
    return {"status": "ok", "service": "quran-journey-api"}

def _new_access_token(user: User) -> str:
    return jwt.encode(
        {"sub": str(user.id), "role": user.role, "ver": user.auth_token_version,
         "exp": datetime.now(timezone.utc) + timedelta(minutes=TOKEN_MINUTES)},
        JWT_SECRET, algorithm="HS256",
    )

def _refresh_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def _issue_refresh_session(user: User, db: Session) -> str:
    raw = secrets.token_urlsafe(48)
    db.add(AuthSession(user_id=user.id, token_hash=_refresh_hash(raw),
                       expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_DAYS)))
    return raw

def _revoke_user_sessions(db: Session, user_id: int) -> None:
    now = datetime.now(timezone.utc)
    for session in db.scalars(select(AuthSession).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
    )).all():
        session.revoked_at = now

@app.post("/auth/login")
def login(data: LoginInput, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.login_id == data.login_id.strip()))
    if not user or not user.is_active or not password_hash.verify(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid login ID or password")
    refresh_token = _issue_refresh_session(user, db)
    db.commit()
    return {"access_token": _new_access_token(user), "refresh_token": refresh_token,
            "token_type": "bearer", "expires_in": TOKEN_MINUTES * 60,
            "refresh_expires_in": REFRESH_DAYS * 86400,
            "user": {"id": user.id, "login_id": user.login_id, "role": user.role}}

@app.post("/auth/refresh")
def refresh_session(data: RefreshInput, db: Session = Depends(get_db)):
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == _refresh_hash(data.refresh_token)))
    now = datetime.now(timezone.utc)
    if not session or session.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Refresh session is invalid. Please sign in again.")
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        session.revoked_at = now
        db.commit()
        raise HTTPException(status_code=401, detail="Refresh session expired. Please sign in again.")
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        session.revoked_at = now
        db.commit()
        raise HTTPException(status_code=401, detail="Account inactive")
    session.revoked_at = now
    new_refresh_token = _issue_refresh_session(user, db)
    db.commit()
    return {"access_token": _new_access_token(user), "refresh_token": new_refresh_token,
            "token_type": "bearer", "expires_in": TOKEN_MINUTES * 60,
            "refresh_expires_in": REFRESH_DAYS * 86400}

@app.post("/auth/logout")
def logout(data: RefreshInput, db: Session = Depends(get_db)):
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == _refresh_hash(data.refresh_token)))
    if session and session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return {"success": True}

@app.get("/auth/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "login_id": user.login_id, "role": user.role}

@app.post("/auth/change-password")
def change_password(data: ChangePasswordInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Allow authenticated teachers and parents to change their own password only."""
    if user.role not in ("teacher", "parent"):
        raise HTTPException(status_code=403, detail="Teacher or Parent access required")
    if not password_hash.verify(data.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if password_hash.verify(data.new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="New password must be different from the current password")
    user.password_hash = password_hash.hash(data.new_password)
    user.auth_token_version += 1
    _revoke_user_sessions(db, user.id)
    db.commit()
    return {"success": True, "message": "Password changed successfully. Please sign in again."}

@app.post("/auth/change-teacher-credentials")
def change_teacher_credentials(data: ChangeTeacherCredentialsInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Change the authenticated teacher's own Login ID and password atomically."""
    if not password_hash.verify(data.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    new_login_id = data.new_login_id.strip()
    duplicate = db.scalar(select(User).where(User.login_id == new_login_id, User.id != user.id))
    if duplicate:
        raise HTTPException(status_code=409, detail="This Login ID is already in use. Choose another one.")
    if password_hash.verify(data.new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="New password must be different from the current password")
    user.login_id = new_login_id
    user.password_hash = password_hash.hash(data.new_password)
    user.auth_token_version += 1
    _revoke_user_sessions(db, user.id)
    db.commit()
    return {"success": True, "login_id": user.login_id, "message": "Login ID and password updated. Please sign in again."}

@app.get("/students")
def list_students(user: User = Depends(current_user), db: Session = Depends(get_db)):
    ids = allowed_student_ids(user, db)
    query = select(Student).where(Student.is_active.is_(True))
    if ids is not None:
        if not ids:
            return []
        query = query.where(Student.id.in_(ids))
    student_rows = db.scalars(query.order_by(Student.name)).all()
    lesson_days = dict(db.execute(select(ReadingEntry.student_id, func.count(func.distinct(ReadingEntry.entry_date))).where(ReadingEntry.student_id.in_([s.id for s in student_rows] or [-1]), func.cast(ReadingEntry.pages, Float) > 0).group_by(ReadingEntry.student_id)).all())
    return [{"id": s.id, "student_code": s.student_code, "name": s.name, "class_name": s.class_name, "total_pages": s.total_pages, "completed_pages": s.completed_pages, "new_lesson_days": lesson_days.get(s.id, 0), "current_juz": _normalize_curriculum_juz(s.current_juz), "next_juz_pages": s.next_juz_pages or 0, "journey_start_date": s.journey_start_date.isoformat() if s.journey_start_date else None, "photo_data": s.photo_data, "cleanliness_points": s.cleanliness_points, "discipline_points": s.discipline_points, "worship_points": s.worship_points} for s in student_rows]

@app.post("/students", status_code=201)
def create_student(data: StudentInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    if db.scalar(select(Student).where(Student.student_code == data.student_code.strip())):
        raise HTTPException(status_code=409, detail="Student code already exists")
    student = Student(
        student_code=data.student_code.strip(), name=data.name.strip(), class_name=data.class_name,
        total_pages=data.total_pages, completed_pages=data.completed_pages, current_juz=data.current_juz,
        next_juz_pages=data.next_juz_pages, journey_start_date=data.journey_start_date,
    )
    if data.photo_data:
        student.photo_data, student.photo_public_id = _store_student_photo(data.photo_data, data.student_code.strip())
    db.add(student)
    db.commit()
    db.refresh(student)
    return {"id": student.id, "student_code": student.student_code, "name": student.name, "class_name": student.class_name,
            "total_pages": student.total_pages, "completed_pages": student.completed_pages, "current_juz": _normalize_curriculum_juz(student.current_juz), "next_juz_pages": student.next_juz_pages or 0,
            "journey_start_date": student.journey_start_date.isoformat() if student.journey_start_date else None,
            "photo_data": student.photo_data, "cleanliness_points": student.cleanliness_points, "discipline_points": student.discipline_points, "worship_points": student.worship_points}

@app.patch("/students/{student_id}")
def update_student(student_id: int, data: StudentUpdateInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    student = db.scalar(select(Student).where(Student.id == student_id, Student.is_active.is_(True)))
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    values = data.model_dump(exclude_unset=True)
    old_photo_public_id = student.photo_public_id
    if "photo_data" in values:
        incoming_photo = values.pop("photo_data")
        if incoming_photo and incoming_photo != student.photo_data:
            student.photo_data, student.photo_public_id = _store_student_photo(incoming_photo, student.id)
        elif not incoming_photo:
            student.photo_data, student.photo_public_id = None, None
    old_percent = round((float(student.completed_pages or 0) / max(int(student.total_pages or 1), 1)) * 100, 1)
    old_juz = _normalize_curriculum_juz(student.current_juz)
    if "student_code" in values and db.scalar(select(Student).where(Student.student_code == values["student_code"], Student.id != student_id)):
        raise HTTPException(status_code=409, detail="Student code already exists")
    total_pages = values.get("total_pages", student.total_pages)
    completed_pages = values.get("completed_pages", student.completed_pages)
    if completed_pages > total_pages:
        raise HTTPException(status_code=422, detail="Completed pages cannot exceed total pages")
    if values.get("current_juz", student.current_juz) == 26 and values.get("next_juz_pages", student.next_juz_pages or 0) != 0:
        raise HTTPException(status_code=422, detail="Juz 26 is the final Juz in this curriculum; next Juz pages must be 0")
    for key, value in values.items():
        setattr(student, key, value)
    # A teacher's explicit Juz edit resets the automatic-tracking baseline.
    if "current_juz" in values or "next_juz_pages" in values:
        student.juz_progress_base_juz = _normalize_curriculum_juz(student.current_juz)
        student.juz_progress_base_pages = float(student.next_juz_pages or 0)
    new_percent = round((float(student.completed_pages or 0) / max(int(student.total_pages or 1), 1)) * 100, 1)
    if new_percent > old_percent:
        notify_student_parents(db, student.id, f"progress-percent:{new_percent}", "Quran progress updated",
                               f"{student.name}'s Quran progress has reached {new_percent}%.", "progress")
    if int(student.current_juz or 30) < old_juz:
        notify_student_parents(db, student.id, f"current-juz:{student.current_juz}", "New Juz reached",
                               f"{student.name} has reached Juz {student.current_juz}.", "juz")
    db.commit()
    db.refresh(student)
    if old_photo_public_id and old_photo_public_id != student.photo_public_id:
        _delete_cloudinary_photo(old_photo_public_id)
    return {"id": student.id, "student_code": student.student_code, "name": student.name, "class_name": student.class_name,
            "total_pages": student.total_pages, "completed_pages": student.completed_pages, "current_juz": student.current_juz,
            "next_juz_pages": student.next_juz_pages or 0,
            "journey_start_date": student.journey_start_date.isoformat() if student.journey_start_date else None,
            "photo_data": student.photo_data}


@app.delete("/students/{student_id}", status_code=204)
def delete_student(student_id: int, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    student = db.scalar(select(Student).where(Student.id == student_id, Student.is_active.is_(True)))
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    # Soft-delete so accidental removal does not cascade-delete reading, attendance, marks, or parent links.
    old_photo_public_id = student.photo_public_id
    student.is_active = False
    db.commit()
    _delete_cloudinary_photo(old_photo_public_id)
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

@app.get("/parents")
def list_parent_accounts(user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    """List parent login accounts and their linked active students for teacher administration."""
    parents = db.scalars(
        select(User).where(User.role == "parent", User.is_active.is_(True)).order_by(User.login_id)
    ).all()
    result = []
    for parent in parents:
        student_names = db.scalars(
            select(Student.name)
            .join(ParentStudent, ParentStudent.student_id == Student.id)
            .where(ParentStudent.parent_user_id == parent.id, Student.is_active.is_(True))
            .order_by(Student.name)
        ).all()
        result.append({
            "id": parent.id,
            "login_id": parent.login_id,
            "linked_students": student_names,
        })
    return result


@app.post("/parents/{parent_id}/reset-password")
def reset_parent_password(
    parent_id: int,
    data: ParentPasswordResetInput,
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Allow teachers to reset Parent accounts only; teacher accounts are never eligible."""
    parent = db.scalar(select(User).where(
        User.id == parent_id,
        User.role == "parent",
        User.is_active.is_(True),
    ))
    if not parent:
        raise HTTPException(status_code=404, detail="Parent account not found")
    parent.password_hash = password_hash.hash(data.new_password)
    parent.auth_token_version += 1
    _revoke_user_sessions(db, parent.id)
    db.commit()
    return {"success": True, "message": "Parent password reset successfully."}


@app.get("/parent/notifications")
def get_parent_notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "parent":
        raise HTTPException(status_code=403, detail="Parent access required")
    rows = db.execute(
        select(ParentNotification, Student.name)
        .join(ParentStudent, ParentStudent.student_id == ParentNotification.student_id)
        .join(Student, Student.id == ParentNotification.student_id)
        .where(
            ParentNotification.parent_user_id == user.id,
            ParentStudent.parent_user_id == user.id,
            Student.is_active.is_(True),
        )
        .order_by(ParentNotification.created_at.desc())
        .limit(100)
    ).all()
    return [{"id": r.id, "student_id": r.student_id, "student_name": student_name,
             "title": r.title, "message": r.message, "type": r.notification_type,
             "created_at": r.created_at.isoformat(), "read": r.read_at is not None}
            for r, student_name in rows]


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

@app.get("/students/{student_id}/character-points")
def get_monthly_character_points(student_id: int, year: int = Query(ge=2000, le=2100), month: int = Query(ge=1, le=12), user: User = Depends(current_user), db: Session = Depends(get_db)):
    check_student_access(student_id, user, db)
    row = db.scalar(select(MonthlyCharacterPoints).where(MonthlyCharacterPoints.student_id == student_id, MonthlyCharacterPoints.year == year, MonthlyCharacterPoints.month == month))
    return {"student_id": student_id, "year": year, "month": month, "cleanliness_points": row.cleanliness_points if row else 0, "discipline_points": row.discipline_points if row else 0, "worship_points": row.worship_points if row else 0}

@app.put("/students/{student_id}/character-points")
def save_monthly_character_points(student_id: int, data: MonthlyCharacterPointsInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    check_student_access(student_id, user, db)
    row = db.scalar(select(MonthlyCharacterPoints).where(MonthlyCharacterPoints.student_id == student_id, MonthlyCharacterPoints.year == data.year, MonthlyCharacterPoints.month == data.month))
    if row is None:
        row = MonthlyCharacterPoints(student_id=student_id, year=data.year, month=data.month)
        db.add(row)
    row.cleanliness_points, row.discipline_points, row.worship_points = data.cleanliness_points, data.discipline_points, data.worship_points
    db.commit()
    return {"student_id": student_id, **data.model_dump()}

@app.get("/points/monthly-ranking")
def monthly_points_ranking(year: int = Query(ge=2000, le=2100), month: int = Query(ge=1, le=12), user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    active = db.scalars(select(Student).where(Student.is_active.is_(True)).order_by(Student.name)).all()
    ids = {s.id for s in active}
    # Hifz is based on monthly Progress remarks containing "thamam".
    # Normalize each student's monthly count against the highest count in this month.
    thamam_counts = {sid: 0 for sid in ids}
    progress_rows = db.scalars(select(ReadingEntry).where(
        ReadingEntry.student_id.in_(ids or {-1}),
        ReadingEntry.entry_date >= start,
        ReadingEntry.entry_date < end,
    )).all()
    for row in progress_rows:
        if "thamam" in (row.remarks or "").casefold():
            thamam_counts[row.student_id] += 1
    max_thamam = max(thamam_counts.values(), default=0)
    hifz_points = {
        sid: round((count / max_thamam) * 10, 2) if max_thamam else 0.0
        for sid, count in thamam_counts.items()
    }
    chars = db.scalars(select(MonthlyCharacterPoints).where(MonthlyCharacterPoints.student_id.in_(ids or {-1}), MonthlyCharacterPoints.year == year, MonthlyCharacterPoints.month == month)).all()
    char_by_id = {r.student_id: r for r in chars}
    exams = {}
    for row in db.scalars(select(ExamSession).where(ExamSession.student_id.in_(ids or {-1}), ExamSession.exam_date >= start, ExamSession.exam_date < end, ExamSession.confirmed.is_(True))).all():
        exams[row.student_id] = exams.get(row.student_id, 0) + int(row.total_marks or 0)
    results = []
    for st in active:
        c = char_by_id.get(st.id)
        ar = db.scalars(select(Attendance).where(Attendance.student_id == st.id, Attendance.attendance_date >= start, Attendance.attendance_date < end)).all()
        by_day = {}
        for x in ar:
            by_day.setdefault(x.attendance_date, []).append((x.status or "").lower())
        if st.class_name:
            work = set(db.scalars(select(Attendance.attendance_date).join(Student, Student.id == Attendance.student_id).where(Student.is_active.is_(True), Student.class_name == st.class_name, Attendance.attendance_date >= start, Attendance.attendance_date < end).distinct()).all())
        else:
            work = set(by_day)
        present = sum(1 for values in by_day.values() if values and all(v in {"present", "late"} for v in values))
        attendance = round(present / len(work) * 10, 2) if work else 0.0
        cleanliness = c.cleanliness_points if c else 0
        discipline = c.discipline_points if c else 0
        worship = c.worship_points if c else 0
        hifz = round(hifz_points.get(st.id, 0), 2)
        pareeksha = exams.get(st.id, 0)
        total = cleanliness + discipline + attendance + worship + hifz + pareeksha
        results.append({"student_id": st.id, "student_code": st.student_code, "name": st.name, "class_name": st.class_name or "Unassigned class", "month": f"{year:04d}-{month:02d}", "cleanliness_points": cleanliness, "discipline_points": discipline, "attendance_points": attendance, "worship_points": worship, "hifz": hifz, "pareeksha": pareeksha, "total_points": round(total, 2)})
    results.sort(key=lambda x: (-x["total_points"], x["name"].casefold()))
    for rank, item in enumerate(results, 1):
        item["rank"] = rank
    return results


@app.get("/points/leaderboard")
def points_leaderboard(year: int = Query(default=date.today().year, ge=2000, le=2100), month: int = Query(default=date.today().month, ge=1, le=12), user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Rank reading activity points for the selected calendar month; keep older entries as history."""
    month_start = date(year, month, 1)
    month_end = (date(year + 1, 1, 1) - timedelta(days=1)) if month == 12 else (date(year, month + 1, 1) - timedelta(days=1))
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

@app.get("/calendar/holidays")
def list_calendar_holidays(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(CalendarHoliday).order_by(CalendarHoliday.holiday_date)).all()
    return [{"id": r.id, "date": r.holiday_date.isoformat(), "reason": r.reason, "class_name": r.class_name, "category": r.category} for r in rows]


@app.post("/calendar/holidays", status_code=201)
def create_calendar_holiday(data: CalendarHolidayInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    row = CalendarHoliday(holiday_date=data.holiday_date, reason=data.reason, class_name=data.class_name, category=data.category)
    db.add(row)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="A holiday is already registered for this date")
    db.refresh(row)
    return {"id": row.id, "date": row.holiday_date.isoformat(), "reason": row.reason, "class_name": row.class_name, "category": row.category}


@app.patch("/calendar/holidays/{holiday_id}")
def update_calendar_holiday(holiday_id: int, data: CalendarHolidayInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    row = db.get(CalendarHoliday, holiday_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Holiday not found")
    row.holiday_date, row.reason = data.holiday_date, data.reason
    row.class_name, row.category = data.class_name, data.category
    row.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="A holiday is already registered for this date")
    return {"id": row.id, "date": row.holiday_date.isoformat(), "reason": row.reason}


@app.delete("/calendar/holidays/{holiday_id}", status_code=204)
def delete_calendar_holiday(holiday_id: int, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    row = db.get(CalendarHoliday, holiday_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Holiday not found")
    db.delete(row)
    db.commit()
    return Response(status_code=204)


def _period_bounds(day: date, kind: str):
    if kind == "week":
        # Weekly target runs Saturday through Thursday; Friday is excluded.
        start = day - timedelta(days=(day.weekday() - 5) % 7)
        return start, start + timedelta(days=5)
    start = day.replace(day=1)
    next_month = start.replace(day=28) + timedelta(days=4)
    next_month = next_month.replace(day=1)
    return start, next_month - timedelta(days=1)


# Carry-forward reset: ignore all target deficits and reading totals before this week.
# Keep this as a fixed launch date; do not calculate it from today's weekday, or the
# reset would move forward every Saturday and erase legitimate weekly carry-forward.
TARGET_CARRY_RESET_DATE = date(2026, 11, 2)


def _target_period(student: Student, kind: str, today: date, holidays: list[CalendarHoliday], db: Session):
    """Build weekly/monthly progress from the Dashboard's live three-year required pace.

    Carry-forward starts at zero on TARGET_CARRY_RESET_DATE. Each completed period's
    shortfall is carried into the next period; overachievement clears the shortfall.
    """
    start_date = student.journey_start_date or today
    target_date = start_date.replace(
        year=start_date.year + 3,
        day=min(start_date.day, 28) if start_date.month == 2 and start_date.day == 29 else start_date.day,
    )
    target_days = (target_date - today).days
    remaining_pages = max(0.0, float(student.total_pages or 0) - float(student.completed_pages or 0))
    required_daily = remaining_pages / target_days if remaining_pages > 0 and target_days > 0 else 0.0
    # Both weekly and monthly targets use the same six-day study calendar.
    # Friday is excluded from every target period; class/global No Class Days
    # are excluded separately below.

    start, end = _period_bounds(today, kind)
    calculation_start = max(start_date, TARGET_CARRY_RESET_DATE)
    if calculation_start > today or calculation_start > target_date:
        return {"period_start": start.isoformat(), "period_end": end.isoformat(),
                "base_target": 0, "carry_in": 0,
                "target": 0, "completed": 0,
                "remaining": 0, "working_days": 0,
                "total_working_days": 0, "status": "Not started"}

    rows = db.execute(
        select(ReadingEntry.entry_date, ReadingEntry.pages).where(
            ReadingEntry.student_id == student.id,
            ReadingEntry.entry_date >= calculation_start,
            ReadingEntry.entry_date <= today,
        )
    ).all()
    pages_by_date = {}
    for entry_day, page_value in rows:
        pages_by_date[entry_day] = pages_by_date.get(entry_day, 0.0) + reading_page_count(page_value)

    cursor = (
        calculation_start - timedelta(days=(calculation_start.weekday() - 5) % 7)
        if kind == "week" else calculation_start.replace(day=1)
    )
    carry = 0.0
    current = None
    while cursor <= end:
        if kind == "week":
            period_start, period_end = cursor, cursor + timedelta(days=5)
            next_cursor = cursor + timedelta(days=7)
        else:
            period_start = cursor
            next_cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
            period_end = next_cursor - timedelta(days=1)

        # No-class days reduce this period's required workload, not the three-year pace.
        closed_dates = {
            holiday.holiday_date for holiday in holidays
            if (not holiday.class_name or holiday.class_name == (student.class_name or "Unassigned class"))
            and period_start <= holiday.holiday_date <= period_end
        }
        # If the carry-forward reset or journey start falls mid-period, count only
        # eligible dates from that effective start. Fridays are never in this range.
        effective_start = max(period_start, calculation_start)
        eligible_start = effective_start
        # Count only Saturday–Thursday dates. Apply No Class Days to both
        # weekly and monthly periods, without double-counting Fridays.
        closed_in_target_window = sum(
            1 for closed_day in closed_dates
            if eligible_start <= closed_day <= period_end and closed_day.weekday() != 4
        )
        eligible_days = sum(
            1 for offset in range(max(0, (period_end - eligible_start).days + 1))
            if (eligible_start + timedelta(days=offset)).weekday() != 4
        )
        working_target_days = max(0, eligible_days - closed_in_target_window)
        period_base = required_daily * working_target_days
        effective_end = min(period_end, today)
        completed = sum(
            value for entry_day, value in pages_by_date.items()
            if effective_start <= entry_day <= effective_end
        ) if effective_end >= effective_start else 0.0
        carry_in = round(carry, 2)
        base_target = round(period_base, 2)
        total_target = round(base_target + carry_in, 2)
        remaining = max(0.0, total_target - completed)
        if period_start == start:
            elapsed_days = sum(
                1 for offset in range(max(0, (effective_end - effective_start).days + 1))
                if effective_end >= effective_start
                and (effective_start + timedelta(days=offset)).weekday() != 4
                and (effective_start + timedelta(days=offset)) not in closed_dates
            )
            total_days = working_target_days
            current = {
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "base_target": base_target,
                "carry_in": carry_in,
                "target": total_target,
                "completed": round(completed, 2),
                "remaining": round(remaining, 2),
                "working_days": elapsed_days,
                "total_working_days": total_days,
                "no_class_days": closed_in_target_window,
                "excluded_pages": round(required_daily * closed_in_target_window, 2),
                "status": "Met" if completed + 0.001 >= period_base + carry_in else "Pending",
            }
        carry = remaining
        cursor = next_cursor
    return current or {
        "period_start": start.isoformat(), "period_end": end.isoformat(),
        "base_target": 0, "carry_in": 0,
        "target": 0, "completed": 0,
        "remaining": 0, "working_days": 0,
        "total_working_days": 0, "status": "Pending",
    }

@app.get("/targets/summary")
def targets_summary(user: User = Depends(current_user), db: Session = Depends(get_db)):
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    holidays = db.scalars(select(CalendarHoliday).order_by(CalendarHoliday.holiday_date)).all()
    students = db.scalars(select(Student).where(Student.is_active.is_(True)).order_by(Student.name)).all()
    allowed = allowed_student_ids(user, db)
    return [{"student_id": s.id, "weekly": _target_period(s, "week", today, holidays, db), "monthly": _target_period(s, "month", today, holidays, db)} for s in students if allowed is None or s.id in allowed]


@app.get("/students/{student_id}/reading")
def get_reading(student_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    check_student_access(student_id, user, db)
    rows = db.scalars(select(ReadingEntry).where(ReadingEntry.student_id == student_id).order_by(ReadingEntry.entry_date.desc(), ReadingEntry.id.desc())).all()
    return [{"id": r.id, "date": r.entry_date.isoformat(), "start_surah": r.start_surah, "start_ayah": r.start_ayah, "end_surah": r.end_surah, "end_ayah": r.end_ayah, "recent_start_surah": r.recent_start_surah, "recent_start_ayah": r.recent_start_ayah, "recent_end_surah": r.recent_end_surah, "recent_end_ayah": r.recent_end_ayah, "general_start_surah": r.general_start_surah, "general_start_ayah": r.general_start_ayah, "general_end_surah": r.general_end_surah, "general_end_ayah": r.general_end_ayah, "new_lesson": r.new_lesson, "pages": r.pages, "recent_revision": r.recent_revision, "recent_pages": r.recent_pages or "0", "general_revision": r.general_revision, "general_pages": r.general_pages or "0", "remarks": r.remarks, "juz_progress_data": r.juz_progress_data} for r in rows]

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
    _set_reading_juz_contribution(row)
    db.flush()
    _sync_student_juz_progress(db, student_id)
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
    db.flush()
    _sync_student_juz_progress(db, student_id)
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
    _set_reading_juz_contribution(row)
    db.add(row)
    db.flush()
    _sync_student_juz_progress(db, student_id)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "student_id": row.student_id, "date": row.entry_date.isoformat()}

@app.get("/students/{student_id}/attendance/monthly-score")
def get_monthly_attendance_score(
    student_id: int,
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Calculate monthly attendance points out of 10 using recorded class working days."""
    check_student_access(student_id, user, db)
    student = db.get(Student, student_id)
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

    # Parent reports use only this child's attendance dates. Teachers retain
    # the class-working-day denominator used by the existing staff reports.
    if user.role == "parent":
        working_query = select(Attendance.attendance_date).where(
            Attendance.student_id == student_id,
            Attendance.attendance_date >= start,
            Attendance.attendance_date < end,
        )
    else:
        working_query = select(Attendance.attendance_date).join(
            Student, Student.id == Attendance.student_id
        ).where(
            Student.is_active.is_(True),
            Attendance.attendance_date >= start,
            Attendance.attendance_date < end,
        )
        if student.class_name:
            working_query = working_query.where(Student.class_name == student.class_name)
        else:
            working_query = working_query.where(Attendance.student_id == student_id)
    working_dates = set(db.scalars(working_query.distinct()).all())
    holiday_rows = db.scalars(select(CalendarHoliday).where(CalendarHoliday.holiday_date >= start, CalendarHoliday.holiday_date < end)).all()
    excluded_dates = {h.holiday_date for h in holiday_rows if not h.class_name or h.class_name == (student.class_name or "Unassigned class")}
    working_dates.difference_update(excluded_dates)

    student_rows = db.scalars(select(Attendance).where(
        Attendance.student_id == student_id,
        Attendance.attendance_date >= start,
        Attendance.attendance_date < end,
    ).order_by(Attendance.attendance_date, Attendance.period, Attendance.id)).all()
    statuses_by_date: dict[date, list[str]] = {}
    for row in student_rows:
        if row.attendance_date not in excluded_dates:
            statuses_by_date.setdefault(row.attendance_date, []).append((row.status or "").lower())

    present_days = sum(
        1 for day_statuses in statuses_by_date.values()
        if day_statuses and all(value in {"present", "late"} for value in day_statuses)
    )
    working_days = len(working_dates)
    percentage = round((present_days / working_days) * 100, 2) if working_days else 0.0
    points = round((percentage / 100) * 10, 2)
    return {
        "student_id": student_id,
        "year": year,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "attendance_percentage": percentage,
        "attendance_points": points,
        "max_points": 10,
        "basis": ("unique attendance dates recorded for this student; a day counts present only when all recorded periods are present or late" if user.role == "parent" else "unique attendance dates recorded for the student's class; a day counts present only when all recorded periods are present or late"),
    }


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
    student = db.get(Student, student_id)
    no_class = db.scalar(select(CalendarHoliday).where(CalendarHoliday.holiday_date == day).limit(1))
    if no_class and (not no_class.class_name or no_class.class_name == (student.class_name or "Unassigned class")):
        raise HTTPException(status_code=409, detail="No class is scheduled for this date: " + (no_class.reason or no_class.category or "No class"))
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
def challenge_leaderboard(year: int = Query(default=date.today().year, ge=2000, le=2100), month: int = Query(default=date.today().month, ge=1, le=12), user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Show confirmed challenge marks for the selected month; preserve all older sessions as history."""
    month_start = date(year, month, 1)
    month_end = (date(year + 1, 1, 1) - timedelta(days=1)) if month == 12 else (date(year, month + 1, 1) - timedelta(days=1))
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
        "id": row.id, "date": row.exam_date.isoformat(), "exam_type": row.exam_type or "monthly",
        "start_juz": row.start_juz, "end_juz": row.end_juz,
        "monthly_source": row.monthly_source or "new_lesson", "start_page": row.start_page, "end_page": row.end_page,
        "confirmed": row.confirmed, "total_marks": row.total_marks,
        "questions": [{
            "text": q.question_text, "expected": q.expected_answer or "",
            "max_marks": q.max_marks, "awarded_marks": q.awarded_marks,
            "note": q.teacher_note or ""
        } for q in row.questions]
    }

@app.get("/students/{student_id}/exam/monthly-learning")
def exam_monthly_learning(
    student_id: int,
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Return only New Lesson ranges entered for the selected calendar month."""
    _challenge_student(student_id, user, db)
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    rows = db.scalars(select(ReadingEntry).where(
        ReadingEntry.student_id == student_id,
        ReadingEntry.entry_date >= start,
        ReadingEntry.entry_date < end,
        ReadingEntry.start_surah.is_not(None),
        ReadingEntry.start_ayah.is_not(None),
        ReadingEntry.end_surah.is_not(None),
        ReadingEntry.end_ayah.is_not(None),
    ).order_by(ReadingEntry.entry_date, ReadingEntry.id)).all()
    return [{
        "id": row.id, "date": row.entry_date.isoformat(),
        "start_surah": row.start_surah, "start_ayah": row.start_ayah,
        "end_surah": row.end_surah, "end_ayah": row.end_ayah,
        "pages": row.pages or "0", "new_lesson": row.new_lesson or "",
    } for row in rows]

@app.get("/students/{student_id}/exam/monthly-pages")
def exam_monthly_pages(
    student_id: int,
    start_page: int = Query(ge=1, le=604),
    end_page: int = Query(ge=1, le=604),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Return the Quran ayah coverage for a standard 604-page Mushaf range."""
    _challenge_student(student_id, user, db)
    if end_page < start_page:
        raise HTTPException(status_code=422, detail="End page must be greater than or equal to Start page.")
    return {"start_page": start_page, "end_page": end_page, "ayah_count": sum(
        end - start + 1 for page, start, end in _QURAN_PAGE_INTERVALS if start_page <= page <= end_page
    )}

@app.get("/students/{student_id}/exam/sessions")
def exam_sessions(student_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _challenge_student(student_id, user, db)
    rows = db.scalars(select(ExamSession).where(ExamSession.student_id == student_id).order_by(ExamSession.exam_date.desc(), ExamSession.id.desc())).all()
    return [_exam_json(row) for row in rows]

@app.post("/students/{student_id}/exam/generate")
def generate_exam(student_id: int, data: ExamGenerateInput, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    _challenge_student(student_id, user, db)
    if data.exam_type == "monthly":
        if data.date.year != data.year or data.date.month != data.month:
            raise HTTPException(status_code=422, detail="Exam date must be within the selected Monthly Exam month.")
    row = db.scalar(select(ExamSession).where(
        ExamSession.student_id == student_id,
        ExamSession.exam_date == data.date,
        ExamSession.exam_type == data.exam_type,
    ).order_by(ExamSession.id.desc()))
    if row and row.confirmed:
        raise HTTPException(status_code=409, detail="This exam is confirmed. Create a new exam date to generate another.")

    refs_by_key = {}
    if data.exam_type == "monthly":
        if data.monthly_source in ("new_lesson", "both"):
            month_start = date(data.year, data.month, 1)
            month_end = date(data.year + 1, 1, 1) if data.month == 12 else date(data.year, data.month + 1, 1)
            lessons = db.scalars(select(ReadingEntry).where(
                ReadingEntry.student_id == student_id,
                ReadingEntry.entry_date >= month_start,
                ReadingEntry.entry_date < month_end,
                ReadingEntry.start_surah.is_not(None),
                ReadingEntry.start_ayah.is_not(None),
                ReadingEntry.end_surah.is_not(None),
                ReadingEntry.end_ayah.is_not(None),
            ).order_by(ReadingEntry.entry_date, ReadingEntry.id)).all()
            for lesson in lessons:
                first = (lesson.start_surah, lesson.start_ayah)
                last = (lesson.end_surah, lesson.end_ayah)
                lower, upper = sorted((first, last))
                for surah_no in range(lower[0], upper[0] + 1):
                    for ref in _surah_ayah_refs(surah_no):
                        key = (ref["surah"], ref["ayah"])
                        if lower <= key <= upper:
                            refs_by_key[key] = (ref, f"New Lesson {lesson.entry_date.isoformat()}")
            if data.monthly_source == "new_lesson" and not refs_by_key:
                raise HTTPException(status_code=400, detail="No New Lesson ranges were recorded for this student in the selected month. Revision entries are not used.")
        if data.monthly_source in ("page_range", "both"):
            if data.start_page is None or data.end_page is None or data.end_page < data.start_page:
                raise HTTPException(status_code=422, detail="Select a valid Quran page range (1–604).")
            first_interval = next((x for x in _QURAN_PAGE_INTERVALS if x[0] == data.start_page), None)
            last_interval = next((x for x in _QURAN_PAGE_INTERVALS if x[0] == data.end_page), None)
            if not first_interval or not last_interval:
                raise HTTPException(status_code=422, detail="Quran page range is not available in the page map.")
            first_ordinal, last_ordinal = first_interval[1], last_interval[2]
            cumulative = 0
            for surah_no, ayah_count in enumerate(SURAH_AYAH_COUNTS, start=1):
                surah_start, surah_end = cumulative, cumulative + ayah_count - 1
                if surah_end >= first_ordinal and surah_start <= last_ordinal:
                    for ref in _surah_ayah_refs(surah_no):
                        ordinal = surah_start + ref["ayah"] - 1
                        if first_ordinal <= ordinal <= last_ordinal:
                            key = (ref["surah"], ref["ayah"])
                            refs_by_key[key] = (ref, f"Pages {data.start_page}–{data.end_page}")
                cumulative += ayah_count
        if not refs_by_key:
            raise HTTPException(status_code=400, detail="No valid Quran ayahs were found in the selected monthly exam source.")
    else:
        start_juz = data.juz_no if data.exam_type == "juz" else data.start_juz
        end_juz = data.juz_no if data.exam_type == "juz" else data.end_juz
        juz_numbers = list(range(start_juz, end_juz + 1))
        saved_ranges = db.scalars(select(ChallengeRange).where(ChallengeRange.student_id == student_id)).all()
        saved_juz = {j for r in saved_ranges if r.start_juz and r.end_juz for j in range(r.start_juz, r.end_juz + 1)}
        missing = [j for j in juz_numbers if j not in saved_juz]
        if missing:
            raise HTTPException(status_code=400, detail="Selected Juz range is not present in the student's saved Learning Range: " + ", ".join(map(str, missing)))
        for juz_no in juz_numbers:
            for ref in _juz_ayah_refs(juz_no):
                refs_by_key[(ref["surah"], ref["ayah"])] = (ref, f"Juz {juz_no}")
        if not refs_by_key:
            raise HTTPException(status_code=400, detail="No ayahs found in the selected Juz range.")

    refs = list(refs_by_key.values())
    if len(refs) < data.question_count:
        raise HTTPException(status_code=400, detail=f"Only {len(refs)} unique ayahs are available in the selected range. Reduce the question count to {len(refs)} or fewer.")
    # Keep generated questions at least half a Mushaf page apart.
    # Convert each ayah's global ordinal to a fractional page coordinate so
    # spacing works consistently across New Lesson, page-range, and Juz exams.
    def _ayah_page_position(ref):
        ordinal = _ayah_ordinal(int(ref["surah"]), int(ref["ayah"]))
        for page_no, page_start, page_end in _QURAN_PAGE_INTERVALS:
            if page_start <= ordinal <= page_end:
                ayah_count = page_end - page_start + 1
                return page_no + ((ordinal - page_start) + 0.5) / ayah_count
        return None

    rng = random.SystemRandom()
    shuffled_refs = list(refs)
    rng.shuffle(shuffled_refs)
    chosen = []
    chosen_positions = []
    for candidate in shuffled_refs:
        position = _ayah_page_position(candidate[0])
        if position is None:
            continue
        if all(abs(position - existing) >= 0.5 for existing in chosen_positions):
            chosen.append(candidate)
            chosen_positions.append(position)
            if len(chosen) == data.question_count:
                break
    if len(chosen) < data.question_count:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Only {len(chosen)} questions can be generated with at least "
                f"half-page spacing in this selected range. Reduce the question "
                f"count to {len(chosen)} or expand the selected range."
            ),
        )
    if row:
        row.questions.clear()
        db.flush()
        row.confirmed = False
        row.total_marks = 0
    else:
        row = ExamSession(student_id=student_id, exam_date=data.date, exam_type=data.exam_type,
                          start_juz=(data.juz_no if data.exam_type == "juz" else data.start_juz),
                          end_juz=(data.juz_no if data.exam_type == "juz" else data.end_juz),
                          monthly_source=data.monthly_source, start_page=data.start_page, end_page=data.end_page,
                          confirmed=False, total_marks=0)
        db.add(row)
        db.flush()
    row.exam_type = data.exam_type
    row.start_juz = data.juz_no if data.exam_type == "juz" else data.start_juz
    row.end_juz = data.juz_no if data.exam_type == "juz" else data.end_juz
    row.monthly_source = data.monthly_source if data.exam_type == "monthly" else "new_lesson"
    row.start_page = data.start_page if data.exam_type == "monthly" else None
    row.end_page = data.end_page if data.exam_type == "monthly" else None
    for idx, (ref, scope_label) in enumerate(chosen, start=1):
        row.questions.append(ExamQuestion(
            question_no=idx, question_text=ref["text"],
            expected_answer=f"Surah {ref['surah']}: {ref['surah_name']} {ref['ayah']} · {scope_label}",
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
    if data.session_id is not None:
        row = db.scalar(select(ExamSession).where(ExamSession.id == data.session_id, ExamSession.student_id == student_id))
        if row is None or row.exam_date != exam_date or row.exam_type != data.exam_type:
            raise HTTPException(status_code=404, detail="Exam history record not found for editing.")
    else:
        row = db.scalar(select(ExamSession).where(ExamSession.student_id == student_id, ExamSession.exam_date == exam_date, ExamSession.exam_type == data.exam_type).order_by(ExamSession.id.desc()))
    if row is None:
        row = ExamSession(student_id=student_id, exam_date=exam_date, exam_type=data.exam_type, start_juz=(data.juz_no if data.exam_type == "juz" else data.start_juz), end_juz=(data.juz_no if data.exam_type == "juz" else data.end_juz), monthly_source=data.monthly_source, start_page=data.start_page, end_page=data.end_page)
        db.add(row)
        db.flush()
    if row.confirmed and not data.allow_confirmed_edit:
        raise HTTPException(status_code=409, detail="Confirmed exam marks require the explicit Edit action.")
    row.exam_type = data.exam_type
    row.start_juz = data.juz_no if data.exam_type == "juz" else data.start_juz
    row.end_juz = data.juz_no if data.exam_type == "juz" else data.end_juz
    row.monthly_source = data.monthly_source if data.exam_type == "monthly" else "new_lesson"
    row.start_page = data.start_page if data.exam_type == "monthly" else None
    row.end_page = data.end_page if data.exam_type == "monthly" else None
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

@app.delete("/students/{student_id}/exam/sessions/{exam_id}")
def delete_exam_session(student_id: int, exam_id: int, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    _challenge_student(student_id, user, db)
    row = db.scalar(select(ExamSession).where(ExamSession.id == exam_id, ExamSession.student_id == student_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Exam history record not found.")
    db.delete(row)
    db.commit()
    return {"deleted": True, "id": exam_id}

_SURAH_AYAH_CACHE: dict[int, list[dict]] = {}

def _surah_ayah_refs(surah_no: int) -> list[dict]:
    """Fetch verified Arabic ayah text and references for one Surah."""
    if surah_no not in _SURAH_AYAH_CACHE:
        try:
            with urlopen(f"https://api.alquran.cloud/v1/surah/{surah_no}/quran-uthmani", timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("code") != 200 or not isinstance(payload.get("data", {}).get("ayahs"), list):
                raise ValueError("Unexpected Quran API response")
            surah = payload["data"]
            _SURAH_AYAH_CACHE[surah_no] = [
                {"surah": int(surah_no), "surah_name": str(surah.get("englishName", "")),
                 "ayah": int(a["numberInSurah"]), "text": str(a["text"]).strip()}
                for a in surah["ayahs"] if a.get("numberInSurah") and a.get("text")
            ]
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=502, detail=f"Could not load verified Quran data for Surah {surah_no}. Please retry.") from exc
    return _SURAH_AYAH_CACHE[surah_no]


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



@app.get("/teacher/reports")
def teacher_reports(user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Teacher-only consolidated reporting data. Parent accounts cannot access this endpoint."""
    students = db.scalars(select(Student).where(Student.is_active.is_(True)).order_by(Student.name)).all()
    student_ids = [s.id for s in students]
    if not student_ids:
        return {"students": [], "reading": [], "attendance": [], "marks": [], "exams": [], "challenges": [], "discipline": [], "character": [], "notifications": []}
    reading = db.scalars(select(ReadingEntry).where(ReadingEntry.student_id.in_(student_ids)).order_by(ReadingEntry.entry_date.desc(), ReadingEntry.id.desc())).all()
    attendance = db.scalars(select(Attendance).where(Attendance.student_id.in_(student_ids)).order_by(Attendance.attendance_date.desc(), Attendance.period)).all()
    marks = db.scalars(select(DailyMark).where(DailyMark.student_id.in_(student_ids)).order_by(DailyMark.mark_date.desc())).all()
    exams = db.scalars(select(ExamSession).where(ExamSession.student_id.in_(student_ids)).order_by(ExamSession.exam_date.desc(), ExamSession.id.desc())).all()
    challenges = db.scalars(select(ChallengeSession).where(ChallengeSession.student_id.in_(student_ids)).order_by(ChallengeSession.challenge_date.desc())).all()
    discipline = db.scalars(select(DisciplineEntry).where(DisciplineEntry.student_id.in_(student_ids)).order_by(DisciplineEntry.incident_date.desc())).all()
    character = db.scalars(select(MonthlyCharacterPoints).where(MonthlyCharacterPoints.student_id.in_(student_ids)).order_by(MonthlyCharacterPoints.year.desc(), MonthlyCharacterPoints.month.desc())).all()
    notifications = db.scalars(select(ParentNotification).where(ParentNotification.student_id.in_(student_ids)).order_by(ParentNotification.created_at.desc())).all()
    return {
        "students": [{"id": s.id, "name": s.name, "class_name": s.class_name or "Unassigned class", "student_code": s.student_code, "completed_pages": s.completed_pages, "total_pages": s.total_pages} for s in students],
        "reading": [{"student_id": r.student_id, "date": r.entry_date.isoformat(), "new_lesson": r.new_lesson or "", "pages": r.pages or "0", "recent_revision": r.recent_revision or "", "recent_pages": r.recent_pages or "0", "general_revision": r.general_revision or "", "general_pages": r.general_pages or "0", "start_surah": r.start_surah, "start_ayah": r.start_ayah, "end_surah": r.end_surah, "end_ayah": r.end_ayah, "recent_start_surah": r.recent_start_surah, "recent_start_ayah": r.recent_start_ayah, "recent_end_surah": r.recent_end_surah, "recent_end_ayah": r.recent_end_ayah, "general_start_surah": r.general_start_surah, "general_start_ayah": r.general_start_ayah, "general_end_surah": r.general_end_surah, "general_end_ayah": r.general_end_ayah, "remarks": r.remarks} for r in reading],
        "attendance": [{"student_id": r.student_id, "date": r.attendance_date.isoformat(), "period": r.period, "status": r.status, "remarks": r.remarks or ""} for r in attendance],
        "marks": [{"student_id": r.student_id, "date": r.mark_date.isoformat(), "points": r.points, "s": r.score_s, "ms": r.score_ms, "mu": r.score_mu, "remarks": r.remarks or ""} for r in marks],
        "exams": [{"student_id": r.student_id, **_exam_json(r)} for r in exams],
        "challenges": [{"student_id": r.student_id, "date": r.challenge_date.isoformat(), "confirmed": r.confirmed, "score": r.score, "q": [{"text": q.question_text, "review": q.review_score, "submitted": q.submitted} for q in r.questions]} for r in challenges],
        "discipline": [{"student_id": r.student_id, "incident_date": r.incident_date.isoformat(), "reason": r.reason, "points_deducted": r.points_deducted, "is_reversed": r.is_reversed, "notes": r.notes or ""} for r in discipline],
        "character": [{"student_id": r.student_id, "year": r.year, "month": r.month, "cleanliness_points": r.cleanliness_points, "discipline_points": r.discipline_points, "worship_points": r.worship_points} for r in character],
        "notifications": [{"student_id": r.student_id, "title": r.title, "type": r.notification_type, "created_at": r.created_at.isoformat(), "read": bool(r.read_at)} for r in notifications],
    }
