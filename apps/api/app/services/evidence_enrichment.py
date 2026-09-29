from __future__ import annotations
import hashlib,json
from datetime import datetime,timezone
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session
from apps.api.app.core.config import settings
from apps.api.app.db.models import CuratorCandidate,CuratorEvidence,RadarRun,RadarSignal
from apps.api.app.integrations.mercado_livre.client import MercadoLivreClient
from apps.api.app.integrations.mercado_livre.models import CapabilityResult
from apps.api.app.integrations.mercado_livre.oauth import MercadoLivreTokenManager
from apps.api.app.services.curator import refresh
from apps.api.app.services.operations import log_decision

SOURCE_KEYS=("catalog","buyBox","price","reviews","sellerReputation")
def now():return datetime.now(timezone.utc)
def fingerprint(value:dict)->str:return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()

class CandidateEvidenceEnrichmentService:
 def __init__(self,db:Session,client:MercadoLivreClient|None=None):self.db=db;self.client=client or MercadoLivreClient(token_manager=MercadoLivreTokenManager(db));self.owns=client is None
 def close(self):
  if self.owns:self.client.close()
 @staticmethod
 def _status(result:CapabilityResult):
  status="AVAILABLE" if result.status=="AVAILABLE" else "UNAVAILABLE" if result.http_status==404 else "FORBIDDEN" if result.status=="FORBIDDEN" or result.http_status==403 else "FAILED";out={"status":status}
  if result.reason_code:out["reasonCode"]=result.reason_code
  if result.http_status:out["httpStatus"]=result.http_status
  return out
 def enrich_run(self,run_id:str)->dict:
  if not self.db.get(RadarRun,run_id):raise ValueError("Execução do Radar não encontrada.")
  ids=set(self.db.scalars(select(RadarSignal.id).where(RadarSignal.radar_run_id==run_id)));linked=set(self.db.scalars(select(CuratorEvidence.candidate_id).where(CuratorEvidence.evidence_type=="MARKET_SIGNAL",CuratorEvidence.source_reference.in_(ids) if ids else False)))
  rows=list(self.db.scalars(select(CuratorCandidate).where(CuratorCandidate.id.in_(linked),CuratorCandidate.triage_marked_for_enrichment.is_(True)).order_by(CuratorCandidate.triage_score.desc(),CuratorCandidate.id).limit(max(1,settings.curator_triage_enrichment_limit))))
  result={"runId":run_id,"candidatesRequested":len(rows),"candidatesProcessed":0,"candidatesEnriched":0,"catalogAvailableCount":0,"commercialEvidenceAvailableCount":0,"candidatesWithoutBuyBox":0,"evidenceAdded":0,"evidenceChanged":0,"evidenceUnchanged":0,"priceAvailableCount":0,"reviewsAvailableCount":0,"sellerReputationAvailableCount":0,"sourceSummary":{k:{s:0 for s in ("AVAILABLE","UNAVAILABLE","FORBIDDEN","FAILED")} for k in SOURCE_KEYS},"candidates":[]}
  log_decision(self.db,"SYSTEM","RADAR_RUN","EVIDENCE_ENRICHMENT_STARTED",run_id,metadata={"runId":run_id,"candidatesRequested":len(rows)})
  for row in rows:
   summary=self._candidate(row);result["candidatesProcessed"]+=1;result["candidates"].append(summary);result["candidatesEnriched"]+=summary["sourceStatuses"]["catalog"]["status"]=="AVAILABLE";result["catalogAvailableCount"]+=summary["sourceStatuses"]["catalog"]["status"]=="AVAILABLE";result["commercialEvidenceAvailableCount"]+=summary["commercialEvidenceAvailable"];result["candidatesWithoutBuyBox"]+=summary["sourceStatuses"]["buyBox"]["status"]=="UNAVAILABLE"
   for key,val in summary["sourceStatuses"].items():result["sourceSummary"][key][val["status"]]+=1
   for key in ("evidenceAdded","evidenceChanged","evidenceUnchanged"):result[key]+=summary[key]
   result["priceAvailableCount"]+=summary["sourceStatuses"]["price"]["status"]=="AVAILABLE";result["reviewsAvailableCount"]+=summary["sourceStatuses"]["reviews"]["status"]=="AVAILABLE";result["sellerReputationAvailableCount"]+=summary["sourceStatuses"]["sellerReputation"]["status"]=="AVAILABLE";refresh(self.db,row)
   log_decision(self.db,"SYSTEM","CURATOR_CANDIDATE","CANDIDATE_ENRICHED",row.id,metadata={"runId":run_id,"candidateId":row.id,"catalogProductId":row.external_id,"observedItemId":summary["observedItemId"],"sourceStatuses":{k:v["status"] for k,v in summary["sourceStatuses"].items()},"counts":{k:summary[k] for k in ("evidenceAdded","evidenceChanged","evidenceUnchanged")}})
  log_decision(self.db,"SYSTEM","RADAR_RUN","EVIDENCE_ENRICHMENT_COMPLETED",run_id,metadata={"runId":run_id,"candidatesProcessed":result["candidatesProcessed"],"evidenceAdded":result["evidenceAdded"],"evidenceChanged":result["evidenceChanged"],"evidenceUnchanged":result["evidenceUnchanged"]});self.db.commit();return result
 def _candidate(self,c):
  statuses={key:{"status":"UNAVAILABLE"} for key in SOURCE_KEYS};out={"candidateId":c.id,"catalogProductId":c.external_id,"observedItemId":None,"observedSellerId":None,"sourceStatuses":statuses,"commercialEvidenceAvailable":False,"evidenceAdded":0,"evidenceChanged":0,"evidenceUnchanged":0}
  catalog=self.client.get("CATALOG_PRODUCT",f"/products/{c.external_id}",requires_auth=True);statuses["catalog"]=self._status(catalog)
  if catalog.status!="AVAILABLE" or not isinstance(catalog.data,dict):return out
  box=catalog.data.get("buy_box_winner")
  # A buy box is optional commercial data: its absence is not a candidate failure and does not affect triage/ranking.
  if not isinstance(box,dict):return out
  statuses["buyBox"]={"status":"AVAILABLE"};item=str(box.get("item_id") or "") or None;seller=str(box.get("seller_id") or "") or None;out["observedItemId"]=item;out["observedSellerId"]=seller
  if isinstance(box.get("price"),(int,float)) and not isinstance(box.get("price"),bool):out["evidence"+self._temporal(c,"CURRENT_PRICE",{"catalogProductId":c.external_id,"observedItemId":item,"currency":box.get("currency_id"),"amount":box["price"]})]+=1;out["commercialEvidenceAvailable"]=True;statuses["price"]={"status":"AVAILABLE"}
  if item:
   prices=self.client.get("ITEM_PRICES",f"/items/{item}/prices",requires_auth=True)
   if statuses["price"]["status"]!="AVAILABLE":statuses["price"]=self._status(prices)
   reviews=self.client.get("ITEM_REVIEWS",f"/reviews/item/{item}",requires_auth=True,params={"catalog_product_id":c.external_id});statuses["reviews"]=self._status(reviews)
   if reviews.status=="AVAILABLE" and isinstance(reviews.data,dict):
    data=reviews.data;paging=data.get("paging") if isinstance(data.get("paging"),dict) else {};sample=data.get("reviews") if isinstance(data.get("reviews"),list) else [];value={"catalogProductId":c.external_id,"itemId":item,"ratingAverage":data.get("rating_average"),"totalReviews":paging.get("total"),"reviewsWithComment":data.get("reviews_with_comment"),"ratingLevels":data.get("rating_levels"),"sampleCount":min(len(sample),20),"reviewIds":[x.get("id") for x in sample[:20] if isinstance(x,dict) and x.get("id") is not None]};out["evidence"+self._temporal(c,"REVIEW_SUMMARY",value)]+=1;out["commercialEvidenceAvailable"]=True
  if seller:
   user=self.client.get("SELLER_REPUTATION",f"/users/{seller}",requires_auth=True);statuses["sellerReputation"]=self._status(user)
   if user.status=="AVAILABLE" and isinstance(user.data,dict) and isinstance(user.data.get("seller_reputation"),dict):out["evidence"+self._temporal(c,"SELLER_REPUTATION",{"sellerId":seller,"sellerReputation":user.data["seller_reputation"]})]+=1;out["commercialEvidenceAvailable"]=True
  return out
 def _temporal(self,c,kind,value):
  active=self.db.scalar(select(CuratorEvidence).where(CuratorEvidence.candidate_id==c.id,CuratorEvidence.evidence_type==kind,CuratorEvidence.valid_until.is_(None)).order_by(CuratorEvidence.observed_at.desc()));digest=fingerprint(value)
  if active and (active.metadata_ or {}).get("fingerprint")==digest:active.observed_at=now();return "Unchanged"
  action="Changed" if active else "Added"
  if active:active.valid_until=now()
  self.db.add(CuratorEvidence(candidate_id=c.id,evidence_type=kind,value_json=value,value_cents=round(value["amount"]*100) if kind=="CURRENT_PRICE" else None,source_kind="MERCADO_LIVRE_OFFICIAL_API",source_name="Mercado Livre official API",source_reference=f"enrichment:{kind}:{digest}",confidence="HIGH",verification_status="VERIFIED",observed_at=now(),metadata_={"fingerprint":digest}));return action
