from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.config.database import Base


class DpBudget(Base):
    """Research-preset total epsilon; spent is cumulative and never reset."""
    __tablename__ = 'dp_budgets'
    id: Mapped[int] = mapped_column(primary_key=True)
    study_id: Mapped[int] = mapped_column(ForeignKey('grade_studies.id'), unique=True)
    total_epsilon_micros: Mapped[int]
    spent_epsilon_micros: Mapped[int] = mapped_column(default=0)
    preset_by: Mapped[str] = mapped_column(String(160), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DpPublication(Base):
    """One charged noisy release per (study, frozen input, epsilon)."""
    __tablename__ = 'dp_publications'
    id: Mapped[int] = mapped_column(primary_key=True)
    study_id: Mapped[int] = mapped_column(ForeignKey('grade_studies.id'))
    fingerprint: Mapped[str] = mapped_column(String(64))
    epsilon_micros: Mapped[int]
    status: Mapped[str] = mapped_column(String(20), default='reserved')
    noise_seed: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(600), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('study_id', 'fingerprint', 'epsilon_micros'),)


class DpReleaseName(Base):
    """A publication may be requested under several names without new charge."""
    __tablename__ = 'dp_release_names'
    id: Mapped[int] = mapped_column(primary_key=True)
    publication_id: Mapped[int] = mapped_column(ForeignKey('dp_publications.id'))
    name: Mapped[str] = mapped_column(String(140), unique=True)
    requested_by: Mapped[str] = mapped_column(String(160), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
