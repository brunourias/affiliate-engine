from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
class ORM(BaseModel): model_config=ConfigDict(from_attributes=True, populate_by_name=True)
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
