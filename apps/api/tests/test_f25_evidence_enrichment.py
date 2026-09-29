import httpx
from sqlalchemy import select
from apps.api.app.db.models import CuratorCandidate,CuratorEvidence,RadarRun,RadarSignal
from apps.api.app.db.session import SessionLocal
from apps.api.app.integrations.mercado_livre.client import MercadoLivreClient
from apps.api.app.services.evidence_enrichment import CandidateEvidenceEnrichmentService

def setup(db,marked=True):
 run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();sig=RadarSignal(radar_run_id=run.id,provider="MERCADO_LIVRE",site_id="MLB",source_type="TREND_GLOBAL",source_capability="TEST",entity_type="QUERY",display_text="snow foam",rank=1);db.add(sig);db.flush();c=CuratorCandidate(provider="MERCADO_LIVRE",site_id="MLB",source_type="CATALOG_DISCOVERY",entity_type="PRODUCT",external_id="MLB73090001",working_title="Produto",triage_marked_for_enrichment=marked,triage_score=80);db.add(c);db.flush();db.add(CuratorEvidence(candidate_id=c.id,evidence_type="MARKET_SIGNAL",source_kind="MERCADO_LIVRE_OFFICIAL_API",source_reference=sig.id,confidence="HIGH",verification_status="VERIFIED"));db.commit();return run,c
def client(handler):return MercadoLivreClient("test",transport=httpx.MockTransport(handler))
def test_enrichment_buy_box_reviews_seller_and_idempotency():
 def h(r):
  if r.url.path.startswith("/products/"):return httpx.Response(200,json={"buy_box_winner":{"item_id":"MLBITEM","seller_id":42,"price":99.9,"currency_id":"BRL","regular_amount":150}})
  if r.url.path.startswith("/items/"):return httpx.Response(403,json={"error":"access_denied"})
  if r.url.path.startswith("/reviews/"):return httpx.Response(200,json={"rating_average":4.7,"paging":{"total":9},"reviews":[{"id":1}]})
  return httpx.Response(200,json={"seller_reputation":{"level_id":"5_green","transactions":{"total":10}}})
 with SessionLocal() as db:
  run,c=setup(db);s=CandidateEvidenceEnrichmentService(db,client(h));one=s.enrich_run(run.id);two=s.enrich_run(run.id);ev=list(db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id==c.id)))
  assert one["priceAvailableCount"]==1 and one["reviewsAvailableCount"]==1 and one["sellerReputationAvailableCount"]==1
  assert one["candidates"][0]["sourceStatuses"]["price"]["status"]=="AVAILABLE" and two["evidenceUnchanged"]==3
  assert {x.evidence_type for x in ev}>={"CURRENT_PRICE","REVIEW_SUMMARY","SELLER_REPUTATION"} and "PRICE_REFERENCE" not in {x.evidence_type for x in ev}
  s.close()
def test_without_buy_box_is_unavailable_and_unmarked_candidate_is_skipped():
 def h(r):return httpx.Response(200,json={"buy_box_winner":None})
 with SessionLocal() as db:
  run,c=setup(db);extra=CuratorCandidate(provider="MERCADO_LIVRE",site_id="MLB",source_type="MANUAL",entity_type="PRODUCT",external_id="MLB73090002",triage_marked_for_enrichment=False);db.add(extra);db.commit();s=CandidateEvidenceEnrichmentService(db,client(h));out=s.enrich_run(run.id)
  assert out["candidatesRequested"]==1 and out["candidatesWithoutBuyBox"]==1 and out["candidates"][0]["sourceStatuses"]["buyBox"]["status"]=="UNAVAILABLE"
  s.close()

def test_optional_buy_box_absence_keeps_catalogs_available_without_commercial_evidence():
 def h(r):return httpx.Response(200,json={"buy_box_winner":None})
 with SessionLocal() as db:
  run,c=setup(db)
  for index in range(9):
   extra=CuratorCandidate(provider="MERCADO_LIVRE",site_id="MLB",source_type="CATALOG_DISCOVERY",entity_type="PRODUCT",external_id=f"MLB73090{index:03d}",working_title=f"Produto {index}",triage_marked_for_enrichment=True,triage_score=79-index);db.add(extra);db.flush();db.add(CuratorEvidence(candidate_id=extra.id,evidence_type="MARKET_SIGNAL",source_kind="MERCADO_LIVRE_OFFICIAL_API",source_reference=db.scalar(select(RadarSignal.id).where(RadarSignal.radar_run_id==run.id)),confidence="HIGH",verification_status="VERIFIED"))
  db.commit();s=CandidateEvidenceEnrichmentService(db,client(h));out=s.enrich_run(run.id)
  assert out["candidatesProcessed"]==10 and out["catalogAvailableCount"]==10
  assert out["commercialEvidenceAvailableCount"]==0 and out["candidatesWithoutBuyBox"]==10
  assert out["evidenceAdded"]==out["evidenceChanged"]==out["evidenceUnchanged"]==0
  s.close()

def test_forbidden_optional_source_is_not_reported_as_unavailable():
 def h(r):
  if r.url.path.startswith("/products/"):return httpx.Response(200,json={"buy_box_winner":{"item_id":"MLBITEM","seller_id":42}})
  if r.url.path.startswith("/items/"):return httpx.Response(403,json={"error":"access_denied"})
  if r.url.path.startswith("/reviews/"):return httpx.Response(403,json={"error":"access_denied"})
  return httpx.Response(403,json={"error":"access_denied"})
 with SessionLocal() as db:
  run,_=setup(db);s=CandidateEvidenceEnrichmentService(db,client(h));out=s.enrich_run(run.id)["candidates"][0]
  assert out["sourceStatuses"]["price"]["status"]=="FORBIDDEN"
  assert out["sourceStatuses"]["reviews"]["status"]=="FORBIDDEN"
  assert out["sourceStatuses"]["sellerReputation"]["status"]=="FORBIDDEN"
  s.close()
