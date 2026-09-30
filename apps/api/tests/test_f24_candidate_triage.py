from sqlalchemy import select

from apps.api.app.core.config import settings
from apps.api.app.db.models import CuratorCandidate, CuratorEvidence, RadarRun, RadarSignal
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.assessment import CuratorAssessmentService
from apps.api.app.services.triage import CandidateTriageService


def signal(db, run, query, rank=1, source="TREND_GLOBAL"):
    row=RadarSignal(radar_run_id=run.id,provider="MERCADO_LIVRE",site_id="MLB",source_type=source,source_capability="TEST",entity_type="QUERY",display_text=query,rank=rank)
    db.add(row);db.flush();return row


def candidate(db, external_id, title="Produto", manual=False):
    row=CuratorCandidate(provider="MERCADO_LIVRE",site_id="MLB",source_type="MANUAL" if manual else "CATALOG_DISCOVERY",entity_type="PRODUCT",external_id=external_id,working_title=title)
    db.add(row);db.flush();return row


def market(db, candidate_row, signal_row, relevance=90):
    db.add(CuratorEvidence(candidate_id=candidate_row.id,evidence_type="MARKET_SIGNAL",source_kind="MERCADO_LIVRE_OFFICIAL_API",source_reference=signal_row.id,confidence="HIGH",verification_status="VERIFIED",value_json={"discoveryRelevanceScore":relevance,"query":signal_row.display_text}))


def catalog(db, candidate_row, domain="MLB-TOOLS", rich=True):
    db.add(CuratorEvidence(candidate_id=candidate_row.id,evidence_type="IDENTITY",value_text=candidate_row.working_title,source_kind="MERCADO_LIVRE_OFFICIAL_API",source_reference=f"{candidate_row.id}:identity",confidence="HIGH",verification_status="VERIFIED"))
    db.add(CuratorEvidence(candidate_id=candidate_row.id,evidence_type="TECHNICAL_SPEC",source_kind="MERCADO_LIVRE_OFFICIAL_API",source_reference=f"{candidate_row.id}:technical",confidence="HIGH",verification_status="VERIFIED",value_json={"domainId":domain,"attributes":[{"id":"A"}] if rich else [],"pictures":[{"id":"P"}] if rich else [],"officialCatalogData":{"status":"active"}}))


def test_specific_relevant_rich_catalog_is_triage_high_and_marks_top(monkeypatch):
    monkeypatch.setattr(settings,"curator_triage_enrichment_limit",10)
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();s=signal(db,run,"snow foam",1,"TREND_CATEGORY");c=candidate(db,"MLB10000001");market(db,c,s);catalog(db,c);db.commit()
        result=CandidateTriageService(db).triage_run(run.id)
        assert c.triage_status=="TRIAGE_HIGH" and c.triage_marked_for_enrichment
        assert {"HIGH_DISCOVERY_RELEVANCE","CATEGORY_TREND_SIGNAL","CATALOG_ATTRIBUTES_AVAILABLE","OFFICIAL_IMAGES_AVAILABLE","SPECIFIC_QUERY"}.issubset(c.triage_reasons)
        assert result["topCandidates"][0]["candidateId"]==c.id


def test_generic_query_and_ambiguous_domains_reduce_priority():
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();s=signal(db,run,"stanley")
        rows=[candidate(db,f"MLB1000000{index}") for index in range(1,4)]
        for index,row in enumerate(rows): market(db,row,s,70);catalog(db,row,f"MLB-DOMAIN-{index}")
        db.commit();CandidateTriageService(db).triage_run(run.id)
        assert all("AMBIGUOUS_QUERY" in row.triage_reasons for row in rows)
        assert all(row.triage_score < 70 for row in rows)


def test_recurrence_uses_distinct_signals_and_runs_only_once_each():
    with SessionLocal() as db:
        first=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");second=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add_all([first,second]);db.flush();s1=signal(db,first,"snow foam");s2=signal(db,second,"snow foam")
        recurring=candidate(db,"MLB10000011");single=candidate(db,"MLB10000012")
        market(db,recurring,s1,60);market(db,recurring,s2,60);market(db,single,s1,60);catalog(db,recurring);catalog(db,single);db.commit()
        CandidateTriageService(db).triage_run(first.id)
        assert "RECURRING_RADAR_RUNS" not in recurring.triage_reasons and recurring.triage_score == single.triage_score
        before=recurring.triage_score;CandidateTriageService(db).triage_run(first.id);assert recurring.triage_score==before


def test_missing_commercial_data_does_not_make_triage_zero_or_change_assessment_scores():
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();s=signal(db,run,"regua pedreiro")
        c=candidate(db,"MLB10000021");market(db,c,s,70);catalog(db,c);db.commit()
        baseline=CuratorAssessmentService(db).assess(c)
        CandidateTriageService(db).triage_run(run.id)
        after=CuratorAssessmentService(db).assess(c)
        assert c.triage_score and c.triage_score > 0
        assert after.recommendation_score==baseline.recommendation_score and after.opportunity_score==baseline.opportunity_score


def test_limit_marks_only_top_candidates_and_manual_candidate_is_not_duplicated(monkeypatch):
    monkeypatch.setattr(settings,"curator_triage_enrichment_limit",2)
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();s=signal(db,run,"jogo ferramentas completo")
        rows=[candidate(db,f"MLB1000003{index}",manual=index==0) for index in range(4)]
        for index,row in enumerate(rows): market(db,row,s,95-index*10);catalog(db,row)
        db.commit();result=CandidateTriageService(db).triage_run(run.id)
        assert len(result["topCandidates"])==2 and sum(row.triage_marked_for_enrichment for row in rows)==2
        assert len(list(db.scalars(select(CuratorCandidate).where(CuratorCandidate.external_id==rows[0].external_id))))==1


def test_generic_origin_query_uses_market_signal_query_not_product_title():
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();s=signal(db,run,"todos os produtos")
        c=candidate(db,"MLB10000041","Todos os produtos - 8 onças de pimenta preta inteira");market(db,c,s,100);catalog(db,c);db.commit()
        CandidateTriageService(db).triage_run(run.id)
        assert "GENERIC_QUERY" in c.triage_reasons and "SPECIFIC_QUERY" not in c.triage_reasons


def test_generic_and_specific_query_quality_are_distinguished():
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();generic_signal=signal(db,run,"ferramentas");specific_signal=signal(db,run,"jogo de ferramentas completo",2)
        generic=candidate(db,"MLB10000042");specific=candidate(db,"MLB10000043")
        market(db,generic,generic_signal,70);market(db,specific,specific_signal,70);catalog(db,generic);catalog(db,specific);db.commit()
        CandidateTriageService(db).triage_run(run.id)
        assert "GENERIC_QUERY" in generic.triage_reasons and "SPECIFIC_QUERY" not in generic.triage_reasons
        assert "GENERIC_QUERY" not in specific.triage_reasons and "SPECIFIC_QUERY" in specific.triage_reasons


def test_discovery_relevance_contribution_is_proportional_and_deterministic():
    with SessionLocal() as db:
        run=RadarRun(provider="MERCADO_LIVRE",site_id="MLB",status="COMPLETED");db.add(run);db.flush();s=signal(db,run,"snow foam")
        high=candidate(db,"MLB10000051");medium=candidate(db,"MLB10000052");lower=candidate(db,"MLB10000053")
        market(db,high,s,100);market(db,medium,s,90);market(db,lower,s,60)
        for row in (high,medium,lower): catalog(db,row)
        db.commit();first=CandidateTriageService(db).triage_run(run.id)
        assert high.triage_score > medium.triage_score > lower.triage_score
        scores=[row.triage_score for row in (high,medium,lower)]
        CandidateTriageService(db).triage_run(run.id)
        assert scores == [row.triage_score for row in (high,medium,lower)] and first["topCandidates"][0]["candidateId"] == high.id
