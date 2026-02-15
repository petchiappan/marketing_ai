"""SQLAlchemy ORM models for all database tables."""

import uuid
from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Declarative base for all models."""
    pass


# ---------------------------------------------------------------------------
# Stage 1 – Raw Input
# ---------------------------------------------------------------------------

class EnrichmentRequest(Base):
    __tablename__ = "enrichment_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_name = Column(String(500), nullable=False)
    source = Column(String(50), nullable=False)
    salesforce_lead_id = Column(String(18), nullable=True)
    additional_fields = Column(JSONB, default=dict)
    status = Column(String(30), nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    requested_by = Column(String(255), nullable=True)

    # Relationships
    contact_results = relationship("ContactResult", back_populates="request", cascade="all, delete-orphan")
    news_results = relationship("NewsResult", back_populates="request", cascade="all, delete-orphan")
    financial_results = relationship("FinancialResult", back_populates="request", cascade="all, delete-orphan")
    enriched_lead = relationship("EnrichedLead", back_populates="request", uselist=False, cascade="all, delete-orphan")
    audit_logs = relationship("EnrichmentAuditLog", back_populates="request", cascade="all, delete-orphan")
    token_usages = relationship("LLMTokenUsage", back_populates="request")
    agent_runs = relationship("AgentRun", back_populates="request", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("source IN ('salesforce','web_form','api')", name="ck_requests_source"),
        CheckConstraint("status IN ('pending','processing','completed','failed','partial')", name="ck_requests_status"),
        Index("idx_requests_status", "status"),
        Index("idx_requests_company", "company_name"),
    )


# ---------------------------------------------------------------------------
# Stage 2 – Individual Agent Outputs
# ---------------------------------------------------------------------------

class ContactResult(Base):
    __tablename__ = "contact_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("enrichment_requests.id", ondelete="CASCADE"), nullable=False)
    source_tool = Column(String(50), nullable=False)
    full_name = Column(String(300))
    job_title = Column(String(300))
    email = Column(String(500))
    phone = Column(String(100))
    linkedin_url = Column(String(1000))
    company_name = Column(String(500))
    confidence_score = Column(Numeric(3, 2))
    raw_response = Column(JSONB)
    fetched_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    processing_time_ms = Column(Integer)
    error_message = Column(Text)

    request = relationship("EnrichmentRequest", back_populates="contact_results")

    __table_args__ = (
        CheckConstraint("source_tool IN ('lusha','apollo','signal_hire')", name="ck_contact_source"),
        CheckConstraint("confidence_score BETWEEN 0 AND 1", name="ck_contact_confidence"),
        Index("idx_contact_request", "request_id"),
    )


class NewsResult(Base):
    __tablename__ = "news_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("enrichment_requests.id", ondelete="CASCADE"), nullable=False)
    source_tool = Column(String(100), nullable=False)
    headline = Column(Text)
    summary = Column(Text)
    url = Column(String(2000))
    published_date = Column(Date)
    sentiment = Column(String(20))
    relevance_score = Column(Numeric(3, 2))
    category = Column(String(100))
    raw_response = Column(JSONB)
    fetched_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    processing_time_ms = Column(Integer)
    error_message = Column(Text)

    request = relationship("EnrichmentRequest", back_populates="news_results")

    __table_args__ = (
        CheckConstraint("sentiment IN ('positive','negative','neutral','mixed')", name="ck_news_sentiment"),
        CheckConstraint("relevance_score BETWEEN 0 AND 1", name="ck_news_relevance"),
        Index("idx_news_request", "request_id"),
    )


class FinancialResult(Base):
    __tablename__ = "financial_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("enrichment_requests.id", ondelete="CASCADE"), nullable=False)
    source_tool = Column(String(100), nullable=False)
    revenue = Column(Numeric(18, 2))
    revenue_currency = Column(String(3), default="USD")
    employee_count = Column(Integer)
    funding_total = Column(Numeric(18, 2))
    funding_round = Column(String(50))
    market_cap = Column(Numeric(18, 2))
    industry = Column(String(200))
    fiscal_year = Column(Integer)
    headquarters = Column(String(500))
    confidence_score = Column(Numeric(3, 2))
    raw_response = Column(JSONB)
    fetched_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    processing_time_ms = Column(Integer)
    error_message = Column(Text)

    request = relationship("EnrichmentRequest", back_populates="financial_results")

    __table_args__ = (
        CheckConstraint("confidence_score BETWEEN 0 AND 1", name="ck_financial_confidence"),
        Index("idx_financial_request", "request_id"),
    )


# ---------------------------------------------------------------------------
# Stage 3 – Aggregated Enriched Data
# ---------------------------------------------------------------------------

class EnrichedLead(Base):
    __tablename__ = "enriched_leads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("enrichment_requests.id", ondelete="CASCADE"), nullable=False, unique=True)

    # Company info
    company_name = Column(String(500), nullable=False)
    industry = Column(String(200))
    headquarters = Column(String(500))
    employee_count = Column(Integer)
    website = Column(String(1000))

    # Contacts
    contacts = Column(JSONB, default=list)

    # Financial
    revenue = Column(Numeric(18, 2))
    revenue_currency = Column(String(3), default="USD")
    funding_total = Column(Numeric(18, 2))
    latest_funding_round = Column(String(50))
    market_cap = Column(Numeric(18, 2))

    # News
    recent_news = Column(JSONB, default=list)
    news_sentiment_overall = Column(String(20))

    # Quality
    overall_confidence = Column(Numeric(3, 2))
    sources_used = Column(JSONB, default=list)
    enrichment_summary = Column(Text)

    # Salesforce sync
    salesforce_synced = Column(Boolean, default=False)
    salesforce_sync_at = Column(DateTime(timezone=True))
    salesforce_sync_error = Column(Text)

    # Lineage
    contact_agent_status = Column(String(20), default="pending")
    news_agent_status = Column(String(20), default="pending")
    financial_agent_status = Column(String(20), default="pending")
    aggregation_started_at = Column(DateTime(timezone=True))
    aggregation_completed_at = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    request = relationship("EnrichmentRequest", back_populates="enriched_lead")

    __table_args__ = (
        Index("idx_enriched_request", "request_id"),
        Index("idx_enriched_sf_sync", "salesforce_synced"),
    )


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------

class EnrichmentAuditLog(Base):
    __tablename__ = "enrichment_audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("enrichment_requests.id", ondelete="CASCADE"), nullable=False)
    stage = Column(String(20), nullable=False)
    agent_name = Column(String(50))
    action = Column(String(50), nullable=False)
    details = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    request = relationship("EnrichmentRequest", back_populates="audit_logs")

    __table_args__ = (
        Index("idx_audit_request", "request_id"),
    )


# ---------------------------------------------------------------------------
# Admin – Authentication
# ---------------------------------------------------------------------------

class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=True)
    email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=True)
    auth_provider = Column(String(20), nullable=False, default="local")
    azure_oid = Column(String(255), nullable=True)
    display_name = Column(String(255), nullable=True)
    role = Column(String(20), nullable=False, default="viewer")
    is_active = Column(Boolean, nullable=False, default=True)
    last_login_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("auth_provider IN ('local','azure_ad')", name="ck_admin_auth_provider"),
        CheckConstraint("role IN ('admin','editor','viewer')", name="ck_admin_role"),
        Index("idx_admin_users_email", "email"),
    )


# ---------------------------------------------------------------------------
# Admin – Tool Configuration
# ---------------------------------------------------------------------------

class ToolConfig(Base):
    __tablename__ = "tool_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tool_name = Column(String(50), nullable=False, unique=True)
    display_name = Column(String(100), nullable=False)
    base_url = Column(String(1000))
    api_key_encrypted = Column(Text)
    auth_type = Column(String(30), default="api_key")
    extra_headers = Column(JSONB, default=dict)
    extra_config = Column(JSONB, default=dict)
    is_enabled = Column(Boolean, nullable=False, default=True)
    health_status = Column(String(20), default="unknown")
    last_health_check = Column(DateTime(timezone=True))
    updated_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    rate_limit = relationship("ProviderRateLimit", back_populates="tool", uselist=False)

    __table_args__ = (
        CheckConstraint("auth_type IN ('api_key','oauth2','basic','bearer')", name="ck_tool_auth_type"),
        CheckConstraint("health_status IN ('healthy','degraded','down','unknown')", name="ck_tool_health"),
    )


# ---------------------------------------------------------------------------
# Admin – Rate Limits
# ---------------------------------------------------------------------------

class ProviderRateLimit(Base):
    __tablename__ = "provider_rate_limits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_name = Column(String(50), ForeignKey("tool_configs.tool_name"), nullable=False, unique=True)
    requests_per_min = Column(Integer, nullable=False, default=60)
    burst_limit = Column(Integer, nullable=False, default=10)
    daily_quota = Column(Integer, nullable=True)
    is_enabled = Column(Boolean, nullable=False, default=True)
    updated_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    tool = relationship("ToolConfig", back_populates="rate_limit")


# ---------------------------------------------------------------------------
# Admin – LLM Token Usage
# ---------------------------------------------------------------------------

class LLMTokenUsage(Base):
    __tablename__ = "llm_token_usage"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("enrichment_requests.id", ondelete="SET NULL"), nullable=True)
    agent_name = Column(String(50), nullable=False)
    model_name = Column(String(100), nullable=False)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    estimated_cost_usd = Column(Numeric(10, 6))
    latency_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    request = relationship("EnrichmentRequest", back_populates="token_usages")

    __table_args__ = (
        Index("idx_token_usage_request", "request_id"),
        Index("idx_token_usage_agent", "agent_name"),
        Index("idx_token_usage_date", "created_at"),
    )


# ---------------------------------------------------------------------------
# Admin – Agent Runs
# ---------------------------------------------------------------------------

class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("enrichment_requests.id", ondelete="CASCADE"), nullable=False)
    agent_name = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default="queued")
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    duration_ms = Column(Integer)
    input_summary = Column(Text)
    output_summary = Column(Text)
    error_type = Column(String(100))
    error_message = Column(Text)
    error_traceback = Column(Text)
    retry_count = Column(Integer, default=0)
    metadata_ = Column("metadata", JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    request = relationship("EnrichmentRequest", back_populates="agent_runs")

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','completed','failed','timeout','cancelled')",
            name="ck_agent_run_status",
        ),
        Index("idx_agent_runs_request", "request_id"),
        Index("idx_agent_runs_status", "status"),
        Index("idx_agent_runs_agent", "agent_name"),
        Index("idx_agent_runs_created", "created_at"),
    )
