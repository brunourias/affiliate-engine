from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from apps.api.app.db.models import CuratorAssessment,CuratorEvidence,RadarSignal
from apps.api.app.services.curator import stale
from apps.api.app.services.operations import log_decision
REC={"QUALITY_RELIABILITY":(25,{"REVIEW_SUMMARY","POSITIVE_PATTERN","NEGATIVE_PATTERN","LIMITATION","OWN_TEST","TECHNICAL_SPEC"}),"VALUE_FOR_MONEY":(20,{"CURRENT_PRICE","PRICE_REFERENCE","ALTERNATIVE"}),"BUYER_EXPERIENCE":(15,{"REVIEW_SUMMARY","COMMUNITY_SIGNAL","POSITIVE_PATTERN","NEGATIVE_PATTERN"}),"UTILITY_DIFFERENTIAL":(15,{"USE_CASE","DIFFERENTIAL","TECHNICAL_SPEC","LIMITATION"}),"PURCHASE_SAFETY_SELLER":(10,{"SELLER_REPUTATION","COMMUNITY_SIGNAL","OWN_TEST"}),"ALTERNATIVES":(10,{"ALTERNATIVE","PRICE_REFERENCE","DIFFERENTIAL"})}
OPP={"DEMAND_INTEREST":20,"TREND_MOMENTUM":15,"CONVERSION_POTENTIAL":15,"CONTENT_POTENTIAL":15,"TIMING_SEASONALITY":10,"COMPETITION":10,"COMMISSION":10,"COMMERCIAL_DIFFERENTIATION":5}
CRITICAL={"SAFETY_RISK","COUNTERFEIT_RISK","SEVERE_RECURRING_DEFECT","MISLEADING_CLAIM","SELLER_HIGH_RISK","CRITICAL_INCOMPATIBILITY","CLEARLY_SUPERIOR_ALTERNATIVE","EXTREME_OVERPRICE","UNRESOLVED_CRITICAL_CONTRADICTION"}
NEG={"NEGATIVE_PATTERN","LIMITATION"};POS={"POSITIVE_PATTERN","DIFFERENTIAL","USE_CASE","OWN_TEST"};ADJ={"LOW":5,"MEDIUM":10,"HIGH":15,"VERY_HIGH":20}
def pillar(name,weight,rows):
    if not rows:return {"status":"UNKNOWN","score":None,"weight":weight,"weightedContribution":None,"evidenceIds":[],"reasons":["Sem evidência ativa para este pilar."]}
    score=50
    for e in rows:
        delta=ADJ[e.confidence]*(Decimal("1") if e.verification_status=="VERIFIED" else Decimal("0.6") if e.verification_status=="UNVERIFIED" else Decimal("0.25"));score+=int(-delta if e.evidence_type in NEG else delta if e.evidence_type in POS else 0)
    score=max(0,min(100,score));return {"status":"KNOWN","score":score,"weight":weight,"weightedContribution":score*weight/100,"evidenceIds":[e.id for e in rows],"reasons":[f"{len(rows)} evidência(s) ativa(s) sustentam o pilar."]}
def price(rows):
    current=next((e.value_cents for e in rows if e.evidence_type=="CURRENT_PRICE" and e.value_cents is not None),None);reference=next((e.value_cents for e in rows if e.evidence_type=="PRICE_REFERENCE" and e.value_cents is not None and e.confidence in {"HIGH","VERY_HIGH"}),None)
    if current is None or not reference:return "UNKNOWN",None
    ratio=Decimal(current)/Decimal(reference)
    return ("EXCELLENT_PRICE" if ratio<=Decimal("0.85") else "GOOD_PRICE" if ratio<=Decimal("0.95") else "FAIR_PRICE" if ratio<=Decimal("1.05") else "EXPENSIVE" if ratio<=Decimal("1.20") else "AVOID_AT_THIS_PRICE"),None
def verdict(gate,score,pv):
    if gate=="INSUFFICIENT_EVIDENCE" or score is None:return "INSUFFICIENT_EVIDENCE"
    if gate=="BLOCK" or score<60:return "NOT_RECOMMENDED"
    if score>=80 and pv in {"EXCELLENT_PRICE","GOOD_PRICE"}:return "BUY_NOW"
    if score>=70 and pv in {"EXPENSIVE","AVOID_AT_THIS_PRICE"}:return "WAIT_FOR_BETTER_PRICE"
    if score>=70 and pv in {"EXCELLENT_PRICE","GOOD_PRICE","FAIR_PRICE","UNKNOWN"}:return "WORTH_IT"
    return "NOT_RECOMMENDED"
class CuratorAssessmentService:
 def __init__(self,db:Session):self.db=db
 def assess(self,c):
    rows=[e for e in self.db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id==c.id)) if not stale(e)];ids=[e.id for e in rows]
    warnings=[];blocks=[]
    for e in rows:
        metadata=e.metadata_ if isinstance(e.metadata_,dict) else {}
        flag=str(metadata.get("editorialFlag") or "").strip().upper();severity=str(metadata.get("severity") or "").strip().upper()
        item={"code":flag or "RELEVANT_LIMITATION","message":e.value_text or "Evidência editorial relevante.","evidenceIds":[e.id]}
        confidence=str(e.confidence or "").strip().upper();verification=str(e.verification_status or "").strip().upper()
        if flag in CRITICAL and confidence in {"HIGH","VERY_HIGH"} and verification=="VERIFIED":blocks.append(item)
        elif e.evidence_type in {"LIMITATION","NEGATIVE_PATTERN","SELLER_REPUTATION","ALTERNATIVE"} and severity in {"MEDIUM","HIGH","CRITICAL"}:warnings.append(item)
    gate="INSUFFICIENT_EVIDENCE" if c.evidence_status not in {"SUFFICIENT_EVIDENCE","VERIFIED"} else "BLOCK" if blocks else "WARN" if warnings else "PASS"
    rec={k:pillar(k,w,[e for e in rows if e.evidence_type in types]) for k,(w,types) in REC.items()};strength=pillar("EVIDENCE_STRENGTH",5,rows);strength["score"]={"VERIFIED":95,"SUFFICIENT_EVIDENCE":80}.get(c.evidence_status,50) if rows else None;strength["weightedContribution"]=(strength["score"]*5/100) if strength["score"] is not None else None;rec["EVIDENCE_STRENGTH"]=strength
    coverage=sum(p["weight"] for p in rec.values() if p["status"]=="KNOWN");known=sum(p["score"]*p["weight"] for p in rec.values() if p["score"] is not None);rscore=round(known/coverage) if coverage>=60 and gate!="INSUFFICIENT_EVIDENCE" else None
    label="EXCELLENT" if rscore is not None and rscore>=90 else "VERY_GOOD" if rscore is not None and rscore>=80 else "GOOD" if rscore is not None and rscore>=70 else "ACCEPTABLE_WITH_RESERVATIONS" if rscore is not None and rscore>=60 else "NOT_RECOMMENDED" if rscore is not None else None
    signals=list(self.db.scalars(select(RadarSignal).where(RadarSignal.provider==c.provider,RadarSignal.entity_type==c.entity_type,RadarSignal.external_id==c.external_id))) if c.external_id else []
    opp={k:{"status":"UNKNOWN","score":None,"weight":w,"weightedContribution":None,"evidenceIds":[],"reasons":["Dado não disponível."]} for k,w in OPP.items()}
    if signals:
        ranks=[s.rank for s in signals if s.rank];score=max(50,min(100,50+len({s.radar_run_id for s in signals})*5+(20-min(ranks)) if ranks else 0));opp["DEMAND_INTEREST"]={**opp["DEMAND_INTEREST"],"status":"KNOWN","score":score,"weightedContribution":score*.2,"evidenceIds":[],"reasons":[f"Presença em {len(set(s.radar_run_id for s in signals))} execução(ões) do Radar."]}
        if len({s.radar_run_id for s in signals})>=2:opp["TREND_MOMENTUM"]={**opp["TREND_MOMENTUM"],"status":"KNOWN","score":min(100,50+len(signals)*5),"weightedContribution":min(100,50+len(signals)*5)*.15,"reasons":["Recorrência observada em múltiplos snapshots."]}
    diff=[e for e in rows if e.evidence_type=="DIFFERENTIAL"]
    if diff:opp["COMMERCIAL_DIFFERENTIATION"]=pillar("COMMERCIAL_DIFFERENTIATION",5,diff)
    oc=sum(p["weight"] for p in opp.values() if p["status"]=="KNOWN");os=round(sum(p["score"]*p["weight"] for p in opp.values() if p["score"] is not None)/oc) if oc>=40 else None
    pv,ptb=price(rows);unknown=[k for k,p in {**rec,**opp}.items() if p["status"]=="UNKNOWN"]
    previous=self.db.scalar(select(CuratorAssessment).where(CuratorAssessment.candidate_id==c.id).order_by(CuratorAssessment.assessment_version.desc()));version=(previous.assessment_version+1) if previous else 1
    a=CuratorAssessment(candidate_id=c.id,assessment_version=version,previous_assessment_id=previous.id if previous else None,evidence_status=c.evidence_status,evidence_level=c.evidence_level,trust_gate=gate,trust_reasons=blocks,trust_warnings=warnings,recommendation_score=rscore,recommendation_coverage_percent=coverage,recommendation_label=label,opportunity_score=os,opportunity_coverage_percent=oc,price_verdict=pv,price_to_buy_cents=ptb,editorial_verdict=verdict(gate,rscore,pv),recommendation_pillars=rec,opportunity_pillars=opp,evidence_ids_used=ids,unknown_fields=unknown,rationale={"method":"V1-C.2 deterministic rules","trustPriority":True,"unknownExcludedFromDenominator":True})
    self.db.add(a);self.db.flush();log_decision(self.db,"OPERATOR","CURATOR_ASSESSMENT","CURATOR_ASSESSMENT_CREATED",a.id,metadata={"candidateId":c.id,"assessmentId":a.id,"version":version,"trustGate":gate,"recommendationScore":rscore,"recommendationCoverage":coverage,"opportunityScore":os,"opportunityCoverage":oc,"priceVerdict":pv,"editorialVerdict":a.editorial_verdict});self.db.commit();self.db.refresh(a);return a
