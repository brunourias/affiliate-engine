"""Controlled Campaign-approval-to-Creative handoff.

This service creates only an empty editable Creative. It deliberately does not
generate a template, scenes, approvals, media jobs, or publication records.
"""
from __future__ import annotations

import time

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from apps.api.app.db.models import (
    Approval,
    Campaign,
    CampaignAngle,
    CampaignChannel,
    CampaignExperiment,
    Creative,
    CuratorAssessment,
)
from apps.api.app.services.campaigns import readiness
from apps.api.app.services.operations import log_decision


def _error(code: str, message: str, status: int = 409, **extra):
    return HTTPException(status, {"code": code, "message": message, **extra})


class CreativeHandoffService:
    def __init__(self, db: Session):
        self.db = db

    def _campaign(self, campaign_id: str) -> Campaign:
        campaign = self.db.get(Campaign, campaign_id)
        if not campaign:
            raise HTTPException(404, "Campanha não encontrada")
        return campaign

    def _root_creatives(self, campaign_id: str, experiment_id: str | None) -> list[Creative]:
        query = select(Creative).where(
            Creative.campaign_id == campaign_id,
            Creative.parent_creative_id.is_(None),
            Creative.experiment_id == experiment_id if experiment_id else Creative.experiment_id.is_(None),
        ).order_by(Creative.created_at, Creative.id)
        return list(self.db.scalars(query))

    def _approval(self, campaign: Campaign) -> tuple[Approval | None, str | None]:
        rows = list(self.db.scalars(select(Approval).where(
            Approval.type == "CAMPAIGN",
            Approval.entity_type == "CAMPAIGN",
            Approval.entity_id == campaign.id,
            Approval.status == "APPROVED",
        ).order_by(Approval.created_at, Approval.id)))
        if not rows:
            return None, "CAMPAIGN_APPROVAL_REQUIRED"
        if len(rows) != 1:
            return None, "CAMPAIGN_APPROVAL_STATE_INCONSISTENT"
        return rows[0], None

    def _experiment(self, campaign: Campaign, experiment_id: str | None):
        if experiment_id is None:
            return None, None, None
        experiment = self.db.get(CampaignExperiment, experiment_id)
        if not experiment or experiment.campaign_id != campaign.id or experiment.status != "PLANNED":
            return None, None, "EXPERIMENT_NOT_ELIGIBLE"
        angle = None
        if experiment.angle_id:
            angle = self.db.get(CampaignAngle, experiment.angle_id)
            if not angle or angle.campaign_id != campaign.id or angle.status != "ACTIVE":
                return None, None, "EXPERIMENT_ANGLE_NOT_ELIGIBLE"
        if experiment.target_channel and not self.db.scalar(select(CampaignChannel.id).where(
            CampaignChannel.campaign_id == campaign.id,
            CampaignChannel.channel == experiment.target_channel,
            CampaignChannel.enabled.is_(True),
        )):
            return None, None, "EXPERIMENT_CHANNEL_NOT_ENABLED"
        return experiment, angle, None

    def _target_channel(self, campaign: Campaign, experiment: CampaignExperiment | None, requested: str | None):
        enabled = list(self.db.scalars(select(CampaignChannel.channel).where(
            CampaignChannel.campaign_id == campaign.id,
            CampaignChannel.enabled.is_(True),
        ).order_by(CampaignChannel.channel, CampaignChannel.id)))
        if requested is not None and requested not in enabled:
            return None, "CREATIVE_TARGET_CHANNEL_NOT_ENABLED"
        if experiment and experiment.target_channel:
            if requested and requested != experiment.target_channel:
                return None, "EXPERIMENT_TARGET_CHANNEL_CONFLICT"
            return experiment.target_channel, None
        if requested:
            return requested, None
        if len(enabled) == 1:
            return enabled[0], None
        if len(enabled) > 1:
            return None, "CREATIVE_TARGET_CHANNEL_REQUIRED"
        return None, "CHANNEL_REQUIRED"

    def _evaluate(self, campaign: Campaign, experiment_id: str | None, requested_channel: str | None):
        base = {
            "state": "NOT_ELIGIBLE",
            "campaignId": campaign.id,
            "campaignStatus": campaign.status,
            "approvalId": None,
            "assessmentId": campaign.assessment_id,
            "experimentId": experiment_id,
            "creativeId": None,
            "creativeName": None,
            "creativeStatus": None,
            "targetChannel": None,
            "reasonCode": None,
        }
        if campaign.status != "APPROVED":
            return {**base, "reasonCode": "CAMPAIGN_NOT_APPROVED"}, None

        approval, approval_error = self._approval(campaign)
        if approval_error:
            return {**base, "reasonCode": approval_error}, None
        assert approval is not None

        experiment, angle, experiment_error = self._experiment(campaign, experiment_id)
        if experiment_error:
            return {**base, "approvalId": approval.id, "reasonCode": experiment_error}, None

        current_readiness = readiness(self.db, campaign)
        if current_readiness["blockers"] or not current_readiness["checks"].get("sourceAssessmentCurrent"):
            reason = "CAMPAIGN_CREATIVE_HANDOFF_INVALIDATED"
            if not current_readiness["checks"].get("sourceAssessmentCurrent"):
                reason = "ASSESSMENT_OUTDATED"
            elif current_readiness["blockers"]:
                reason = current_readiness["blockers"][0]["code"]
            return {**base, "approvalId": approval.id, "reasonCode": reason}, {
                "approval": approval, "readiness": current_readiness, "blockers": current_readiness["blockers"]
            }

        target_channel, channel_error = self._target_channel(campaign, experiment, requested_channel)
        if channel_error:
            return {**base, "approvalId": approval.id, "reasonCode": channel_error}, {
                "approval": approval, "experiment": experiment, "angle": angle,
                "readiness": current_readiness, "blockers": current_readiness["blockers"]
            }

        matching = self._root_creatives(campaign.id, experiment.id if experiment else None)
        if len(matching) > 1:
            return {**base, "approvalId": approval.id, "targetChannel": target_channel,
                    "state": "MULTIPLE_CREATIVES",
                    "reasonCode": "MULTIPLE_CREATIVES_FOR_EXPERIMENT" if experiment else "MULTIPLE_CREATIVES_FOR_CAMPAIGN"}, {
                "approval": approval, "experiment": experiment, "angle": angle,
                "readiness": current_readiness, "targetChannel": target_channel, "matching": matching
            }
        if len(matching) == 1:
            creative = matching[0]
            return {**base, "approvalId": approval.id, "targetChannel": creative.target_channel,
                    "state": "CREATIVE_EXISTS", "creativeId": creative.id,
                    "creativeName": creative.name, "creativeStatus": creative.status}, {
                "approval": approval, "experiment": experiment, "angle": angle,
                "readiness": current_readiness, "targetChannel": target_channel, "matching": matching
            }
        return {**base, "approvalId": approval.id, "targetChannel": target_channel,
                "state": "READY_TO_CREATE"}, {
            "approval": approval,
            "assessment": self.db.get(CuratorAssessment, campaign.assessment_id),
            "experiment": experiment,
            "angle": angle,
            "readiness": current_readiness,
            "targetChannel": target_channel,
            "matching": matching,
        }

    def state(self, campaign_id: str, experiment_id: str | None = None,
              target_channel: str | None = None) -> dict:
        campaign = self._campaign(campaign_id)
        result, _ = self._evaluate(campaign, experiment_id, target_channel)
        return result

    def _raise_for_state(self, result: dict, context: dict | None):
        code = result["reasonCode"] or "CAMPAIGN_CREATIVE_HANDOFF_INVALIDATED"
        if code == "CAMPAIGN_CREATIVE_HANDOFF_INVALIDATED" or code in {
            "ASSESSMENT_OUTDATED", "INSUFFICIENT_EVIDENCE", "TRUST_GATE_BLOCKED",
            "EDITORIAL_VERDICT_NOT_ELIGIBLE", "TARGET_AUDIENCE_REQUIRED",
            "EDITORIAL_POSITIONING_REQUIRED", "PRIMARY_MESSAGE_REQUIRED", "CTA_REQUIRED",
            "DISCLOSURE_REQUIRED", "AFFILIATE_LINK_REQUIRED", "AFFILIATE_LINK_NOT_VERIFIED",
            "CHANNEL_REQUIRED", "ANGLE_REQUIRED", "EXPERIMENT_REQUIRED",
        }:
            blockers = context.get("blockers", []) if context else []
            raise _error("CAMPAIGN_CREATIVE_HANDOFF_INVALIDATED",
                         "A campanha mudou ou não atende mais às condições atuais para criar um criativo.", blockers=blockers)
        if code in {"CAMPAIGN_APPROVAL_REQUIRED", "CAMPAIGN_APPROVAL_STATE_INCONSISTENT"}:
            messages = {
                "CAMPAIGN_APPROVAL_REQUIRED": "A aprovação da campanha é necessária para criar o criativo.",
                "CAMPAIGN_APPROVAL_STATE_INCONSISTENT": "O histórico de aprovações da campanha precisa ser revisado.",
            }
            raise _error(code, messages[code])
        if code == "CREATIVE_TARGET_CHANNEL_NOT_ENABLED":
            raise _error(code, "O canal escolhido não está habilitado nesta campanha.", 422)
        if code == "CREATIVE_TARGET_CHANNEL_REQUIRED":
            raise _error(code, "Escolha um dos canais habilitados para esta campanha.", 422)
        if code == "MULTIPLE_CREATIVES_FOR_CAMPAIGN":
            raise _error("MULTIPLE_CREATIVES_FOR_CAMPAIGN", "Há mais de um criativo inicial associado a esta campanha.")
        if code == "MULTIPLE_CREATIVES_FOR_EXPERIMENT":
            raise _error("MULTIPLE_CREATIVES_FOR_EXPERIMENT", "Há mais de um criativo inicial associado a este experimento.")
        messages = {
            "CAMPAIGN_NOT_APPROVED": "Somente campanhas aprovadas podem iniciar a criação de um criativo.",
            "EXPERIMENT_NOT_ELIGIBLE": "O experimento não pertence à campanha ou não está elegível.",
            "EXPERIMENT_ANGLE_NOT_ELIGIBLE": "O ângulo do experimento não está ativo nesta campanha.",
            "EXPERIMENT_CHANNEL_NOT_ENABLED": "O canal definido no experimento não está habilitado na campanha.",
            "EXPERIMENT_TARGET_CHANNEL_CONFLICT": "O canal solicitado não corresponde ao canal definido no experimento.",
            "CHANNEL_REQUIRED": "A campanha precisa ter ao menos um canal habilitado.",
        }
        raise _error(code, messages.get(code, "Não foi possível criar o criativo a partir desta campanha."))

    def create(self, campaign_id: str, data, experiment_id: str | None = None) -> Creative:
        campaign = self._campaign(campaign_id)
        chosen_experiment_id = data.experimentId if data.experimentId is not None else experiment_id
        if experiment_id is not None and data.experimentId is not None and data.experimentId != experiment_id:
            raise _error("EXPERIMENT_ID_MISMATCH", "O experimento informado não corresponde ao experimento desta solicitação.", 422)

        result, context = self._evaluate(campaign, chosen_experiment_id, data.targetChannel)
        if result["state"] == "NOT_ELIGIBLE" or result["state"] == "MULTIPLE_CREATIVES":
            self._raise_for_state(result, context)
        if result["state"] == "CREATIVE_EXISTS":
            return context["matching"][0]

        approval: Approval = context["approval"]
        experiment: CampaignExperiment | None = context.get("experiment")
        angle: CampaignAngle | None = context.get("angle")
        assessment: CuratorAssessment | None = context.get("assessment")
        if assessment is None:
            raise _error("CAMPAIGN_CREATIVE_HANDOFF_INVALIDATED", "A análise aprovada não está mais disponível.")
        creation_key = f"CAMPAIGN_APPROVAL:{approval.id}:" + (f"EXPERIMENT:{experiment.id}" if experiment else "BASE")
        name = data.name.strip() if data.name and data.name.strip() else f"Criativo — {campaign.name}"
        row = Creative(
            campaign_id=campaign.id,
            experiment_id=experiment.id if experiment else None,
            name=name,
            status="DRAFT",
            content_type=data.contentType,
            target_channel=context["targetChannel"],
            angle_type_snapshot=angle.angle_type if angle else None,
            objective_snapshot=campaign.objective,
            editorial_verdict_snapshot=campaign.editorial_verdict_snapshot,
            price_verdict_snapshot=campaign.price_verdict_snapshot,
            content_premise=(experiment.hypothesis if experiment else campaign.editorial_positioning),
            hook=experiment.hook_strategy if experiment else None,
            cta=experiment.cta_strategy if experiment else campaign.cta_strategy,
            estimated_duration_seconds=20 if data.contentType == "SHORT_VIDEO" else None,
            disclosure_text=campaign.disclosure_text,
            required_warnings=list(campaign.required_warnings or []),
            forbidden_claims=list(campaign.forbidden_claims or []),
            generation_mode="MANUAL",
            creation_source="CAMPAIGN_APPROVAL",
            creation_key=creation_key,
            source_campaign_approval_id=approval.id,
            source_assessment_id=campaign.assessment_id,
        )
        try:
            self.db.add(row)
            self.db.flush()
            log_decision(self.db, "OPERATOR", "CREATIVE", "CREATIVE_CREATED", row.id, metadata={
                "campaignId": campaign.id,
                "campaignApprovalId": approval.id,
                "assessmentId": campaign.assessment_id,
                "experimentId": experiment.id if experiment else None,
                "creationSource": "CAMPAIGN_APPROVAL",
                "creationKey": creation_key,
                "targetChannel": context["targetChannel"],
            })
            self.db.commit()
            self.db.refresh(row)
            return row
        except IntegrityError:
            self.db.rollback()
            existing = self.db.scalar(select(Creative).where(Creative.creation_key == creation_key))
            if existing:
                return existing
            raise _error("CREATIVE_HANDOFF_CONFLICT", "A criação do criativo está sendo processada. Atualize o estado e tente novamente.")
        except OperationalError:
            self.db.rollback()
            # SQLite may surface a concurrent deferred-write race as SQLITE_BUSY
            # instead of UNIQUE violation. Retry the idempotency lookup briefly.
            for _ in range(5):
                existing = self.db.scalar(select(Creative).where(Creative.creation_key == creation_key))
                if existing:
                    return existing
                time.sleep(0.02)
            raise _error("CREATIVE_HANDOFF_CONFLICT", "A criação do criativo está sendo processada. Atualize o estado e tente novamente.")
        except Exception:
            self.db.rollback()
            raise
