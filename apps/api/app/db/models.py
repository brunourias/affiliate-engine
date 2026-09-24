from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
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

class PublicationConnection(Base):
    __tablename__="publication_connections"
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid);channel:Mapped[str]=mapped_column(String(32),unique=True);connector:Mapped[str]=mapped_column(String(80));status:Mapped[str]=mapped_column(String(40),default="NOT_CONFIGURED")
    account_display_name:Mapped[str|None]=mapped_column(String(200));account_id:Mapped[str|None]=mapped_column(String(120));account_type:Mapped[str|None]=mapped_column(String(32));username:Mapped[str|None]=mapped_column(String(120));scopes:Mapped[list]=mapped_column(JSON,default=list)
    issued_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True));expires_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True));refresh_supported:Mapped[bool]=mapped_column(Boolean,default=False);last_validated_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True));auth_profile:Mapped[str]=mapped_column(String(100));token_store_reference:Mapped[str|None]=mapped_column(String(200));created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now);updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)

class OAuthState(Base):
    __tablename__="oauth_states"
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid);state_hash:Mapped[str]=mapped_column(String(64),unique=True);provider:Mapped[str]=mapped_column(String(32));created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now);expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True));used_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True));return_path:Mapped[str|None]=mapped_column(String(500))


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
    __table_args__ = (UniqueConstraint("provider", "capability_key", name="uq_marketplace_capability_provider_key"),)
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


class MarketplaceCategory(Base):
    __tablename__ = "marketplace_categories"
    __table_args__ = (UniqueConstraint("provider", "external_category_id", name="uq_marketplace_category_provider_external"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    provider: Mapped[str] = mapped_column(String(40))
    site_id: Mapped[str] = mapped_column(String(16))
    external_category_id: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    parent_external_category_id: Mapped[str | None] = mapped_column(String(80))
    source_capability: Mapped[str] = mapped_column(String(60))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class RadarRun(Base):
    __tablename__ = "radar_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    provider: Mapped[str] = mapped_column(String(40))
    site_id: Mapped[str] = mapped_column(String(16))
    trigger_type: Mapped[str] = mapped_column(String(20), default="MANUAL")
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    requested_category_id: Mapped[str | None] = mapped_column(String(80))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sources_requested: Mapped[list] = mapped_column(JSON, default=list)
    sources_succeeded: Mapped[list] = mapped_column(JSON, default=list)
    sources_failed: Mapped[list] = mapped_column(JSON, default=list)
    discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class RadarSignal(Base):
    __tablename__ = "radar_signals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    radar_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("radar_runs.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(40))
    site_id: Mapped[str] = mapped_column(String(16))
    source_type: Mapped[str] = mapped_column(String(40))
    source_capability: Mapped[str] = mapped_column(String(60))
    category_external_id: Mapped[str | None] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(30))
    external_id: Mapped[str | None] = mapped_column(String(120))
    display_text: Mapped[str | None] = mapped_column(String(500))
    rank: Mapped[int | None] = mapped_column(Integer)
    source_payload: Mapped[dict | None] = mapped_column(JSON)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class CuratorCandidate(Base):
    __tablename__ = "curator_candidates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    provider: Mapped[str] = mapped_column(String(40)); site_id: Mapped[str|None] = mapped_column(String(16))
    source_type: Mapped[str] = mapped_column(String(24)); source_radar_signal_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("radar_signals.id")); source_radar_run_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("radar_runs.id"))
    entity_type: Mapped[str] = mapped_column(String(24)); external_id: Mapped[str|None] = mapped_column(String(120)); category_external_id: Mapped[str|None] = mapped_column(String(80)); source_display_text: Mapped[str|None] = mapped_column(String(500))
    working_title: Mapped[str|None] = mapped_column(String(300)); source_url: Mapped[str|None] = mapped_column(String(1000)); notes: Mapped[str|None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="NEW"); evidence_status: Mapped[str] = mapped_column(String(32), default="INSUFFICIENT_EVIDENCE"); evidence_level: Mapped[str] = mapped_column(String(32), default="NONE")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now); last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now); stale_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True)); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now); updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class CuratorEvidence(Base):
    __tablename__ = "curator_evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid); candidate_id: Mapped[str] = mapped_column(String(36), ForeignKey("curator_candidates.id", ondelete="CASCADE"))
    evidence_type: Mapped[str] = mapped_column(String(40)); value_text: Mapped[str|None] = mapped_column(Text); value_number: Mapped[int|None] = mapped_column(Integer); value_cents: Mapped[int|None] = mapped_column(Integer); value_json: Mapped[dict|None] = mapped_column(JSON)
    source_kind: Mapped[str] = mapped_column(String(32)); source_name: Mapped[str|None] = mapped_column(String(200)); source_url: Mapped[str|None] = mapped_column(String(1000)); source_reference: Mapped[str|None] = mapped_column(String(300))
    confidence: Mapped[str] = mapped_column(String(16), default="MEDIUM"); verification_status: Mapped[str] = mapped_column(String(20), default="UNVERIFIED"); observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now); valid_until: Mapped[datetime|None] = mapped_column(DateTime(timezone=True)); metadata_: Mapped[dict|None] = mapped_column("metadata", JSON); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now); updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class CuratorAssessment(Base):
    __tablename__="curator_assessments"
    __table_args__=(UniqueConstraint("candidate_id","assessment_version",name="uq_curator_assessment_candidate_version"),)
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid);candidate_id:Mapped[str]=mapped_column(String(36),ForeignKey("curator_candidates.id",ondelete="CASCADE"));assessment_version:Mapped[int]=mapped_column(Integer);previous_assessment_id:Mapped[str|None]=mapped_column(String(36),ForeignKey("curator_assessments.id"))
    evidence_status:Mapped[str]=mapped_column(String(32));evidence_level:Mapped[str]=mapped_column(String(32));trust_gate:Mapped[str]=mapped_column(String(32));trust_reasons:Mapped[list]=mapped_column(JSON);trust_warnings:Mapped[list]=mapped_column(JSON)
    recommendation_score:Mapped[int|None]=mapped_column(Integer);recommendation_coverage_percent:Mapped[int]=mapped_column(Integer);recommendation_label:Mapped[str|None]=mapped_column(String(40));opportunity_score:Mapped[int|None]=mapped_column(Integer);opportunity_coverage_percent:Mapped[int]=mapped_column(Integer)
    price_verdict:Mapped[str]=mapped_column(String(32));price_to_buy_cents:Mapped[int|None]=mapped_column(Integer);editorial_verdict:Mapped[str]=mapped_column(String(40));recommendation_pillars:Mapped[dict]=mapped_column(JSON);opportunity_pillars:Mapped[dict]=mapped_column(JSON);evidence_ids_used:Mapped[list]=mapped_column(JSON);unknown_fields:Mapped[list]=mapped_column(JSON);rationale:Mapped[dict]=mapped_column(JSON);evaluated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now);created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class Campaign(Base):
    __tablename__="campaigns"
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid);candidate_id:Mapped[str]=mapped_column(String(36),ForeignKey("curator_candidates.id"));assessment_id:Mapped[str]=mapped_column(String(36),ForeignKey("curator_assessments.id"));name:Mapped[str]=mapped_column(String(200));status:Mapped[str]=mapped_column(String(24),default="DRAFT");objective:Mapped[str]=mapped_column(String(24));editorial_verdict_snapshot:Mapped[str]=mapped_column(String(40));trust_gate_snapshot:Mapped[str]=mapped_column(String(32));recommendation_score_snapshot:Mapped[int|None]=mapped_column(Integer);opportunity_score_snapshot:Mapped[int|None]=mapped_column(Integer);price_verdict_snapshot:Mapped[str]=mapped_column(String(32));campaign_priority:Mapped[str]=mapped_column(String(16));target_audience:Mapped[str|None]=mapped_column(Text);editorial_positioning:Mapped[str|None]=mapped_column(Text);primary_message:Mapped[str|None]=mapped_column(Text);affiliate_url:Mapped[str|None]=mapped_column(String(2000));affiliate_url_source:Mapped[str]=mapped_column(String(24),default="MANUAL");affiliate_url_verified_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True));disclosure_text:Mapped[str]=mapped_column(Text);cta_strategy:Mapped[str|None]=mapped_column(Text);requires_financial_spend:Mapped[bool]=mapped_column(Boolean,default=False);trust_warnings_snapshot:Mapped[list]=mapped_column(JSON,default=list);required_disclosures:Mapped[list]=mapped_column(JSON,default=list);required_warnings:Mapped[list]=mapped_column(JSON,default=list);forbidden_claims:Mapped[list]=mapped_column(JSON,default=list);created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now);updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now);approved_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True));rejected_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
class CampaignChannel(Base):
    __tablename__="campaign_channels";id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid);campaign_id:Mapped[str]=mapped_column(String(36),ForeignKey("campaigns.id",ondelete="CASCADE"));channel:Mapped[str]=mapped_column(String(32));enabled:Mapped[bool]=mapped_column(Boolean,default=True);publication_mode:Mapped[str]=mapped_column(String(32),default="MANUAL");platform_notes:Mapped[str|None]=mapped_column(Text);created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now);updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)
class CampaignAngle(Base):
    __tablename__="campaign_angles";id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid);campaign_id:Mapped[str]=mapped_column(String(36),ForeignKey("campaigns.id",ondelete="CASCADE"));angle_type:Mapped[str]=mapped_column(String(32));title:Mapped[str]=mapped_column(String(200));premise:Mapped[str]=mapped_column(Text);target_segment:Mapped[str|None]=mapped_column(Text);priority:Mapped[int]=mapped_column(Integer,default=0);status:Mapped[str]=mapped_column(String(16),default="ACTIVE");created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now);updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)
class CampaignExperiment(Base):
    __tablename__="campaign_experiments";id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid);campaign_id:Mapped[str]=mapped_column(String(36),ForeignKey("campaigns.id",ondelete="CASCADE"));angle_id:Mapped[str|None]=mapped_column(String(36),ForeignKey("campaign_angles.id"));hypothesis:Mapped[str]=mapped_column(Text);status:Mapped[str]=mapped_column(String(24),default="PLANNED");hook_strategy:Mapped[str|None]=mapped_column(Text);cta_strategy:Mapped[str|None]=mapped_column(Text);target_channel:Mapped[str|None]=mapped_column(String(32));variant_group:Mapped[str|None]=mapped_column(String(80));parent_experiment_id:Mapped[str|None]=mapped_column(String(36),ForeignKey("campaign_experiments.id"));created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now);updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)

class Creative(Base):
    __tablename__="creatives";id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid);campaign_id:Mapped[str]=mapped_column(String(36),ForeignKey("campaigns.id"));experiment_id:Mapped[str|None]=mapped_column(String(36),ForeignKey("campaign_experiments.id"));name:Mapped[str]=mapped_column(String(200));status:Mapped[str]=mapped_column(String(24),default="DRAFT");content_type:Mapped[str]=mapped_column(String(32),default="SHORT_VIDEO");target_channel:Mapped[str]=mapped_column(String(32),default="GENERIC");angle_type_snapshot:Mapped[str|None]=mapped_column(String(32));objective_snapshot:Mapped[str]=mapped_column(String(24));editorial_verdict_snapshot:Mapped[str]=mapped_column(String(40));price_verdict_snapshot:Mapped[str]=mapped_column(String(32));title:Mapped[str|None]=mapped_column(String(300));content_premise:Mapped[str|None]=mapped_column(Text);hook:Mapped[str|None]=mapped_column(Text);body_script:Mapped[str|None]=mapped_column(Text);cta:Mapped[str|None]=mapped_column(Text);estimated_duration_seconds:Mapped[int|None]=mapped_column(Integer);disclosure_text:Mapped[str]=mapped_column(Text);required_warnings:Mapped[list]=mapped_column(JSON,default=list);forbidden_claims:Mapped[list]=mapped_column(JSON,default=list);generation_mode:Mapped[str]=mapped_column(String(32),default="MANUAL");variant_group:Mapped[str|None]=mapped_column(String(80));parent_creative_id:Mapped[str|None]=mapped_column(String(36),ForeignKey("creatives.id"));variant_label:Mapped[str|None]=mapped_column(String(40));created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now);updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now);approved_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True));rejected_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
class CreativeScene(Base):
    __tablename__="creative_scenes";id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid);creative_id:Mapped[str]=mapped_column(String(36),ForeignKey("creatives.id",ondelete="CASCADE"));order_index:Mapped[int]=mapped_column(Integer);scene_type:Mapped[str]=mapped_column(String(24));speaker:Mapped[str]=mapped_column(String(16),default="NONE");purpose:Mapped[str]=mapped_column(String(120));narration_text:Mapped[str|None]=mapped_column(Text);on_screen_text:Mapped[str|None]=mapped_column(Text);visual_instruction:Mapped[str|None]=mapped_column(Text);avatar_state:Mapped[str|None]=mapped_column(String(24));duration_seconds:Mapped[int|None]=mapped_column(Integer);required_warning_codes:Mapped[list]=mapped_column(JSON,default=list);created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now);updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)

class MediaJob(Base):
    __tablename__="media_jobs";id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid);creative_id:Mapped[str]=mapped_column(String(36),ForeignKey("creatives.id"));render_type:Mapped[str]=mapped_column(String(16));status:Mapped[str]=mapped_column(String(32),default="QUEUED");width:Mapped[int]=mapped_column(Integer);height:Mapped[int]=mapped_column(Integer);fps:Mapped[int]=mapped_column(Integer,default=30);video_codec:Mapped[str]=mapped_column(String(24),default="h264");audio_codec:Mapped[str]=mapped_column(String(24),default="aac");expected_duration_seconds:Mapped[int|None]=mapped_column(Integer);actual_duration_seconds:Mapped[int|None]=mapped_column(Integer);output_relative_path:Mapped[str|None]=mapped_column(String(500));preview_relative_path:Mapped[str|None]=mapped_column(String(500));output_size_bytes:Mapped[int|None]=mapped_column(Integer);validation_status:Mapped[str|None]=mapped_column(String(16));validation_details:Mapped[dict|None]=mapped_column(JSON);progress_percent:Mapped[int]=mapped_column(Integer,default=0);current_stage:Mapped[str|None]=mapped_column(String(40));current_scene_index:Mapped[int|None]=mapped_column(Integer);total_scenes:Mapped[int|None]=mapped_column(Integer);error_code:Mapped[str|None]=mapped_column(String(80));error_message:Mapped[str|None]=mapped_column(Text);created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now);started_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True));completed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True));updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)

class MediaAsset(Base):
    __tablename__="media_assets";id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid);asset_type:Mapped[str]=mapped_column(String(24));owner_type:Mapped[str]=mapped_column(String(24));owner_id:Mapped[str|None]=mapped_column(String(36));logical_name:Mapped[str]=mapped_column(String(200));relative_path:Mapped[str]=mapped_column(String(500),unique=True);mime_type:Mapped[str]=mapped_column(String(80));width:Mapped[int|None]=mapped_column(Integer);height:Mapped[int|None]=mapped_column(Integer);file_size_bytes:Mapped[int]=mapped_column(Integer);metadata_:Mapped[dict|None]=mapped_column("metadata",JSON);active:Mapped[bool]=mapped_column(Boolean,default=True);created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now);updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)
