import re
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from apps.api.app.db.models import CuratorCandidate, CuratorEvidence, RadarSignal
from apps.api.app.services.operations import log_decision

EVIDENCE_TYPES={"MARKET_SIGNAL","IDENTITY","CURRENT_PRICE","PRICE_REFERENCE","REVIEW_SUMMARY","POSITIVE_PATTERN","NEGATIVE_PATTERN","SELLER_REPUTATION","TECHNICAL_SPEC","USE_CASE","DIFFERENTIAL","LIMITATION","ALTERNATIVE","COMMUNITY_SIGNAL","OWN_TEST","OTHER"}
CHECKLIST={"IDENTITY":"Identidade","URL":"URL/origem","CURRENT_PRICE":"Preço atual","PRICE_REFERENCE":"Referência de preço","REVIEW_SUMMARY":"Avaliações","POSITIVE_PATTERN":"Pontos positivos","LIMITATION":"Problemas/limitações","SELLER_REPUTATION":"Vendedor","TECHNICAL_SPEC":"Características","USE_CASE":"Utilidade","DIFFERENTIAL":"Diferencial","ALTERNATIVE":"Alternativas","MARKET_SIGNAL":"Sinal de mercado","OWN_TEST":"Teste próprio"}
TEMPORAL={"CURRENT_PRICE","SELLER_REPUTATION","REVIEW_SUMMARY","COMMUNITY_SIGNAL"}
def utcnow(): return datetime.now(timezone.utc)
def stale(e):
    if not e.valid_until:return False
    value=e.valid_until.replace(tzinfo=timezone.utc) if e.valid_until.tzinfo is None else e.valid_until
    return utcnow()>value
def checklist(candidate,evidence):
    result=[]
    for key,label in CHECKLIST.items():
        rows=[e for e in evidence if e.evidence_type==key]
        if key=="IDENTITY" and (candidate.external_id or candidate.working_title): state="AVAILABLE"
        elif key=="URL" and candidate.source_url: state="AVAILABLE"
        elif rows and any(stale(e) for e in rows) and not any(not stale(e) for e in rows): state="STALE"
        else: state="AVAILABLE" if rows else "MISSING"
        result.append({"key":key,"label":label,"status":state})
    return result
def derive(candidate,evidence):
    material=[e for e in evidence if e.evidence_type!="MARKET_SIGNAL" and not stale(e)]
    types={e.evidence_type for e in material}; identity=bool(candidate.external_id or candidate.working_title or "IDENTITY" in types)
    quality=bool(types&{"REVIEW_SUMMARY","COMMUNITY_SIGNAL","OWN_TEST"})
    enough=identity and bool(types&{"CURRENT_PRICE","OTHER"}) and quality and bool(types&{"LIMITATION","NEGATIVE_PATTERN"}) and bool(types&{"USE_CASE","DIFFERENTIAL"})
    status="SUFFICIENT_EVIDENCE" if enough else ("PARTIAL_EVIDENCE" if identity and material else "INSUFFICIENT_EVIDENCE")
    own=any(e.evidence_type=="OWN_TEST" and e.verification_status=="VERIFIED" for e in material)
    if enough and (own or all(e.verification_status=="VERIFIED" for e in material)): status="VERIFIED"
    level="OWNED_AND_TESTED" if own else ("COMMUNITY_VALIDATED" if types&{"COMMUNITY_SIGNAL","REVIEW_SUMMARY"} else ("DATA_ANALYZED" if material else "NONE"))
    candidate.evidence_status=status; candidate.evidence_level=level; candidate.updated_at=utcnow()
def refresh(db,candidate):
    evidence=list(db.scalars(select(CuratorEvidence).where(CuratorEvidence.candidate_id==candidate.id))); derive(candidate,evidence); return evidence
def from_radar(db:Session,signal:RadarSignal):
    q=select(CuratorCandidate).where(CuratorCandidate.provider==signal.provider,CuratorCandidate.entity_type==signal.entity_type)
    if signal.external_id:q=q.where(CuratorCandidate.external_id==signal.external_id)
    else:q=q.where(CuratorCandidate.external_id.is_(None),CuratorCandidate.source_display_text==" ".join((signal.display_text or "").lower().split()),CuratorCandidate.category_external_id==signal.category_external_id)
    existing=db.scalar(q)
    if existing:return existing,False
    c=CuratorCandidate(provider=signal.provider,site_id=signal.site_id,source_type="RADAR_SIGNAL",source_radar_signal_id=signal.id,source_radar_run_id=signal.radar_run_id,entity_type=signal.entity_type,external_id=signal.external_id,category_external_id=signal.category_external_id,source_display_text=" ".join((signal.display_text or "").lower().split()))
    db.add(c);db.flush();db.add(CuratorEvidence(candidate_id=c.id,evidence_type="MARKET_SIGNAL",value_json={"sourceType":signal.source_type,"rank":signal.rank,"entityType":signal.entity_type,"externalId":signal.external_id},source_kind="MERCADO_LIVRE_API",source_name=signal.source_type,source_reference=signal.id,confidence="HIGH",verification_status="VERIFIED",observed_at=signal.observed_at));log_decision(db,"OPERATOR","CURATOR_CANDIDATE","CURATOR_CANDIDATE_CREATED_FROM_RADAR",c.id,metadata={"candidateId":c.id,"sourceRadarSignalId":signal.id});return c,True
def parse_mlb(url):
    match=re.search(r"MLB[-_ ]?(\d+)",url or "",re.I);return f"MLB{match.group(1)}" if match else None
