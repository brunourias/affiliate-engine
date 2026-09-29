from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.config import settings
from apps.api.app.db.models import CuratorCandidate, MarketplaceCategory, RadarRun, RadarSignal
from apps.api.app.integrations.mercado_livre.catalog_discovery import MercadoLivreCatalogDiscoveryService
from apps.api.app.integrations.mercado_livre.catalog_discovery_policy import BLOCKED_POLICY, catalog_discovery_eligibility
from apps.api.app.integrations.mercado_livre.client import MercadoLivreClient
from apps.api.app.integrations.mercado_livre.oauth import MercadoLivreTokenManager
from apps.api.app.services.operations import log_decision
from apps.api.app.services.triage import CandidateTriageService


def now(): return datetime.now(timezone.utc)


class DirectedOpportunitySearchService:
    def __init__(self, db: Session, client: MercadoLivreClient | None = None):
        self.db=db; self.client=client or MercadoLivreClient(token_manager=MercadoLivreTokenManager(db)); self.owns=client is None

    def close(self):
        if self.owns: self.client.close()

    def search(self, query: str, category_id: str | None = None) -> dict:
        query=" ".join(query.split())
        if not 2 <= len(query) <= 200: raise ValueError("QUERY_INVALID")
        if category_id and not self.db.scalar(select(MarketplaceCategory.id).where(MarketplaceCategory.provider=="MERCADO_LIVRE", MarketplaceCategory.external_category_id==category_id)):
            raise ValueError("CATEGORY_NOT_FOUND")
        eligibility=catalog_discovery_eligibility(query)
        run=RadarRun(provider="MERCADO_LIVRE",site_id=settings.meli_site_id or "MLB",trigger_type="DIRECTED_SEARCH",status="RUNNING",requested_category_id=category_id,sources_requested=["DOMAIN_DISCOVERY","CATALOG_SEARCH"],sources_succeeded=[],sources_failed=[])
        self.db.add(run); self.db.flush()
        if eligibility.status == BLOCKED_POLICY:
            run.status="COMPLETED"; run.finished_at=now(); run.sources_succeeded=[]
            log_decision(self.db,"OPERATOR","RADAR_RUN","DIRECTED_SEARCH_BLOCKED",run.id,metadata={"query":query,"runId":run.id,"requestedCategoryId":category_id})
            self.db.commit(); return {"runId":run.id,"query":query,"policyStatus":BLOCKED_POLICY,"categoryContext":{"requestedCategoryId":category_id,"mode":"AUTO" if not category_id else "CATEGORY"},"topCandidates":[]}
        result=self.client.get("DOMAIN_DISCOVERY","/sites/MLB/domain_discovery/search",requires_auth=True,params={"q":query,"limit":3})
        suggestions=result.data if result.status=="AVAILABLE" and isinstance(result.data,list) else []
        selected=None
        for suggestion in suggestions:
            if not isinstance(suggestion,dict) or not suggestion.get("domain_id"): continue
            if category_id and not self._in_category_context(str(suggestion.get("category_id") or ""), category_id): continue
            selected=suggestion; break
        if category_id and not selected:
            run.status="COMPLETED"; run.finished_at=now(); run.sources_failed=["DOMAIN_DISCOVERY"]
            self.db.commit(); return {"runId":run.id,"query":query,"policyStatus":"ALLOWED","reasonCode":"NO_MATCH_IN_CATEGORY","message":"Não encontramos um domínio compatível com a categoria selecionada.","categoryContext":{"requestedCategoryId":category_id,"mode":"CATEGORY"},"topCandidates":[]}
        payload={"query":query,"mode":"DIRECTED_SEARCH","domainId":selected.get("domain_id") if selected else None,"domainName":selected.get("domain_name") if selected else None,"predictedCategoryId":selected.get("category_id") if selected else None,"predictedCategoryName":selected.get("category_name") if selected else None,"requestedCategoryId":category_id}
        signal=RadarSignal(radar_run_id=run.id,provider="MERCADO_LIVRE",site_id="MLB",source_type="DIRECTED_QUERY",source_capability="DOMAIN_DISCOVERY",category_external_id=category_id,entity_type="QUERY",display_text=query,rank=1,source_payload=payload)
        self.db.add(signal); self.db.flush(); run.status="COMPLETED"; run.finished_at=now(); run.sources_succeeded=["CATALOG_SEARCH"] + (["DOMAIN_DISCOVERY"] if selected else []); run.sources_failed=[] if selected else ["DOMAIN_DISCOVERY"]
        log_decision(self.db,"OPERATOR","RADAR_RUN","DIRECTED_SEARCH_STARTED",run.id,metadata={"query":query,"runId":run.id,"requestedCategoryId":category_id,"domainId":payload["domainId"],"predictedCategoryId":payload["predictedCategoryId"]})
        self.db.commit()
        discovery=MercadoLivreCatalogDiscoveryService(self.db,self.client).resolve_run(run.id)
        triage=CandidateTriageService(self.db).triage_run(run.id)
        tops=[{"candidateId":x["candidateId"],"title":x["title"],"triageScore":x["triageScore"],"triageStatus":x["triageStatus"],"reasons":x["reasons"]} for x in triage["topCandidates"]]
        for top in tops:
            candidate=self.db.get(CuratorCandidate,top['candidateId']); top['catalogProductId']=candidate.external_id
        log_decision(self.db,"SYSTEM","RADAR_RUN","DIRECTED_SEARCH_COMPLETED",run.id,metadata={"query":query,"runId":run.id,"requestedCategoryId":category_id,"domainId":payload["domainId"],"predictedCategoryId":payload["predictedCategoryId"],"productsSelected":discovery["productsSelected"],"candidatesCreated":discovery["candidatesCreated"],"candidatesReused":discovery["candidatesReused"]})
        self.db.commit()
        return {"runId":run.id,"query":query,"policyStatus":"ALLOWED","categoryContext":{"requestedCategoryId":category_id,"mode":"AUTO" if not category_id else "CATEGORY",**{k:payload[k] for k in ('domainId','domainName','predictedCategoryId','predictedCategoryName')},"domainResolutionStatus":"AVAILABLE" if selected else "UNAVAILABLE"},**{k:discovery[k] for k in ('productsFoundRaw','productsSelected','candidatesCreated','candidatesReused')},"topCandidates":tops}

    def _in_category_context(self, predicted: str, requested: str) -> bool:
        if not predicted: return False
        result=self.client.get("CATEGORY_DETAILS",f"/categories/{predicted}",requires_auth=True)
        path=result.data.get("path_from_root",[]) if result.status=="AVAILABLE" and isinstance(result.data,dict) else []
        return any(isinstance(node,dict) and node.get("id")==requested for node in path)
