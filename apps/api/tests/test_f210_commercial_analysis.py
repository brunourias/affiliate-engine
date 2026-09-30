from fastapi import HTTPException
from apps.api.app.db.models import CuratorCandidate, CuratorEvidence
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.commercial_analysis import CommercialAnalysisService


class Enrichment:
    def __init__(self, result): self.result=result; self.calls=[]
    def enrich_candidate(self, candidate_id, commit=False): self.calls.append((candidate_id,commit)); return self.result
    def close(self): pass


def candidate(db, identifier, review='COMMERCIAL_REVIEW', archived=False):
    row=CuratorCandidate(id=identifier,provider='MERCADO_LIVRE',site_id='MLB',source_type='MANUAL',entity_type='PRODUCT',external_id='MLB123',working_title='Produto',status='ARCHIVED' if archived else 'NEW',opportunity_review_status=review)
    db.add(row);db.commit();return row


def result(item=None, available=False, forbidden=False):
    status='FORBIDDEN' if forbidden else 'UNAVAILABLE'
    return {'catalogProductId':'MLB123','observedItemId':item,'commercialEvidenceAvailable':available,'evidenceAdded':0,'evidenceChanged':0,'evidenceUnchanged':0,'sourceStatuses':{key:{'status':status} for key in ('catalog','buyBox','price','reviews','sellerReputation')}}


def test_requires_commercial_review_and_waits_for_offer():
    with SessionLocal() as db:
        blocked=candidate(db,'blocked','PENDING')
        try: CommercialAnalysisService(db,Enrichment(result())).analyze(blocked.id)
        except HTTPException as exc: assert exc.status_code==409 and exc.detail=='COMMERCIAL_REVIEW_REQUIRED'
        waiting=candidate(db,'waiting')
        output=CommercialAnalysisService(db,Enrichment(result())).analyze(waiting.id)
        assert output['commercialAnalysisStatus']=='WAITING_FOR_OFFER' and output['commercialAnalysisBlocker']=='OFFER_REQUIRED' and output['assessmentId'] is None


def test_forbidden_offer_is_partial_not_failed_and_preserves_review_status():
    with SessionLocal() as db:
        row=candidate(db,'partial')
        output=CommercialAnalysisService(db,Enrichment(result('MLB999',False,True))).analyze(row.id)
        assert output['commercialAnalysisStatus']=='EVIDENCE_PARTIAL' and output['commercialAnalysisBlocker']=='ITEM_DETAILS_FORBIDDEN'
        assert db.get(CuratorCandidate,row.id).opportunity_review_status=='COMMERCIAL_REVIEW'


def test_batch_only_processes_commercial_review_and_excludes_archived():
    with SessionLocal() as db:
        allowed=candidate(db,'allowed');candidate(db,'pending','PENDING');candidate(db,'archived',archived=True)
        enrichment=Enrichment(result())
        output=CommercialAnalysisService(db,enrichment).run()
        assert output['processed']==1 and output['waitingForOffer']==1 and output['failed']==0
        assert enrichment.calls==[(allowed.id,False)]

def test_investigate_requires_commercial_review():
    with SessionLocal() as db:
        row=candidate(db,'investigate','INVESTIGATE')
        try: CommercialAnalysisService(db,Enrichment(result())).analyze(row.id)
        except HTTPException as exc: assert exc.status_code==409 and exc.detail=='COMMERCIAL_REVIEW_REQUIRED'

def test_dismissed_requires_commercial_review():
    with SessionLocal() as db:
        row=candidate(db,'dismissed','DISMISSED')
        try: CommercialAnalysisService(db,Enrichment(result())).analyze(row.id)
        except HTTPException as exc: assert exc.status_code==409 and exc.detail=='COMMERCIAL_REVIEW_REQUIRED'

def test_not_started_is_persisted_until_analysis_runs():
    with SessionLocal() as db:
        row=candidate(db,'initial')
        assert db.get(CuratorCandidate,row.id).commercial_analysis_status=='NOT_STARTED'

def test_waiting_rerun_is_idempotent_and_does_not_create_binding_or_assessment():
    with SessionLocal() as db:
        row=candidate(db,'rerun')
        service=CommercialAnalysisService(db,Enrichment(result()))
        first=service.analyze(row.id);second=service.analyze(row.id)
        assert first['commercialAnalysisStatus']==second['commercialAnalysisStatus']=='WAITING_FOR_OFFER'
        assert db.scalar(__import__('sqlalchemy').select(__import__('apps.api.app.db.models',fromlist=['CuratorAssessment']).CuratorAssessment).where(__import__('apps.api.app.db.models',fromlist=['CuratorAssessment']).CuratorAssessment.candidate_id==row.id)) is None
        assert db.scalar(__import__('sqlalchemy').select(CuratorEvidence).where(CuratorEvidence.candidate_id==row.id,CuratorEvidence.evidence_type=='MARKETPLACE_LISTING_BINDING')) is None

def test_explicit_binding_source_item_is_preserved_when_evidence_available():
    with SessionLocal() as db:
        row=candidate(db,'bound')
        db.add(CuratorEvidence(candidate_id=row.id,evidence_type='MARKETPLACE_LISTING_BINDING',source_kind='MANUAL_OPERATOR',source_reference='MLB777',value_json={'sourceItemId':'MLB777'},confidence='HIGH',verification_status='UNVERIFIED'));db.commit()
        output=CommercialAnalysisService(db,Enrichment(result('MLB777',True))).analyze(row.id)
        assert output['commercialAnalysisStatus']=='ASSESSMENT_AVAILABLE' and output['sourceItemId']=='MLB777' and output['offerSource']=='EXPLICIT_BINDING'
        assert output['opportunityReviewStatus']=='COMMERCIAL_REVIEW'

def test_available_commercial_evidence_creates_assessment_even_when_scores_are_null():
    with SessionLocal() as db:
        row=candidate(db,'assessment')
        output=CommercialAnalysisService(db,Enrichment(result('MLB888',True))).analyze(row.id)
        assert output['assessmentId'] and output['assessmentVersion']==1 and output['recommendationScore'] is None
        assert output['trustGate']=='INSUFFICIENT_EVIDENCE' and output['commercialAnalysisStatus']=='ASSESSMENT_AVAILABLE'

def test_same_active_evidence_reuses_assessment():
    with SessionLocal() as db:
        row=candidate(db,'reuse')
        service=CommercialAnalysisService(db,Enrichment(result('MLB888',True)))
        first=service.analyze(row.id);second=service.analyze(row.id)
        assert second['assessmentId']==first['assessmentId'] and second['assessmentReused'] is True

def test_new_active_evidence_creates_next_assessment_version():
    with SessionLocal() as db:
        row=candidate(db,'version')
        service=CommercialAnalysisService(db,Enrichment(result('MLB888',True)))
        first=service.analyze(row.id)
        db.add(CuratorEvidence(candidate_id=row.id,evidence_type='CURRENT_PRICE',source_kind='OFFICIAL',source_reference='new',value_cents=100,confidence='HIGH',verification_status='VERIFIED'));db.commit()
        second=service.analyze(row.id)
        assert second['assessmentVersion']==2 and second['assessmentId']!=first['assessmentId'] and second['assessmentReused'] is False

def test_closed_evidence_does_not_create_new_assessment_version():
    from datetime import datetime, timezone
    with SessionLocal() as db:
        row=candidate(db,'closed')
        service=CommercialAnalysisService(db,Enrichment(result('MLB888',True)));first=service.analyze(row.id)
        db.add(CuratorEvidence(candidate_id=row.id,evidence_type='CURRENT_PRICE',source_kind='OFFICIAL',source_reference='old',value_cents=100,confidence='HIGH',verification_status='VERIFIED',valid_until=datetime.now(timezone.utc)));db.commit()
        second=service.analyze(row.id)
        assert second['assessmentId']==first['assessmentId'] and second['assessmentReused'] is True

def test_normal_unavailable_data_is_partial_not_failed():
    with SessionLocal() as db:
        row=candidate(db,'unavailable')
        output=CommercialAnalysisService(db,Enrichment(result('MLB999',False))).analyze(row.id)
        assert output['commercialAnalysisStatus']=='EVIDENCE_PARTIAL' and output['commercialAnalysisBlocker']=='COMMERCIAL_DATA_UNAVAILABLE'

def test_summary_counts_only_commercial_review_non_archived():
    with SessionLocal() as db:
        waiting=candidate(db,'sumwaiting');waiting.commercial_analysis_status='WAITING_FOR_OFFER'
        partial=candidate(db,'sumpartial');partial.commercial_analysis_status='EVIDENCE_PARTIAL'
        candidate(db,'sumpending','PENDING');candidate(db,'sumarchived',archived=True);db.commit()
        assert CommercialAnalysisService(db,Enrichment(result())).summary()=={'notStarted':0,'waitingForOffer':1,'evidencePartial':1,'assessmentAvailable':0,'failed':0}

def test_batch_waiting_and_partial_are_completed_not_failed():
    with SessionLocal() as db:
        first=candidate(db,'batchwait');second=candidate(db,'batchpartial')
        class Mixed(Enrichment):
            def enrich_candidate(self,candidate_id,commit=False): return result('MLB1',False,True) if candidate_id==second.id else result()
        output=CommercialAnalysisService(db,Mixed(result())).run()
        assert output['status']=='COMPLETED' and output['waitingForOffer']==1 and output['evidencePartial']==1 and output['failed']==0

def test_started_and_terminal_decision_logs_are_safe():
    from sqlalchemy import select
    from apps.api.app.db.models import DecisionLog
    with SessionLocal() as db:
        row=candidate(db,'logs');CommercialAnalysisService(db,Enrichment(result())).analyze(row.id)
        actions=set(db.scalars(select(DecisionLog.action).where(DecisionLog.entity_id==row.id)))
        assert {'COMMERCIAL_ANALYSIS_STARTED','COMMERCIAL_ANALYSIS_WAITING_FOR_OFFER'}.issubset(actions)

def test_unexpected_enrichment_failure_becomes_failed():
    with SessionLocal() as db:
        row=candidate(db,'failure')
        class Broken(Enrichment):
            def enrich_candidate(self,candidate_id,commit=False): raise RuntimeError('unexpected')
        output=CommercialAnalysisService(db,Broken(result())).analyze(row.id)
        assert output['commercialAnalysisStatus']=='FAILED' and output['commercialAnalysisBlocker']=='ENRICHMENT_FAILED'

def test_batch_ignores_all_non_commercial_review_states():
    with SessionLocal() as db:
        candidate(db,'p','PENDING');candidate(db,'i','INVESTIGATE');candidate(db,'d','DISMISSED')
        output=CommercialAnalysisService(db,Enrichment(result())).run()
        assert output['requested']==0 and output['processed']==0 and output['status']=='COMPLETED'

def test_commercial_analysis_never_creates_affiliate_destination():
    with SessionLocal() as db:
        row=candidate(db,'aff');CommercialAnalysisService(db,Enrichment(result())).analyze(row.id)
        assert db.scalar(__import__('sqlalchemy').select(CuratorEvidence).where(CuratorEvidence.candidate_id==row.id,CuratorEvidence.evidence_type=='AFFILIATE_DESTINATION')) is None

def test_batch_respects_configured_limit(monkeypatch):
    with SessionLocal() as db:
        candidate(db,'limit-a');candidate(db,'limit-b')
        monkeypatch.setattr('apps.api.app.services.commercial_analysis.settings.commercial_analysis_batch_limit',1)
        output=CommercialAnalysisService(db,Enrichment(result())).run()
        assert output['requested']==1 and output['processed']==1
