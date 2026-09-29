from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db.models import Campaign, Creative, CuratorCandidate, CuratorEvidence
from apps.api.app.services.static_creative import ProductMediaAnalyzer
from apps.api.app.services.mercado_livre_commercial import OFFICIAL_SOURCE


EVIDENCE_MAP = {
    "CURRENT_PRICE": "currentPrice", "PRICE_REFERENCE": "priceReference", "RATING": "rating",
    "REVIEW_COUNT": "reviewCount", "SOLD_QUANTITY": "soldQuantity", "SHIPPING": "shipping",
    "PRODUCT_FEATURE": "claim", "DESCRIPTION": "claim", "ATTRIBUTE": "attribute", "CATALOG_ATTRIBUTE":"attribute",
    "LISTING_TITLE": "title", "CATALOG_TITLE":"title", "LISTING_PICTURE": "picture", "CATALOG_PICTURE":"picture",
    "LISTING_DATA": "listingData", "CATALOG_DATA":"catalogData",
}


class CommercialEvidenceMapper:
    def __init__(self, rows): self.rows = rows

    @staticmethod
    def _stale(row) -> bool:
        return bool(row.valid_until and row.valid_until.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc))

    def mapped(self):
        result = []
        for row in self.rows:
            field = EVIDENCE_MAP.get(row.evidence_type)
            if not field: continue
            value = row.value_cents if field in {"currentPrice", "priceReference"} else row.value_number if row.value_number is not None else row.value_text if row.value_text is not None else row.value_json
            result.append({"field":field,"value":value,"status":"STALE" if self._stale(row) else "KNOWN","evidenceIds":[row.id],"sourceKind":row.source_kind,"sourceReference":row.source_reference or row.id,"observedAt":row.observed_at,"confidence":row.confidence,"verificationStatus":row.verification_status,"evidenceType":row.evidence_type,"metadata":row.metadata_ or {}})
        return result


class MarketplaceCommercialSnapshotService:
    def __init__(self, db: Session): self.db = db

    def build(self, creative_id: str) -> dict:
        creative = self.db.get(Creative, creative_id)
        if not creative: raise ValueError("CREATIVE_NOT_FOUND")
        campaign = self.db.get(Campaign, creative.campaign_id); candidate = self.db.get(CuratorCandidate, campaign.candidate_id)
        rows = self.db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id == candidate.id)).all()
        mapped = CommercialEvidenceMapper(rows).mapped(); by_field = {}
        for item in sorted(mapped, key=lambda x: (x["sourceKind"] == OFFICIAL_SOURCE, str(x["observedAt"] or "")), reverse=True):
            if item["status"] != "STALE" and item["verificationStatus"] == "VERIFIED": by_field.setdefault(item["field"], item)
        official_title = by_field.get("title")
        title, title_source = ((official_title["value"], OFFICIAL_SOURCE) if official_title else (candidate.working_title, "CANDIDATE_WORKING_TITLE") if candidate.working_title else (candidate.source_display_text, "CANDIDATE_SOURCE_DISPLAY_TEXT") if candidate.source_display_text else (creative.title, "CREATIVE_TITLE"))
        bundle = ProductMediaAnalyzer().analyze(self.db, candidate.id)
        images = [{"assetId":x.get("assetId"),"source":"MEDIA_ASSET","width":x.get("width"),"height":x.get("height"),"aspectRatio":x.get("aspectRatio"),"active":not bool(x.get("warnings")),"quality":x.get("qualityScore"),"role":"PRIMARY" if x.get("classification")=="HERO_IMAGE" else "DETAIL" if x.get("classification")=="DETAIL_IMAGE" else "UNKNOWN"} for x in bundle.get("assets",[]) if x.get("mediaType")=="PRODUCT_IMAGE"]
        official_pictures = sorted((x for x in mapped if x["field"] == "picture" and x["status"] == "KNOWN"), key=lambda x: x["value"].get("position", 0))
        images = [{"assetId":None,"pictureId":x["value"].get("id"),"source":OFFICIAL_SOURCE,
                   "url":x["value"].get("secure_url") or x["value"].get("url"),"width":x["value"].get("width"),
                   "height":x["value"].get("height"),"aspectRatio":(x["value"].get("width") / x["value"].get("height")) if x["value"].get("width") and x["value"].get("height") else None,
                   "position":x["value"].get("position"),"active":True,"quality":"UNKNOWN","role":"UNKNOWN","provenance":x} for x in official_pictures] or images
        current = by_field.get("currentPrice"); reference = by_field.get("priceReference") if by_field.get("priceReference",{}).get("metadata",{}).get("semantic") == "ORIGINAL_PRICE" else None
        affiliate_rows = sorted((row for row in rows if row.evidence_type == "AFFILIATE_DESTINATION"), key=lambda row: str(row.observed_at or ""), reverse=True)
        affiliate_data = (affiliate_rows[0].value_json or {}) if affiliate_rows else {}
        binding_rows = sorted((row for row in rows if row.evidence_type == "MARKETPLACE_LISTING_BINDING"), key=lambda row: str(row.observed_at or ""), reverse=True)
        binding_data = (binding_rows[0].value_json or {}) if binding_rows else {}
        affiliate = affiliate_data.get("affiliateUrl")
        destination = affiliate_data.get("destinationUrl")
        strategy = affiliate_data.get("destinationStrategy") or "UNKNOWN"
        affiliate_status = {"status":"READY" if affiliate_data.get("affiliateValidationStatus") == "VALID" and destination else affiliate_data.get("affiliateValidationStatus") or "UNKNOWN",
                            "reasonCode":affiliate_data.get("failureCode")}
        attributes = [{"key":x["metadata"].get("attributeKey",x["evidenceType"]),"label":x["metadata"].get("label",x["evidenceType"]),"value":x["value"],"status":x["status"],"evidenceIds":x["evidenceIds"]} for x in mapped if x["field"] == "attribute" and x["status"] == "KNOWN"]
        claims = [{"claimId":x["evidenceIds"][0],"text":str(x["value"]),"category":"PRODUCT_FEATURE","supportStatus":"SUPPORTED","evidenceIds":x["evidenceIds"],"confidence":x["confidence"],"allowedForCreative":True} for x in mapped if x["field"] == "claim" and x["status"] == "KNOWN" and x["verificationStatus"] == "VERIFIED"]
        known_fields = []
        if title: known_fields.append("title")
        if images: known_fields.append("images")
        if current: known_fields.append("pricing.currentPrice")
        if destination: known_fields.append("destination.affiliateUrl")
        listing = by_field.get("listingData", {}).get("value") or {}
        if listing.get("available_quantity") is not None:known_fields.append("inventory.availableQuantity")
        if listing.get("seller_id") is not None:known_fields.append("seller.id")
        unknown = [x for x in ["pricing.currentPrice","pricing.originalPrice","pricing.discountPercent","pricing.installments","inventory.availableQuantity","seller.id","seller.reputation","logistics.shippingStatus","logistics.freeShipping","logistics.fulfillment","socialProof.rating","socialProof.reviewCount","socialProof.soldQuantity","destination.destinationStrategy"] if x not in known_fields]
        discount = round((reference["value"] - current["value"]) * 100 / reference["value"]) if current and reference and reference["value"] > current["value"] else None
        shipping = listing.get("shipping") or {}
        commercial_completeness = binding_data.get("commercialCompleteness") or ("PARTIAL" if any((current,listing,by_field.get("rating"))) else "UNAVAILABLE")
        source_item_id=binding_data.get("sourceItemId") or binding_data.get("itemId")
        return {"snapshotId":f"derived:{creative_id}","creativeId":creative.id,"campaignId":creative.campaign_id,"candidateId":candidate.id,"assessmentId":None,"provider":candidate.provider,"siteId":candidate.site_id,"entityType":candidate.entity_type,"externalId":candidate.external_id,"catalogProductId":binding_data.get("catalogProductId"),"sourceItemId":source_item_id,"itemId":source_item_id,"sourceUrl":binding_data.get("sourcePermalink") or candidate.source_url,"itemDetailsStatus":binding_data.get("itemDetailsStatus") or "UNKNOWN","catalogProductStatus":binding_data.get("catalogProductStatus") or "UNKNOWN","commercialCompleteness":commercial_completeness,"title":title,"titleProvenance":{"source":title_source,"evidenceIds":official_title["evidenceIds"] if official_title else []},"images":images,"pricing":{"status":"KNOWN" if current else "UNKNOWN","currentPrice":current["value"] if current else None,"originalPrice":reference["value"] if reference else None,"discountPercent":discount,"currency":current["metadata"].get("currency") if current else None,"installments":None,"provenance":current},"inventory":{"status":"KNOWN" if listing.get("available_quantity") is not None else "UNKNOWN","availableQuantity":listing.get("available_quantity")},"seller":{"status":"KNOWN" if listing.get("seller_id") is not None else "UNKNOWN","id":listing.get("seller_id"),"reputation":None},"logistics":{"status":"KNOWN" if shipping else "UNKNOWN","shippingStatus":shipping.get("status"),"freeShipping":shipping.get("free_shipping"),"fulfillment":shipping.get("logistic_type"),"mode":shipping.get("mode")},"socialProof":{"status":"KNOWN" if any((by_field.get("rating"),by_field.get("reviewCount"),listing.get("sold_quantity") is not None)) else "UNKNOWN","rating":by_field.get("rating",{}).get("value"),"reviewCount":by_field.get("reviewCount",{}).get("value"),"soldQuantity":listing.get("sold_quantity")},"attributes":attributes,"commercialClaims":claims,"destination":{"sourcePermalink":candidate.source_url,"affiliateUrl":affiliate,"affiliateUrlSource":affiliate_data.get("affiliateUrlSource"),"affiliateValidationStatus":affiliate_data.get("affiliateValidationStatus") or "UNKNOWN","affiliateItemId":affiliate_data.get("affiliateItemId"),"destinationUrl":destination,"destinationStrategy":strategy,"affiliateStatus":affiliate_status},"evidenceCoverage":{"known":len(known_fields),"total":len(known_fields)+len(unknown),"coveragePercent":round(len(known_fields)*100/(len(known_fields)+len(unknown)))},"unknownFields":unknown,"observedAt":max((x.observed_at for x in rows),default=None),"generatedAt":datetime.now(timezone.utc),"provenance":[x for x in mapped]}
