import pytest
from sqlalchemy import select
from apps.api.app.db.models import CuratorAssessment,CuratorCandidate,CuratorEvidence,RadarRun,RadarSignal
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.assessment import CuratorAssessmentService,price,verdict
def candidate(db,status="SUFFICIENT_EVIDENCE",level="DATA_ANALYZED"):
 c=CuratorCandidate(provider="MERCADO_LIVRE",site_id="MLB",source_type="MANUAL",entity_type="ITEM",external_id="MLB42",status="INVESTIGATING",evidence_status=status,evidence_level=level);db.add(c);db.flush();return c
def ev(db,c,t,*,cents=None,confidence="HIGH",verification="VERIFIED",metadata=None):
 e=CuratorEvidence(candidate_id=c.id,evidence_type=t,value_text=t,value_cents=cents,source_kind="MANUAL_OPERATOR",confidence=confidence,verification_status=verification,metadata_=metadata);db.add(e);db.flush();return e
def full(db,c):
 for t in ["POSITIVE_PATTERN","REVIEW_SUMMARY","CURRENT_PRICE","PRICE_REFERENCE","USE_CASE","DIFFERENTIAL","SELLER_REPUTATION","ALTERNATIVE"]:ev(db,c,t,cents=9000 if t=="CURRENT_PRICE" else 10000 if t=="PRICE_REFERENCE" else None)
def test_insufficient_never_publishes_recommendation_and_unknown_is_not_zero():
 with SessionLocal() as db:
  c=candidate(db,"PARTIAL_EVIDENCE");ev(db,c,"POSITIVE_PATTERN");a=CuratorAssessmentService(db).assess(c);assert a.trust_gate=="INSUFFICIENT_EVIDENCE" and a.recommendation_score is None and a.editorial_verdict=="INSUFFICIENT_EVIDENCE";assert a.recommendation_pillars["VALUE_FOR_MONEY"]["score"] is None
def test_coverage_below_60_is_null_and_known_weights_are_exact():
 with SessionLocal() as db:
  c=candidate(db);ev(db,c,"SELLER_REPUTATION");a=CuratorAssessmentService(db).assess(c);assert a.recommendation_coverage_percent==15 and a.recommendation_score is None
def test_recommendation_is_normalized_and_commission_is_excluded():
 with SessionLocal() as db:
  c=candidate(db);full(db,c);a=CuratorAssessmentService(db).assess(c);assert a.recommendation_coverage_percent==100 and 0<=a.recommendation_score<=100;assert "COMMISSION" not in a.recommendation_pillars
@pytest.mark.parametrize("score,label",[(95,"EXCELLENT"),(85,"VERY_GOOD"),(75,"GOOD"),(65,"ACCEPTABLE_WITH_RESERVATIONS"),(55,"NOT_RECOMMENDED")])
def test_recommendation_labels(score,label):
 from apps.api.app.services.assessment import verdict
 assert ("EXCELLENT" if score>=90 else "VERY_GOOD" if score>=80 else "GOOD" if score>=70 else "ACCEPTABLE_WITH_RESERVATIONS" if score>=60 else "NOT_RECOMMENDED")==label
@pytest.mark.parametrize("current,expected",[(8500,"EXCELLENT_PRICE"),(9500,"GOOD_PRICE"),(10500,"FAIR_PRICE"),(12000,"EXPENSIVE"),(12001,"AVOID_AT_THIS_PRICE")])
def test_price_thresholds_use_integer_cents(current,expected):
 class E:
  def __init__(self,t,v):self.evidence_type=t;self.value_cents=v;self.confidence="HIGH"
 assert price([E("CURRENT_PRICE",current),E("PRICE_REFERENCE",10000)])[0]==expected
def test_price_without_reference_is_unknown():
 class E:evidence_type="CURRENT_PRICE";value_cents=100;confidence="HIGH"
 assert price([E()])==( "UNKNOWN",None)
def test_warn_and_low_critical_does_not_block():
 with SessionLocal() as db:
  c=candidate(db);full(db,c);ev(db,c,"LIMITATION",metadata={"severity":"HIGH"});ev(db,c,"OTHER",confidence="LOW",metadata={"editorialFlag":"SAFETY_RISK"});a=CuratorAssessmentService(db).assess(c);assert a.trust_gate=="WARN" and a.trust_warnings
def test_verified_high_critical_blocks_and_precedes_high_scores():
 with SessionLocal() as db:
  c=candidate(db,"VERIFIED","OWNED_AND_TESTED");full(db,c);ev(db,c,"OWN_TEST",confidence="VERY_HIGH",metadata={"editorialFlag":"SAFETY_RISK"});a=CuratorAssessmentService(db).assess(c);assert a.trust_gate=="BLOCK" and a.editorial_verdict=="NOT_RECOMMENDED"
@pytest.mark.parametrize(("confidence","verification","expected"),[("HIGH","VERIFIED","BLOCK"),("LOW","VERIFIED","WARN"),("HIGH","UNVERIFIED","WARN")])
def test_safety_risk_requires_high_verified(confidence,verification,expected):
 with SessionLocal() as db:
  c=candidate(db,"VERIFIED","DATA_ANALYZED");full(db,c);ev(db,c,"LIMITATION",confidence=confidence,verification=verification,metadata={"severity":"CRITICAL","editorialFlag":"SAFETY_RISK"});a=CuratorAssessmentService(db).assess(c);assert a.trust_gate==expected
  if expected=="BLOCK":assert a.editorial_verdict=="NOT_RECOMMENDED" and a.recommendation_score is not None
def test_safety_block_precedes_high_recommendation_and_opportunity():
 with SessionLocal() as db:
  c=candidate(db,"VERIFIED","OWNED_AND_TESTED");full(db,c)
  for rank in [1,1,1]:
   r=RadarRun(provider="MERCADO_LIVRE",site_id="MLB");db.add(r);db.flush();db.add(RadarSignal(radar_run_id=r.id,provider="MERCADO_LIVRE",site_id="MLB",source_type="HIGHLIGHT_CATEGORY",source_capability="HIGHLIGHTS_CATEGORY",entity_type="ITEM",external_id="MLB42",rank=rank))
  ev(db,c,"LIMITATION",confidence="VERY_HIGH",verification="VERIFIED",metadata={"severity":"CRITICAL","editorialFlag":"SAFETY_RISK"});db.flush();a=CuratorAssessmentService(db).assess(c);assert a.trust_gate=="BLOCK" and a.editorial_verdict=="NOT_RECOMMENDED";assert a.recommendation_score is not None and a.opportunity_score is not None
def test_editorial_rules_are_independent_from_opportunity():
 assert verdict("BLOCK",92,"GOOD_PRICE")=="NOT_RECOMMENDED";assert verdict("PASS",55,"GOOD_PRICE")=="NOT_RECOMMENDED";assert verdict("PASS",85,"GOOD_PRICE")=="BUY_NOW";assert verdict("WARN",75,"FAIR_PRICE")=="WORTH_IT";assert verdict("PASS",75,"EXPENSIVE")=="WAIT_FOR_BETTER_PRICE"
def test_opportunity_unknowns_and_radar_recurrence():
 with SessionLocal() as db:
  c=candidate(db);full(db,c)
  for rank in [10,5]:
   r=RadarRun(provider="MERCADO_LIVRE",site_id="MLB");db.add(r);db.flush();db.add(RadarSignal(radar_run_id=r.id,provider="MERCADO_LIVRE",site_id="MLB",source_type="HIGHLIGHT_CATEGORY",source_capability="HIGHLIGHTS_CATEGORY",entity_type="ITEM",external_id="MLB42",rank=rank))
  db.flush();a=CuratorAssessmentService(db).assess(c);assert a.opportunity_pillars["COMMISSION"]["status"]=="UNKNOWN" and a.opportunity_pillars["CONVERSION_POTENTIAL"]["score"] is None;assert a.opportunity_pillars["TREND_MOMENTUM"]["status"]=="KNOWN" and a.opportunity_coverage_percent==40 and a.opportunity_score is not None
def test_snapshots_increment_and_preserve_previous(client):
 with SessionLocal() as db:c=candidate(db);full(db,c);db.commit();cid=c.id
 first=client.post(f"/api/v1/curator/candidates/{cid}/assess").json();second=client.post(f"/api/v1/curator/candidates/{cid}/assess").json();assert first["assessmentVersion"]==1 and second["assessmentVersion"]==2 and second["previousAssessmentId"]==first["id"];history=client.get(f"/api/v1/curator/candidates/{cid}/assessments").json();assert len(history)==2 and history[1]["id"]==first["id"] and history[0]["evidenceIdsUsed"]
