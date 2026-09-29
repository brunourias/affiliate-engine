from apps.api.app.services.commercial_readiness import CommercialReadinessService


class Obj:
    def __init__(self, **values): self.__dict__.update(values)


class FakeDB:
    def __init__(self, creative, campaign): self.creative=creative; self.campaign=campaign
    def get(self, model, key): return self.creative if key == "creative-1" else self.campaign
    def scalar(self, query): return Obj(active=True, metadata_={"productCoveragePercent": 60})
    def scalars(self, query): return iter([])


def test_commercial_readiness_reports_evidence_based_checks(monkeypatch):
    creative=Obj(id="creative-1",campaign_id="campaign-1",hook="Boa opção para pequenos reparos?",title="Parafusadeira",content_premise="Uso doméstico",body_script="Compacta para tarefas",cta="Ver detalhes",disclosure_text="Link de afiliado")
    campaign=Obj(affiliate_url="https://example.com/oferta")
    db=FakeDB(creative,campaign)
    monkeypatch.setattr("apps.api.app.services.commercial_readiness.MarketplaceCommercialSnapshotService.build",lambda *args:{"commercialClaims":[],"destination":{"destinationUrl":"https://example.com/oferta","destinationStrategy":"OWNED_LANDING_PAGE"}})
    monkeypatch.setattr("apps.api.app.services.commercial_readiness.CreativeDistributionPlan.create",lambda *args,**kwargs:{"publicationCandidates":[{"assetPaths":["static/card.png"]}]})
    monkeypatch.setattr("apps.api.app.services.commercial_readiness.CreativeDistributionPlan._placement",lambda *args:"INSTAGRAM_FEED")
    monkeypatch.setattr("apps.api.app.services.commercial_readiness.ChannelAssetAdaptationEngine.current_variant",lambda *args:{"adaptationStatus":"UP_TO_DATE"})
    result=CommercialReadinessService(db).evaluate("creative-1")
    assert result["status"]=="READY" and {x["code"] for x in result["checks"]}=={"VISUAL_AVAILABLE","PRODUCT_VISIBILITY","HEADLINE_QUALITY","BENEFITS_AVAILABLE","CTA_PRESENT","CAPTION_COMPLETE","DESTINATION_STRATEGY","DESTINATION_READY","AFFILIATE_DESTINATION_READY","DISCLOSURE_READY","FINAL_PREVIEW_AVAILABLE"}
    assert result["destinationStrategy"]=="OWNED_LANDING_PAGE" and not result["blockers"]


def test_commercial_readiness_blocks_missing_destination_and_cta(monkeypatch):
    creative=Obj(id="creative-1",campaign_id="campaign-1",hook=None,title=None,content_premise=None,body_script=None,cta=None,disclosure_text="Link")
    monkeypatch.setattr("apps.api.app.services.commercial_readiness.MarketplaceCommercialSnapshotService.build",lambda *args:{"commercialClaims":[],"destination":{"destinationUrl":None,"destinationStrategy":"UNKNOWN"}})
    monkeypatch.setattr("apps.api.app.services.commercial_readiness.CreativeDistributionPlan.create",lambda *args,**kwargs:{"publicationCandidates":[{"assetPaths":[]}]})
    monkeypatch.setattr("apps.api.app.services.commercial_readiness.CreativeDistributionPlan._placement",lambda *args:"INSTAGRAM_FEED")
    monkeypatch.setattr("apps.api.app.services.commercial_readiness.ChannelAssetAdaptationEngine.current_variant",lambda *args:None)
    result=CommercialReadinessService(FakeDB(creative,Obj(affiliate_url=None))).evaluate("creative-1")
    assert result["status"]=="BLOCKED" and {x["code"] for x in result["blockers"]}>={"VISUAL_AVAILABLE","CTA_PRESENT","CAPTION_COMPLETE","DESTINATION_STRATEGY","DESTINATION_READY"}
