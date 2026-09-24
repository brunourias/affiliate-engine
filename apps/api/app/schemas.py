from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
def utc_iso(value:datetime):
    aware=value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return aware.isoformat().replace("+00:00","Z")
class ORM(BaseModel):
    model_config=ConfigDict(from_attributes=True,populate_by_name=True)
    @field_serializer("*",when_used="json",check_fields=False)
    def serialize_datetimes(self,value):return utc_iso(value) if isinstance(value,datetime) else value
class SettingsOut(ORM):
    monthlyConfirmedCommissionGoalCents:int=Field(validation_alias="monthly_confirmed_commission_goal_cents"); dailyPublicationLimit:int=Field(validation_alias="daily_publication_limit"); timezone:str; systemAutomationEnabled:bool=Field(validation_alias="system_automation_enabled"); radarEnabled:bool=Field(validation_alias="radar_enabled"); creativeEnabled:bool=Field(validation_alias="creative_enabled"); publishingEnabled:bool=Field(validation_alias="publishing_enabled"); commentReplyEnabled:bool=Field(validation_alias="comment_reply_enabled"); externalIntelligenceEnabled:bool=Field(validation_alias="external_intelligence_enabled"); updatedAt:datetime=Field(validation_alias="updated_at")
class SettingsPatch(BaseModel):
    monthlyConfirmedCommissionGoalCents:int|None=Field(None,ge=0); dailyPublicationLimit:int|None=Field(None,ge=0); timezone:str|None=None; systemAutomationEnabled:bool|None=None; radarEnabled:bool|None=None; creativeEnabled:bool|None=None; publishingEnabled:bool|None=None; commentReplyEnabled:bool|None=None; externalIntelligenceEnabled:bool|None=None
    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls,v):
        if v is not None:
            try: ZoneInfo(v)
            except ZoneInfoNotFoundError: raise ValueError("Timezone inválida")
        return v
class ApprovalOut(ORM):
    id:str; type:str; status:str; title:str; description:str; entityType:str|None=Field(validation_alias="entity_type"); entityId:str|None=Field(validation_alias="entity_id"); requestedPayload:dict|None=Field(validation_alias="requested_payload"); decidedAt:datetime|None=Field(validation_alias="decided_at"); decisionReason:str|None=Field(validation_alias="decision_reason"); createdAt:datetime=Field(validation_alias="created_at"); updatedAt:datetime=Field(validation_alias="updated_at")
class DecisionRequest(BaseModel): reason:str|None=Field(None,max_length=1000)
class NotificationOut(ORM):
    id:str; type:str; severity:str; title:str; message:str; isRead:bool=Field(validation_alias="is_read"); createdAt:datetime=Field(validation_alias="created_at"); readAt:datetime|None=Field(validation_alias="read_at"); metadata:dict|None=Field(validation_alias="metadata_")
class TaskCreate(BaseModel): type:Literal["SYSTEM_HEARTBEAT","CONTROLLED_FAILURE"]="SYSTEM_HEARTBEAT"; title:str=Field(min_length=1,max_length=200); payload:dict[str,Any]|None=None; isAutomatic:bool=False
class TaskOut(ORM):
    id:str; type:str; status:str; title:str; payload:dict|None; result:dict|None; error:str|None; isAutomatic:bool=Field(validation_alias="is_automatic"); createdAt:datetime=Field(validation_alias="created_at"); startedAt:datetime|None=Field(validation_alias="started_at"); finishedAt:datetime|None=Field(validation_alias="finished_at"); updatedAt:datetime=Field(validation_alias="updated_at")
class DecisionOut(ORM):
    id:str; timestamp:datetime; actor:str; entityType:str=Field(validation_alias="entity_type"); entityId:str|None=Field(validation_alias="entity_id"); action:str; reason:str|None; confidence:str|None; metadata:dict|None=Field(validation_alias="metadata_")


class MarketplaceCapabilityOut(ORM):
    id: str
    provider: str
    capabilityKey: str = Field(validation_alias="capability_key")
    status: str
    endpoint: str | None
    httpMethod: str | None = Field(validation_alias="http_method")
    lastHttpStatus: int | None = Field(validation_alias="last_http_status")
    latencyMs: int | None = Field(validation_alias="latency_ms")
    reasonCode: str | None = Field(validation_alias="reason_code")
    message: str | None
    metadata: dict | None = Field(validation_alias="metadata_")
    checkedAt: datetime | None = Field(validation_alias="checked_at")


class MarketplaceConnectionOut(ORM):
    id: str
    provider: str
    siteId: str = Field(validation_alias="site_id")
    status: str
    authMode: str = Field(validation_alias="auth_mode")
    externalAccountId: str | None = Field(validation_alias="external_account_id")
    externalNickname: str | None = Field(validation_alias="external_nickname")
    lastCheckedAt: datetime | None = Field(validation_alias="last_checked_at")
    lastSuccessAt: datetime | None = Field(validation_alias="last_success_at")
    metadata: dict | None = Field(validation_alias="metadata_")
    createdAt: datetime = Field(validation_alias="created_at")
    updatedAt: datetime = Field(validation_alias="updated_at")


class MarketplaceDiagnosticsRequest(BaseModel):
    categoryId: str | None = Field(default=None, pattern=r"^MLB\d+$")


class MarketplaceItemDiagnosticsRequest(BaseModel):
    item: str = Field(min_length=1, max_length=500)


class MarketplaceCategoryOut(ORM):
    id: str
    provider: str
    siteId: str = Field(validation_alias="site_id")
    externalCategoryId: str = Field(validation_alias="external_category_id")
    name: str
    parentExternalCategoryId: str | None = Field(validation_alias="parent_external_category_id")
    sourceCapability: str = Field(validation_alias="source_capability")
    firstSeenAt: datetime = Field(validation_alias="first_seen_at")
    lastSeenAt: datetime = Field(validation_alias="last_seen_at")


class RadarRunCreate(BaseModel):
    categoryId: str | None = Field(default=None, pattern=r"^MLB\d+$")


class RadarRunOut(ORM):
    id: str
    provider: str
    siteId: str = Field(validation_alias="site_id")
    triggerType: str = Field(validation_alias="trigger_type")
    status: str
    requestedCategoryId: str | None = Field(validation_alias="requested_category_id")
    startedAt: datetime = Field(validation_alias="started_at")
    finishedAt: datetime | None = Field(validation_alias="finished_at")
    sourcesRequested: list[str] = Field(validation_alias="sources_requested")
    sourcesSucceeded: list[str] = Field(validation_alias="sources_succeeded")
    sourcesFailed: list[str] = Field(validation_alias="sources_failed")
    discoveredCount: int = Field(validation_alias="discovered_count")
    errorSummary: str | None = Field(validation_alias="error_summary")


class RadarSignalOut(ORM):
    id: str
    radarRunId: str = Field(validation_alias="radar_run_id")
    provider: str
    siteId: str = Field(validation_alias="site_id")
    sourceType: str = Field(validation_alias="source_type")
    sourceCapability: str = Field(validation_alias="source_capability")
    categoryExternalId: str | None = Field(validation_alias="category_external_id")
    entityType: str = Field(validation_alias="entity_type")
    externalId: str | None = Field(validation_alias="external_id")
    displayText: str | None = Field(validation_alias="display_text")
    rank: int | None
    sourcePayload: dict | None = Field(validation_alias="source_payload")
    observedAt: datetime = Field(validation_alias="observed_at")


class RadarStatusOut(BaseModel):
    provider: str
    siteId: str
    status: str
    capabilities: dict[str, str]

Provider=Literal["MERCADO_LIVRE","OTHER"]
EntityType=Literal["QUERY","ITEM","PRODUCT","USER_PRODUCT","UNKNOWN","MANUAL"]
CandidateStatus=Literal["NEW","INVESTIGATING","READY_FOR_REVIEW","ARCHIVED"]
class CandidateCreate(BaseModel):
    provider:Provider="OTHER"; entityType:EntityType="MANUAL"; workingTitle:str|None=Field(None,max_length=300); sourceUrl:str|None=Field(None,max_length=1000); externalId:str|None=Field(None,max_length=120); categoryExternalId:str|None=Field(None,max_length=80); notes:str|None=Field(None,max_length=5000)
class CandidatePatch(BaseModel):
    workingTitle:str|None=Field(None,max_length=300); sourceUrl:str|None=Field(None,max_length=1000); notes:str|None=Field(None,max_length=5000); status:CandidateStatus|None=None
class CandidateOut(ORM):
    id:str;provider:str;siteId:str|None=Field(validation_alias="site_id");sourceType:str=Field(validation_alias="source_type");sourceRadarSignalId:str|None=Field(validation_alias="source_radar_signal_id");sourceRadarRunId:str|None=Field(validation_alias="source_radar_run_id");entityType:str=Field(validation_alias="entity_type");externalId:str|None=Field(validation_alias="external_id");categoryExternalId:str|None=Field(validation_alias="category_external_id");workingTitle:str|None=Field(validation_alias="working_title");sourceUrl:str|None=Field(validation_alias="source_url");notes:str|None;status:str;evidenceStatus:str=Field(validation_alias="evidence_status");evidenceLevel:str=Field(validation_alias="evidence_level");firstSeenAt:datetime=Field(validation_alias="first_seen_at");lastSeenAt:datetime=Field(validation_alias="last_seen_at");createdAt:datetime=Field(validation_alias="created_at");updatedAt:datetime=Field(validation_alias="updated_at")
class EvidenceCreate(BaseModel):
    evidenceType:str;valueText:str|None=None;valueNumber:int|None=None;valueCents:int|None=Field(None,ge=0);valueJson:dict|None=None;sourceKind:str="MANUAL_OPERATOR";sourceName:str|None=None;sourceUrl:str|None=None;sourceReference:str|None=None;confidence:Literal["LOW","MEDIUM","HIGH","VERY_HIGH"]="MEDIUM";verificationStatus:Literal["UNVERIFIED","VERIFIED","DISPUTED"]="UNVERIFIED";observedAt:datetime|None=None;validUntil:datetime|None=None;metadata:dict|None=None
class EvidencePatch(EvidenceCreate): pass
class EvidenceOut(ORM):
    id:str;candidateId:str=Field(validation_alias="candidate_id");evidenceType:str=Field(validation_alias="evidence_type");valueText:str|None=Field(validation_alias="value_text");valueNumber:int|None=Field(validation_alias="value_number");valueCents:int|None=Field(validation_alias="value_cents");valueJson:dict|None=Field(validation_alias="value_json");sourceKind:str=Field(validation_alias="source_kind");sourceName:str|None=Field(validation_alias="source_name");sourceUrl:str|None=Field(validation_alias="source_url");sourceReference:str|None=Field(validation_alias="source_reference");confidence:str;verificationStatus:str=Field(validation_alias="verification_status");observedAt:datetime=Field(validation_alias="observed_at");validUntil:datetime|None=Field(validation_alias="valid_until");isStale:bool=False;metadata:dict|None=Field(validation_alias="metadata_")
class AssessmentOut(ORM):
    id:str;candidateId:str=Field(validation_alias="candidate_id");assessmentVersion:int=Field(validation_alias="assessment_version");previousAssessmentId:str|None=Field(validation_alias="previous_assessment_id");evidenceStatus:str=Field(validation_alias="evidence_status");evidenceLevel:str=Field(validation_alias="evidence_level");trustGate:str=Field(validation_alias="trust_gate");trustReasons:list=Field(validation_alias="trust_reasons");trustWarnings:list=Field(validation_alias="trust_warnings");recommendationScore:int|None=Field(validation_alias="recommendation_score");recommendationCoveragePercent:int=Field(validation_alias="recommendation_coverage_percent");recommendationLabel:str|None=Field(validation_alias="recommendation_label");opportunityScore:int|None=Field(validation_alias="opportunity_score");opportunityCoveragePercent:int=Field(validation_alias="opportunity_coverage_percent");priceVerdict:str=Field(validation_alias="price_verdict");priceToBuyCents:int|None=Field(validation_alias="price_to_buy_cents");editorialVerdict:str=Field(validation_alias="editorial_verdict");recommendationPillars:dict=Field(validation_alias="recommendation_pillars");opportunityPillars:dict=Field(validation_alias="opportunity_pillars");evidenceIdsUsed:list[str]=Field(validation_alias="evidence_ids_used");unknownFields:list[str]=Field(validation_alias="unknown_fields");rationale:dict;evaluatedAt:datetime=Field(validation_alias="evaluated_at");createdAt:datetime=Field(validation_alias="created_at")

class CampaignCreate(BaseModel):
    assessmentId:str;name:str=Field(min_length=1,max_length=200);objective:Literal["CONVERSION","TRAFFIC","DISCOVERY","PRICE_ALERT","EDUCATION","COMPARISON"]|None=None
class CampaignPatch(BaseModel):
    name:str|None=Field(None,min_length=1,max_length=200);objective:str|None=None;targetAudience:str|None=None;editorialPositioning:str|None=None;primaryMessage:str|None=None;affiliateUrl:str|None=None;affiliateUrlVerified:bool|None=None;disclosureText:str|None=None;ctaStrategy:str|None=None;requiresFinancialSpend:bool|None=None
class CampaignOut(ORM):
    id:str;candidateId:str=Field(validation_alias="candidate_id");assessmentId:str=Field(validation_alias="assessment_id");name:str;status:str;objective:str;editorialVerdictSnapshot:str=Field(validation_alias="editorial_verdict_snapshot");trustGateSnapshot:str=Field(validation_alias="trust_gate_snapshot");recommendationScoreSnapshot:int|None=Field(validation_alias="recommendation_score_snapshot");opportunityScoreSnapshot:int|None=Field(validation_alias="opportunity_score_snapshot");priceVerdictSnapshot:str=Field(validation_alias="price_verdict_snapshot");campaignPriority:str=Field(validation_alias="campaign_priority");targetAudience:str|None=Field(validation_alias="target_audience");editorialPositioning:str|None=Field(validation_alias="editorial_positioning");primaryMessage:str|None=Field(validation_alias="primary_message");affiliateUrl:str|None=Field(validation_alias="affiliate_url");affiliateUrlSource:str=Field(validation_alias="affiliate_url_source");affiliateUrlVerifiedAt:datetime|None=Field(validation_alias="affiliate_url_verified_at");disclosureText:str=Field(validation_alias="disclosure_text");ctaStrategy:str|None=Field(validation_alias="cta_strategy");requiresFinancialSpend:bool=Field(validation_alias="requires_financial_spend");trustWarningsSnapshot:list=Field(validation_alias="trust_warnings_snapshot");requiredDisclosures:list=Field(validation_alias="required_disclosures");requiredWarnings:list=Field(validation_alias="required_warnings");forbiddenClaims:list=Field(validation_alias="forbidden_claims");createdAt:datetime=Field(validation_alias="created_at");updatedAt:datetime=Field(validation_alias="updated_at");approvedAt:datetime|None=Field(validation_alias="approved_at");rejectedAt:datetime|None=Field(validation_alias="rejected_at")
class ChannelData(BaseModel):
    channel:Literal["TIKTOK","INSTAGRAM_REELS","YOUTUBE_SHORTS","FACEBOOK_REELS","WHATSAPP","WEBSITE"];enabled:bool=True;publicationMode:Literal["FUTURE_AUTOMATIC","FUTURE_ASSISTED","MANUAL"]="MANUAL";platformNotes:str|None=None
class ChannelPatch(BaseModel): enabled:bool|None=None;publicationMode:str|None=None;platformNotes:str|None=None
class ChannelOut(ORM):
    id:str;campaignId:str=Field(validation_alias="campaign_id");channel:str;enabled:bool;publicationMode:str=Field(validation_alias="publication_mode");platformNotes:str|None=Field(validation_alias="platform_notes");createdAt:datetime=Field(validation_alias="created_at");updatedAt:datetime=Field(validation_alias="updated_at")
class AngleData(BaseModel):
    angleType:Literal["SMART_BUYING","OPPORTUNITY","DISCOVERY","COMPARISON","PROBLEM_SOLUTION","PRICE_ALERT","REVIEW","LIMITATION_FIRST","EDUCATION"];title:str=Field(min_length=1,max_length=200);premise:str=Field(min_length=1);targetSegment:str|None=None;priority:int=0;status:Literal["ACTIVE","DISABLED"]="ACTIVE"
class AnglePatch(BaseModel): title:str|None=None;premise:str|None=None;targetSegment:str|None=None;priority:int|None=None;status:str|None=None
class AngleOut(ORM):
    id:str;campaignId:str=Field(validation_alias="campaign_id");angleType:str=Field(validation_alias="angle_type");title:str;premise:str;targetSegment:str|None=Field(validation_alias="target_segment");priority:int;status:str;createdAt:datetime=Field(validation_alias="created_at");updatedAt:datetime=Field(validation_alias="updated_at")
class ExperimentData(BaseModel):
    angleId:str|None=None;hypothesis:str=Field(min_length=1);status:str="PLANNED";hookStrategy:str|None=None;ctaStrategy:str|None=None;targetChannel:str|None=None;variantGroup:str|None=None;parentExperimentId:str|None=None
class ExperimentPatch(BaseModel): hypothesis:str|None=None;status:str|None=None;hookStrategy:str|None=None;ctaStrategy:str|None=None;targetChannel:str|None=None;variantGroup:str|None=None
class ExperimentOut(ORM):
    id:str;campaignId:str=Field(validation_alias="campaign_id");angleId:str|None=Field(validation_alias="angle_id");hypothesis:str;status:str;hookStrategy:str|None=Field(validation_alias="hook_strategy");ctaStrategy:str|None=Field(validation_alias="cta_strategy");targetChannel:str|None=Field(validation_alias="target_channel");variantGroup:str|None=Field(validation_alias="variant_group");parentExperimentId:str|None=Field(validation_alias="parent_experiment_id");createdAt:datetime=Field(validation_alias="created_at");updatedAt:datetime=Field(validation_alias="updated_at")

class CreativeCreate(BaseModel):
    name:str|None=Field(None,max_length=200);contentType:str="SHORT_VIDEO";targetChannel:str="GENERIC";experimentId:str|None=None
class CreativePatch(BaseModel):
    name:str|None=None;contentType:str|None=None;targetChannel:str|None=None;title:str|None=None;contentPremise:str|None=None;hook:str|None=None;bodyScript:str|None=None;cta:str|None=None;estimatedDurationSeconds:int|None=Field(None,ge=1,le=3600);disclosureText:str|None=None;variantLabel:str|None=None
class TemplateGenerate(BaseModel):
    overwrite:bool=False
class CreativeOut(ORM):
    id:str;campaignId:str=Field(validation_alias="campaign_id");experimentId:str|None=Field(validation_alias="experiment_id");name:str;status:str;contentType:str=Field(validation_alias="content_type");targetChannel:str=Field(validation_alias="target_channel");angleTypeSnapshot:str|None=Field(validation_alias="angle_type_snapshot");objectiveSnapshot:str=Field(validation_alias="objective_snapshot");editorialVerdictSnapshot:str=Field(validation_alias="editorial_verdict_snapshot");priceVerdictSnapshot:str=Field(validation_alias="price_verdict_snapshot");title:str|None;contentPremise:str|None=Field(validation_alias="content_premise");hook:str|None;bodyScript:str|None=Field(validation_alias="body_script");cta:str|None;estimatedDurationSeconds:int|None=Field(validation_alias="estimated_duration_seconds");disclosureText:str=Field(validation_alias="disclosure_text");requiredWarnings:list=Field(validation_alias="required_warnings");forbiddenClaims:list=Field(validation_alias="forbidden_claims");generationMode:str=Field(validation_alias="generation_mode");variantGroup:str|None=Field(validation_alias="variant_group");parentCreativeId:str|None=Field(validation_alias="parent_creative_id");variantLabel:str|None=Field(validation_alias="variant_label");createdAt:datetime=Field(validation_alias="created_at");updatedAt:datetime=Field(validation_alias="updated_at");approvedAt:datetime|None=Field(validation_alias="approved_at");rejectedAt:datetime|None=Field(validation_alias="rejected_at")
class SceneData(BaseModel):
    orderIndex:int=Field(ge=0);sceneType:str;speaker:str="NONE";purpose:str=Field(min_length=1);narrationText:str|None=None;onScreenText:str|None=None;visualInstruction:str|None=None;avatarState:str|None=None;durationSeconds:int|None=Field(None,ge=1);requiredWarningCodes:list[str]=[]
class ScenePatch(BaseModel):
    orderIndex:int|None=Field(None,ge=0);sceneType:str|None=None;speaker:str|None=None;purpose:str|None=None;narrationText:str|None=None;onScreenText:str|None=None;visualInstruction:str|None=None;avatarState:str|None=None;durationSeconds:int|None=Field(None,ge=1);requiredWarningCodes:list[str]|None=None
class SceneOut(ORM):
    id:str;creativeId:str=Field(validation_alias="creative_id");orderIndex:int=Field(validation_alias="order_index");sceneType:str=Field(validation_alias="scene_type");speaker:str;purpose:str;narrationText:str|None=Field(validation_alias="narration_text");onScreenText:str|None=Field(validation_alias="on_screen_text");visualInstruction:str|None=Field(validation_alias="visual_instruction");avatarState:str|None=Field(validation_alias="avatar_state");durationSeconds:int|None=Field(validation_alias="duration_seconds");requiredWarningCodes:list[str]=Field(validation_alias="required_warning_codes")

class MediaJobCreate(BaseModel): renderType:Literal["PREVIEW","STANDARD"]="PREVIEW"
class VoicePreviewCreate(BaseModel):
    text:str=Field(min_length=1,max_length=500);speaker:Literal["BRUNO","CAROL","NARRATOR"]="CAROL";voiceStyle:Literal["CURIOUS_ENERGETIC","CONVERSATIONAL","CONFIDENT","CAUTION","EXPLANATORY","CONFIDENT_INVITING"]="CURIOUS_ENERGETIC"
class MediaJobOut(ORM):
    id:str;creativeId:str=Field(validation_alias="creative_id");renderType:str=Field(validation_alias="render_type");status:str;width:int;height:int;fps:int;videoCodec:str=Field(validation_alias="video_codec");audioCodec:str=Field(validation_alias="audio_codec");expectedDurationSeconds:int|None=Field(validation_alias="expected_duration_seconds");actualDurationSeconds:int|None=Field(validation_alias="actual_duration_seconds");outputRelativePath:str|None=Field(validation_alias="output_relative_path");previewRelativePath:str|None=Field(validation_alias="preview_relative_path");outputSizeBytes:int|None=Field(validation_alias="output_size_bytes");validationStatus:str|None=Field(validation_alias="validation_status");validationDetails:dict|None=Field(validation_alias="validation_details");progressPercent:int=Field(validation_alias="progress_percent");currentStage:str|None=Field(validation_alias="current_stage");currentSceneIndex:int|None=Field(validation_alias="current_scene_index");totalScenes:int|None=Field(validation_alias="total_scenes");errorCode:str|None=Field(validation_alias="error_code");errorMessage:str|None=Field(validation_alias="error_message");createdAt:datetime=Field(validation_alias="created_at");startedAt:datetime|None=Field(validation_alias="started_at");completedAt:datetime|None=Field(validation_alias="completed_at");updatedAt:datetime=Field(validation_alias="updated_at")
class MediaAssetOut(ORM):
    id:str;assetType:str=Field(validation_alias="asset_type");ownerType:str=Field(validation_alias="owner_type");ownerId:str|None=Field(validation_alias="owner_id");logicalName:str=Field(validation_alias="logical_name");relativePath:str=Field(validation_alias="relative_path");mimeType:str=Field(validation_alias="mime_type");width:int|None;height:int|None;fileSizeBytes:int=Field(validation_alias="file_size_bytes");metadata:dict|None=Field(validation_alias="metadata_");active:bool;createdAt:datetime=Field(validation_alias="created_at");updatedAt:datetime=Field(validation_alias="updated_at")
