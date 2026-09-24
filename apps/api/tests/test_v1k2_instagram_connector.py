import json,pytest
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.publication_connectors import InstagramPublicationConnector,MetaPublicationConnector,PublicationConnectorRegistry,TikTokPublicationConnector

def sample(format="CAROUSEL",count=3):return {"publicationCandidateId":"pc","packageFingerprint":"fp","format":format,"assetFiles":[f"card_{i}.png" for i in range(count)],"manualReviewRequired":True}

def test_instagram_resolves_separately_from_facebook_and_tiktok():
    with SessionLocal() as db:
        registry=PublicationConnectorRegistry(db);assert isinstance(registry.resolve("INSTAGRAM","DIRECT_PUBLISH"),InstagramPublicationConnector);assert isinstance(registry.resolve("FACEBOOK","DIRECT_PUBLISH"),MetaPublicationConnector);assert isinstance(registry.resolve("TIKTOK","DIRECT_PUBLISH"),TikTokPublicationConnector);assert registry.resolve("INSTAGRAM","ASSISTED_UPLOAD") is None

def test_capabilities_profiles_and_professional_account_requirements():
    connector=InstagramPublicationConnector("DIRECT_PUBLISH");caps=connector.capabilities();assert caps["connectorDomain"]=="CONTENT_PUBLISHING" and caps["supportsPhotos"] and caps["supportsVideo"] and caps["supportsCarousel"] and caps["supportsReels"]
    assert caps["connectionRequirements"]["professionalAccountRequired"] and caps["connectionRequirements"]["mediaHostingRequired"] and caps["authorizationProfile"]=="INSTAGRAM_LOGIN"
    assert InstagramPublicationConnector("DIRECT_PUBLISH","FACEBOOK_LOGIN").capabilities()["requiredScopes"]!=caps["requiredScopes"]

def test_export_needs_no_oauth_but_direct_needs_connection_account_and_public_media():
    with SessionLocal() as db:assert PublicationConnectorRegistry(db).options("INSTAGRAM")[0]["readiness"]=="READY"
    result=InstagramPublicationConnector("DIRECT_PUBLISH").validate_package(sample());assert {"INSTAGRAM_CONNECTION_REQUIRED","PROFESSIONAL_ACCOUNT_REQUIRED","PUBLIC_MEDIA_SOURCE_REQUIRED","DISCLOSURE_REQUIREMENT_UNKNOWN"}<=set(result["reasonCodes"])
    ready=InstagramPublicationConnector("DIRECT_PUBLISH").validate_package({**sample(),"manualReviewRequired":False},"PUBLIC_URL","BUSINESS",True);assert ready["readiness"]=="READY"

def test_carousel_plan_preserves_order_and_builds_children_parent_publish_without_request():
    package=sample();plan=InstagramPublicationConnector("DIRECT_PUBLISH").execution_plan(package);children=[x for x in plan["steps"] if x["code"]=="CREATE_ITEM_CONTAINER"]
    assert [x["asset"] for x in children]==package["assetFiles"] and len(children)==3 and sum(x["code"]=="CREATE_CAROUSEL_CONTAINER" for x in plan["steps"])==1 and sum(x["code"]=="PUBLISH_CONTAINER" for x in plan["steps"])==1
    assert plan["status"]=="WAITING_FOR_MEDIA_HOSTING" and plan["remoteRequestExecuted"] is False and not any(plan[x] for x in ["igAccountId","creationId","containerIds","platformMediaId"])

def test_carousel_over_ten_fails_without_truncation():
    with pytest.raises(ValueError):InstagramPublicationConnector("DIRECT_PUBLISH").execution_plan(sample(count=11))

def test_image_and_reels_plans_are_specific_and_deterministic():
    connector=InstagramPublicationConnector("DIRECT_PUBLISH");image=connector.execution_plan(sample("STATIC_CARD",1));reel=connector.execution_plan(sample("VIDEO_SHORT",1));again=connector.execution_plan(sample("VIDEO_SHORT",1))
    assert any(x.get("mediaType")=="IMAGE" for x in image["steps"]) and any(x.get("mediaType")=="REELS" for x in reel["steps"]);assert reel["executionFingerprint"]==again["executionFingerprint"] and "INSTAGRAM_CONTAINER_PROCESSING_REQUIRED" in {x.get("reasonCode") for x in reel["steps"]}
    assert all("secret" not in key.lower() and "token" not in key.lower() for key in json.loads(json.dumps(reel)))
