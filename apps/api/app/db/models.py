from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base
def now(): return datetime.now(timezone.utc)
def uid(): return str(uuid4())
class AppSettings(Base):
    __tablename__="app_settings"; id: Mapped[int]=mapped_column(Integer,primary_key=True,default=1)
    monthly_confirmed_commission_goal_cents: Mapped[int]=mapped_column(Integer,default=100000); daily_publication_limit: Mapped[int]=mapped_column(Integer,default=20); timezone: Mapped[str]=mapped_column(String(64),default="America/Sao_Paulo")
    system_automation_enabled: Mapped[bool]=mapped_column(Boolean,default=True); radar_enabled: Mapped[bool]=mapped_column(Boolean,default=False); creative_enabled: Mapped[bool]=mapped_column(Boolean,default=False); publishing_enabled: Mapped[bool]=mapped_column(Boolean,default=False); comment_reply_enabled: Mapped[bool]=mapped_column(Boolean,default=False); external_intelligence_enabled: Mapped[bool]=mapped_column(Boolean,default=False); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)
class Approval(Base):
    __tablename__="approvals"; id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); type: Mapped[str]=mapped_column(String(24)); status: Mapped[str]=mapped_column(String(24),default="PENDING"); title: Mapped[str]=mapped_column(String(200)); description: Mapped[str]=mapped_column(Text); entity_type: Mapped[str|None]=mapped_column(String(80)); entity_id: Mapped[str|None]=mapped_column(String(36)); requested_payload: Mapped[dict|None]=mapped_column(JSON); decided_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); decision_reason: Mapped[str|None]=mapped_column(Text); is_demo: Mapped[bool]=mapped_column(Boolean,default=False); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)
class Notification(Base):
    __tablename__="notifications"; id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); type: Mapped[str]=mapped_column(String(80)); severity: Mapped[str]=mapped_column(String(24)); title: Mapped[str]=mapped_column(String(200)); message: Mapped[str]=mapped_column(Text); is_read: Mapped[bool]=mapped_column(Boolean,default=False); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now); read_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); metadata_: Mapped[dict|None]=mapped_column("metadata",JSON); is_demo: Mapped[bool]=mapped_column(Boolean,default=False)
class AgentTask(Base):
    __tablename__="agent_tasks"; id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); type: Mapped[str]=mapped_column(String(80)); status: Mapped[str]=mapped_column(String(24),default="PENDING"); title: Mapped[str]=mapped_column(String(200)); payload: Mapped[dict|None]=mapped_column(JSON); result: Mapped[dict|None]=mapped_column(JSON); error: Mapped[str|None]=mapped_column(Text); is_automatic: Mapped[bool]=mapped_column(Boolean,default=False); is_demo: Mapped[bool]=mapped_column(Boolean,default=False); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now); started_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); finished_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)
class DecisionLog(Base):
    __tablename__="decision_logs"; id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); timestamp: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now); actor: Mapped[str]=mapped_column(String(80)); entity_type: Mapped[str]=mapped_column(String(80)); entity_id: Mapped[str|None]=mapped_column(String(36)); action: Mapped[str]=mapped_column(String(120)); reason: Mapped[str|None]=mapped_column(Text); confidence: Mapped[str|None]=mapped_column(String(24)); metadata_: Mapped[dict|None]=mapped_column("metadata",JSON); is_demo: Mapped[bool]=mapped_column(Boolean,default=False)


class MarketplaceConnection(Base):
    __tablename__ = "marketplace_connections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    provider: Mapped[str] = mapped_column(String(40), unique=True)
    site_id: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="NOT_CONFIGURED")
    auth_mode: Mapped[str] = mapped_column(String(24), default="ANONYMOUS")
    external_account_id: Mapped[str | None] = mapped_column(String(80))
    external_nickname: Mapped[str | None] = mapped_column(String(120))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class MarketplaceCapability(Base):
    __tablename__ = "marketplace_capabilities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    provider: Mapped[str] = mapped_column(String(40))
    capability_key: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(24), default="UNKNOWN")
    endpoint: Mapped[str | None] = mapped_column(String(300))
    http_method: Mapped[str | None] = mapped_column(String(12))
    last_http_status: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    reason_code: Mapped[str | None] = mapped_column(String(80))
    message: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
