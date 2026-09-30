from types import SimpleNamespace
from apps.api.app.db.models import CuratorCandidate, CuratorEvidence
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.opportunity_orchestration import OpportunityOrchestrationService
from uuid import UUID

class Preferred:
 def __init__(self,status="COMPLETED"):self.status=status
 def run(self):return {"status":self.status,"runsCreated":2,"signalsFound":4,"runs":[{"runId":"r1","categoryId":"MLB1","status":"COMPLETED","discoveredCount":2},{"runId":"r2","categoryId":"MLB2","status":"PARTIAL","discoveredCount":2}],"failures":[]}

class Discovery:
 def __init__(self,fail=None):self.calls=[];self.fail=fail
 def resolve_run(self,id):
  self.calls.append(id)
  if id==self.fail:raise RuntimeError("failure")
  return {"productsFoundRaw":3,"productsSelected":2,"candidatesCreated":1,"candidatesReused":1}

def candidate(db,id,score,status="TRIAGE_HIGH",marked=True,archived=False):
 c=CuratorCandidate(id=id,provider="MERCADO_LIVRE",site_id="MLB",source_type="CATALOG_DISCOVERY",entity_type="PRODUCT",external_id="MLB"+id[-1]*6,working_title=id,status="ARCHIVED" if archived else "NEW",triage_score=score,triage_status=status,triage_marked_for_enrichment=marked);db.add(c);db.flush();return c
def signal(db,c,run,cat,relevance=90):db.add(CuratorEvidence(candidate_id=c.id,evidence_type="MARKET_SIGNAL",source_kind="MERCADO_LIVRE_OFFICIAL_API",source_reference=run,value_json={"sourceRadarRunId":run,"categoryExternalId":cat,"discoveryRelevanceScore":relevance},confidence="HIGH",verification_status="VERIFIED"))

def test_queue_deduplicates_sources_orders_and_excludes_ineligible():
 with SessionLocal() as db:
  a=candidate(db,"a",90);b=candidate(db,"b",80,"TRIAGE_MEDIUM");candidate(db,"c",99,"TRIAGE_LOW");candidate(db,"d",99,marked=False);candidate(db,"e",99,archived=True)
  signal(db,a,"r1","MLB1");signal(db,a,"r2","MLB2",80);signal(db,b,"r1","MLB1");db.commit()
  rows=OpportunityOrchestrationService(db).queue(10)
  assert [x["candidateId"] for x in rows]==["a","b"]
  assert rows[0]["sourceRunIds"]==["r1","r2"] and rows[0]["sourceCategoryIds"]==["MLB1","MLB2"] and rows[0]["sourceCount"]==2

def test_orchestration_processes_runs_and_is_partial_on_discovery_failure(monkeypatch):
 with SessionLocal() as db:
  a=candidate(db,"a",90);signal(db,a,"r1","MLB1");db.commit(); discovery=Discovery("r2")
  monkeypatch.setattr("apps.api.app.services.opportunity_orchestration.CandidateTriageService.triage_run",lambda self,id:{"candidatesEvaluated":1})
  result=OpportunityOrchestrationService(db,Preferred(),discovery).run_preferred()
  assert discovery.calls==["r1","r2"] and result["status"]=="PARTIAL" and result["runsProcessed"]==1 and result["runsFailed"]==1

def test_no_preferred_categories_returns_without_discovery():
 with SessionLocal() as db:
  discovery=Discovery(); result=OpportunityOrchestrationService(db,Preferred("NO_PREFERRED_CATEGORIES"),discovery).run_preferred()
  assert result["status"]=="NO_PREFERRED_CATEGORIES" and discovery.calls==[]

def test_queue_limit_binding_and_missing_relevance_are_safe(monkeypatch):
 with SessionLocal() as db:
  for i in range(12):
   c=candidate(db,f"x{i}",100-i,"TRIAGE_HIGH"); signal(db,c,"r1","MLB1",90-i)
  bound=candidate(db,"bound",95); signal(db,bound,"r1","MLB1")
  db.add(CuratorEvidence(candidate_id=bound.id,evidence_type="MARKETPLACE_LISTING_BINDING",source_kind="MANUAL_OPERATOR",source_reference="MLB111",value_json={"sourceItemId":"MLB111"},confidence="HIGH",verification_status="UNVERIFIED")); db.commit()
  rows=OpportunityOrchestrationService(db).queue(10)
  assert len(rows)==10 and next(x for x in rows if x["candidateId"]=="bound")["commercialBindingPresent"] is True
  assert next(x for x in rows if x["candidateId"]=="bound")["sourceItemId"]=="MLB111"

def test_global_run_and_triage_failure_are_partial(monkeypatch):
 class GlobalPreferred(Preferred):
  def run(self):
   base=super().run(); base["runs"].append({"runId":"global","categoryId":None,"status":"COMPLETED","discoveredCount":3});base["runsCreated"]=3;return base
 with SessionLocal() as db:
  a=candidate(db,"a",90);signal(db,a,"r1","MLB1");signal(db,a,"global","MLB1");db.commit();discovery=Discovery()
  def triage(self,id):
   if id=="r2":raise RuntimeError("triage")
   return {"candidatesEvaluated":1}
  monkeypatch.setattr("apps.api.app.services.opportunity_orchestration.CandidateTriageService.triage_run",triage)
  result=OpportunityOrchestrationService(db,GlobalPreferred(),discovery).run_preferred()
  assert discovery.calls==["r1","r2","global"] and result["status"]=="PARTIAL" and result["runsProcessed"]==2
  assert result["opportunities"][0]["sourceRunIds"]==["global","r1"] and UUID(result["orchestrationId"])

def test_all_discovery_failures_return_failed(monkeypatch):
 class AllFail(Discovery):
  def resolve_run(self,id): self.calls.append(id); raise RuntimeError("failure")
 with SessionLocal() as db:
  result=OpportunityOrchestrationService(db,Preferred(),AllFail()).run_preferred()
  assert result["status"]=="FAILED" and result["runsProcessed"]==0 and UUID(result["orchestrationId"])
