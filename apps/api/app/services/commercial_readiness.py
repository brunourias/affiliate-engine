from __future__ import annotations

from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db.models import Campaign, Creative, CreativeScene, MediaAsset
from apps.api.app.services.channel_adaptation import ChannelAssetAdaptationEngine
from apps.api.app.services.format_decision import CreativeDistributionPlan
from apps.api.app.services.commercial_snapshot import MarketplaceCommercialSnapshotService


class CommercialReadinessService:
    """Deterministic, evidence-first commercial checks; no external AI is required."""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _item(code: str, status: str, message: str, severity: str = "INFO", source: str | None = None, evidence: object | None = None) -> dict:
        result = {"code": code, "status": status, "message": message, "severity": severity, "source": source}
        if evidence is not None:
            result["evidence"] = evidence
        return result

    @staticmethod
    def _url(value: str | None) -> bool:
        try:
            parts = urlsplit(value or "")
            return parts.scheme in {"http", "https"} and bool(parts.netloc)
        except ValueError:
            return False

    def evaluate(self, creative_id: str, channel: str = "INSTAGRAM", format: str = "STATIC_CARD") -> dict:
        creative = self.db.get(Creative, creative_id)
        if not creative:
            raise ValueError("CREATIVE_NOT_FOUND")
        campaign = self.db.get(Campaign, creative.campaign_id)
        snapshot = MarketplaceCommercialSnapshotService(self.db).build(creative_id)
        candidate = CreativeDistributionPlan(self.db).create(creative_id, [format], distribution_mode="ORGANIC", channel=channel)["publicationCandidates"][0]
        scenes = list(self.db.scalars(select(CreativeScene).where(CreativeScene.creative_id == creative_id).order_by(CreativeScene.order_index)))
        assets = [self.db.scalar(select(MediaAsset).where(MediaAsset.relative_path == path)) for path in candidate.get("assetPaths", [])]
        checks: list[dict] = []

        has_asset = bool(candidate.get("assetPaths")) and all(asset is not None and asset.active for asset in assets)
        checks.append(self._item("VISUAL_AVAILABLE", "PASS" if has_asset else "BLOCKED", "O visual final está disponível." if has_asset else "Adicione uma imagem válida do produto.", "INFO" if has_asset else "BLOCKER", "MEDIA_ASSET"))

        visibility = "UNKNOWN"
        for asset in assets:
            metadata = asset.metadata_ if asset else {}
            if isinstance(metadata, dict) and metadata.get("productCoveragePercent") is not None:
                visibility = "PASS" if 55 <= float(metadata["productCoveragePercent"]) <= 75 else "WARNING"
                break
        checks.append(self._item("PRODUCT_VISIBILITY", visibility, "O produto possui enquadramento comercial adequado." if visibility == "PASS" else "Confirme que o produto ocupa área visual relevante no preview.", "INFO" if visibility == "PASS" else "WARNING", "MEDIA_ASSET"))

        headline = (creative.hook or creative.title or "").strip()
        generic = not headline or headline.upper() in {"VALE OLHAR OS DETALHES", "VEJA OS DETALHES", "PRODUTO"}
        checks.append(self._item("HEADLINE_QUALITY", "WARNING" if generic else "PASS", "Defina uma headline específica baseada em evidências." if generic else "A headline está definida.", "WARNING" if generic else "INFO", "CREATIVE"))

        benefit_text = " ".join(filter(None, [creative.content_premise, creative.body_script, *(claim["text"] for claim in snapshot["commercialClaims"]), *(scene.on_screen_text for scene in scenes)]))
        checks.append(self._item("BENEFITS_AVAILABLE", "PASS" if benefit_text.strip() else "WARNING", "Há conteúdo para contextualizar benefícios." if benefit_text.strip() else "Não há benefício/evidência suficiente para destacar.", "INFO" if benefit_text.strip() else "WARNING", "CREATIVE"))

        checks.append(self._item("CTA_PRESENT", "PASS" if creative.cta and creative.cta.strip() else "BLOCKED", "CTA definido." if creative.cta and creative.cta.strip() else "Defina um CTA comercial.", "INFO" if creative.cta and creative.cta.strip() else "BLOCKER", "CREATIVE"))
        caption_ready = bool(headline and benefit_text.strip() and creative.cta and creative.disclosure_text)
        checks.append(self._item("CAPTION_COMPLETE", "PASS" if caption_ready else "BLOCKED", "A legenda possui estrutura comercial mínima." if caption_ready else "A legenda precisa de hook, contexto, CTA e disclosure.", "INFO" if caption_ready else "BLOCKER", "CREATIVE"))

        destination = snapshot["destination"]["destinationUrl"]
        strategy = snapshot["destination"]["destinationStrategy"] if snapshot["destination"]["destinationStrategy"] != "UNKNOWN" else None
        checks.append(self._item("DESTINATION_STRATEGY", "PASS" if strategy else "BLOCKED", "Estratégia de destino definida." if strategy else "Defina como a pessoa chegará ao produto.", "INFO" if strategy else "BLOCKER", "CAMPAIGN", strategy))
        checks.append(self._item("DESTINATION_READY", "PASS" if self._url(destination) else "BLOCKED", "Destino válido configurado." if self._url(destination) else "Configure uma URL de destino válida.", "INFO" if self._url(destination) else "BLOCKER", "CAMPAIGN"))
        affiliate_status = snapshot["destination"].get("affiliateStatus", {}).get("status")
        # Snapshots produced before F2.2b may not carry the explicit validator result;
        # preserve their established strategy semantics while new snapshots are strict.
        if affiliate_status is None and snapshot["destination"].get("destinationStrategy") not in {None, "UNKNOWN"}:
            affiliate_status = "READY"
        affiliate_reason = snapshot["destination"].get("affiliateStatus", {}).get("reasonCode")
        affiliate_message = "Link de afiliado válido para atribuição elegível." if affiliate_status == "READY" else "Este link de afiliado aponta para outro produto." if affiliate_reason == "AFFILIATE_ITEM_MISMATCH" else "Não foi possível verificar o produto deste link." if snapshot["destination"].get("affiliateValidationStatus") == "UNVERIFIED" else "Configure um link de afiliado oficial para este produto."
        checks.append(self._item("AFFILIATE_DESTINATION_READY", "PASS" if affiliate_status == "READY" else "BLOCKED", affiliate_message, "INFO" if affiliate_status == "READY" else "BLOCKER", "CAMPAIGN"))
        disclosure_ready = bool(creative.disclosure_text and creative.disclosure_text.strip())
        checks.append(self._item("DISCLOSURE_READY", "PASS" if disclosure_ready else "BLOCKED", "Disclosure configurado." if disclosure_ready else "Configure o disclosure obrigatório.", "INFO" if disclosure_ready else "BLOCKER", "CREATIVE"))

        placement = CreativeDistributionPlan._placement(channel, format)
        variant = ChannelAssetAdaptationEngine(self.db).current_variant(creative_id, channel, "ORGANIC", placement, format)
        preview_ready = bool(has_asset and variant and variant.get("adaptationStatus") == "UP_TO_DATE")
        checks.append(self._item("FINAL_PREVIEW_AVAILABLE", "PASS" if preview_ready else "WARNING", "Preview final disponível." if preview_ready else "Gere a variante para revisar o preview final.", "INFO" if preview_ready else "WARNING", "CHANNEL_VARIANT"))

        blockers = [item for item in checks if item["status"] == "BLOCKED"]
        warnings = [item for item in checks if item["status"] == "WARNING"]
        status = "BLOCKED" if blockers else "READY_WITH_WARNINGS" if warnings else "READY"
        return {"creativeId": creative_id, "channel": channel, "format": format, "status": status, "checks": checks, "blockers": blockers, "warnings": warnings, "destinationStrategy": strategy}
