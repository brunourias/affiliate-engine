from __future__ import annotations

from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
from apps.api.app.core.config import settings
from apps.api.app.db.models import CuratorCandidate, CuratorEvidence
from apps.api.app.integrations.mercado_livre.catalog_discovery import MercadoLivreCatalogDiscoveryService
from apps.api.app.services.operations import log_decision
from apps.api.app.services.preferred_radar_execution import PreferredRadarExecutionService
from apps.api.app.services.triage import CandidateTriageService

class OpportunityOrchestrationService:
    def __init__(self,db:Session, preferred=None, discovery=None):
        self.db=db; self.preferred=preferred or PreferredRadarExecutionService(db); self.discovery=discovery or MercadoLivreCatalogDiscoveryService(db)
    def run_preferred(self):
        oid=str(uuid4()); log_decision(self.db,"OPERATOR","SYSTEM","OPPORTUNITY_ORCHESTRATION_STARTED",metadata={"orchestrationId":oid})
        preferred=self.preferred.run()
        if preferred["status"]=="NO_PREFERRED_CATEGORIES": return {"orchestrationId":oid,"status":"NO_PREFERRED_CATEGORIES","preferredRadar":preferred,"runsProcessed":0,"opportunities":[],"failures":[]}
        totals={k:0 for k in ("productsFoundRaw","productsSelected","candidatesCreated","candidatesReused")}; failures=list(preferred["failures"]); processed=[]
        for run in preferred["runs"]:
            if run["status"] not in {"COMPLETED","PARTIAL"}: continue
            try:
                found=self.discovery.resolve_run(run["runId"]); triaged=CandidateTriageService(self.db).triage_run(run["runId"])
                for key in totals: totals[key]+=found[key]
                processed.append((run,triaged))
            except Exception as exc: failures.append({"runId":run["runId"],"reasonCode":type(exc).__name__})
        run_ids=[r["runId"] for r,_ in processed]
        unique_candidates=self._unique_candidate_count(run_ids)
        opportunities=self._opportunities(run_ids, settings.opportunity_review_limit)
        status="FAILED" if not processed else "PARTIAL" if failures or preferred["status"]=="PARTIAL" else "COMPLETED"
        result={"orchestrationId":oid,"status":status,"preferredRadar":{"runsCreated":preferred["runsCreated"],"signalsFound":preferred["signalsFound"]},"runsProcessed":len(processed),"runsSucceeded":sum(r["status"]=="COMPLETED" for r,_ in processed),"runsPartial":sum(r["status"]=="PARTIAL" for r,_ in processed),"runsFailed":len(failures),**totals,"candidatesTriaged":sum(x[1]["candidatesEvaluated"] for x in processed),"uniqueCandidates":unique_candidates,"reviewQueueLimit":settings.opportunity_review_limit,"opportunities":opportunities,"failures":failures}
        log_decision(self.db,"SYSTEM","SYSTEM",f"OPPORTUNITY_ORCHESTRATION_{status}",metadata={"orchestrationId":oid,"runIds":[r["runId"] for r,_ in processed],"runsProcessed":len(processed),"productsSelected":totals["productsSelected"],"candidatesCreated":totals["candidatesCreated"],"candidatesReused":totals["candidatesReused"],"uniqueCandidates":result["uniqueCandidates"],"opportunitiesSelected":len(opportunities),"failureCount":len(failures)})
        self.db.commit(); return result
    def queue(self,limit=20,review_status="PENDING"): return self._opportunities(None,limit,review_status)
    def review_summary(self):
        rows=list(self.db.scalars(self._eligible_query()))
        counts={"pending":0,"investigate":0,"dismissed":0,"commercialReview":0}
        for candidate in rows:
            status=candidate.opportunity_review_status or "PENDING"
            counts[{"PENDING":"pending","INVESTIGATE":"investigate","DISMISSED":"dismissed","COMMERCIAL_REVIEW":"commercialReview"}[status]]+=1
        return counts
    @staticmethod
    def _eligible_query():
        return select(CuratorCandidate).where(CuratorCandidate.status!="ARCHIVED",CuratorCandidate.triage_marked_for_enrichment.is_(True),CuratorCandidate.triage_status.in_(("TRIAGE_HIGH","TRIAGE_MEDIUM")))
    def _opportunities(self,run_ids,limit,review_status="PENDING"):
        q=self._eligible_query()
        if review_status != "ALL": q=q.where(CuratorCandidate.opportunity_review_status==review_status)
        rows=list(self.db.scalars(q))
        out=[]
        for c in rows:
            signals=list(self.db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id==c.id,CuratorEvidence.evidence_type=="MARKET_SIGNAL")))
            ids={str((x.value_json or {}).get("sourceRadarRunId")) for x in signals if (x.value_json or {}).get("sourceRadarRunId")}
            if run_ids is not None and not ids.intersection(run_ids): continue
            categories={str((x.value_json or {}).get("categoryExternalId")) for x in signals if (x.value_json or {}).get("categoryExternalId")}
            binding=self.db.scalar(select(CuratorEvidence).where(CuratorEvidence.candidate_id==c.id,CuratorEvidence.evidence_type=="MARKETPLACE_LISTING_BINDING"))
            b=dict(binding.value_json or {}) if binding else {}
            relevance_values=[(x.value_json or {}).get("discoveryRelevanceScore") for x in signals if (x.value_json or {}).get("discoveryRelevanceScore") is not None]
            relevance=max(relevance_values) if relevance_values else None
            out.append({"candidateId":c.id,"catalogProductId":c.external_id,"title":c.working_title,"triageScore":c.triage_score,"triageStatus":c.triage_status,"relevanceScore":relevance,"sourceRunIds":sorted(ids),"sourceCategoryIds":sorted(categories),"sourceCount":len(ids),"commercialBindingPresent":bool(binding),"sourceItemId":b.get("sourceItemId") or b.get("itemId"),"evidenceStatus":c.evidence_status,"evidenceLevel":c.evidence_level,"triageEvaluatedAt":c.triage_evaluated_at,"opportunityReviewStatus":c.opportunity_review_status or "PENDING","opportunityReviewedAt":c.opportunity_reviewed_at,"opportunityReviewReason":c.opportunity_review_reason,"commercialAnalysisStatus":c.commercial_analysis_status or "NOT_STARTED","commercialAnalysisLastRunAt":c.commercial_analysis_last_run_at,"commercialAnalysisBlocker":c.commercial_analysis_blocker,"campaignHandoffStatus":c.campaign_handoff_status or "NOT_DECIDED","campaignHandoffAssessmentId":c.campaign_handoff_assessment_id,"campaignHandoffReviewedAt":c.campaign_handoff_reviewed_at,"campaignHandoffReason":c.campaign_handoff_reason})
        return sorted(out,key=lambda x:(-(x["triageScore"] or -1),x["triageStatus"] or "",-(x["relevanceScore"] if x["relevanceScore"] is not None else -1),str(x["triageEvaluatedAt"] or ""),x["candidateId"]))[:max(1,limit)]
    def _unique_candidate_count(self, run_ids):
        rows=self.db.scalars(select(CuratorEvidence.candidate_id).where(CuratorEvidence.evidence_type=="MARKET_SIGNAL")).all()
        return len({candidate_id for candidate_id in rows if any((e.value_json or {}).get("sourceRadarRunId") in run_ids for e in self.db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id==candidate_id,CuratorEvidence.evidence_type=="MARKET_SIGNAL")))})
