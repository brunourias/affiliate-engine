from hashlib import sha256
from io import BytesIO
import socket

import httpx
from PIL import Image
import pytest
from sqlalchemy import func, select

from apps.api.app.core.config import settings
from apps.api.app.db.models import (
    CuratorCandidate, CuratorEvidence, DecisionLog, MediaAsset, MediaJob,
)
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.media import add_asset
from apps.api.app.services.media_pipeline import (
    FakeMediaValidator, FakeSceneRenderer, FakeTimelineComposer, FakeVoiceRenderer, run_pipeline,
)
from apps.api.app.services.media_storage import MediaStorage
from apps.api.app.services.marketplace_media_ingestion import (
    MarketplaceProductMediaService, OFFICIAL_SOURCE, ProductMediaError,
)
from apps.api.app.services.product_media import BrollDirector, ProductMediaAnalyzer
from apps.api.tests.test_f217a_media_handoff import make_creative, create


def image_bytes(fmt="PNG", color=(240, 20, 10)):
    output = BytesIO()
    Image.new("RGB", (32, 24), color).save(output, format=fmt)
    return output.getvalue()


def public_dns(host, port, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def candidate(provider="MERCADO_LIVRE", *, title="Produto oficial"):
    with SessionLocal() as db:
        row = CuratorCandidate(provider=provider, site_id="MLB", source_type="MANUAL",
                               entity_type="ITEM", external_id="MLB123456789", working_title=title)
        db.add(row); db.commit(); db.refresh(row)
        return row.id


def evidence(candidate_id, evidence_type="CATALOG_PICTURE", *, picture_id="PIC-1", url="https://http2.mlstatic.com/pic-1.png",
             position=0, official=True):
    payload = {"id": picture_id, "secure_url": url, "position": position}
    if official:
        payload["provenance"] = OFFICIAL_SOURCE
    with SessionLocal() as db:
        row = CuratorEvidence(candidate_id=candidate_id, evidence_type=evidence_type,
                              value_json=payload, source_kind=OFFICIAL_SOURCE if official else "USER_INPUT",
                              source_name="Mercado Livre API", source_reference=f"REF:{picture_id}",
                              confidence="HIGH", verification_status="VERIFIED")
        db.add(row); db.commit(); db.refresh(row)
        return row.id


def service(db, tmp_path, handler=None, *, resolver=public_dns):
    monkeypatch_root = str(tmp_path)
    settings.media_root = monkeypatch_root
    handler = handler or (lambda request: httpx.Response(200, headers={"content-type": "image/png"}, content=image_bytes()))
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, follow_redirects=False)
    return MarketplaceProductMediaService(db, client=client, dns_resolver=resolver,
                                          storage=MediaStorage(tmp_path)), client


def read_metrics(db, candidate_id):
    assets = db.scalar(select(func.count()).select_from(MediaAsset).where(MediaAsset.owner_id == candidate_id)) or 0
    logs = db.scalar(select(func.count()).select_from(DecisionLog).where(DecisionLog.entity_id == candidate_id)) or 0
    return assets, logs


def test_candidate_missing_and_non_marketplace_are_structured(tmp_path):
    with SessionLocal() as db:
        svc, client = service(db, tmp_path)
        with pytest.raises(ProductMediaError) as missing:
            svc.sync("missing")
        assert missing.value.code == "CANDIDATE_NOT_FOUND" and missing.value.status == 404
        other = candidate("OTHER")
        with pytest.raises(ProductMediaError) as wrong_provider:
            svc.sync(other)
        assert wrong_provider.value.code == "PRODUCT_MEDIA_SOURCE_NOT_OFFICIAL"
        client.close()


def test_no_picture_evidence_returns_degraded_without_download(tmp_path):
    candidate_id = candidate()
    calls = []
    with SessionLocal() as db:
        svc, client = service(db, tmp_path, lambda request: calls.append(request) or httpx.Response(500))
        result = svc.sync(candidate_id)
        assert result["status"] == "UNAVAILABLE" and result["reasonCode"] == "PRODUCT_MEDIA_SOURCE_NOT_FOUND"
        assert result["sourcePictureCount"] == result["downloadedCount"] == result["failedCount"] == 0
        assert calls == []
        client.close()


def test_catalog_picture_is_sufficient_when_item_details_are_forbidden(tmp_path):
    candidate_id = candidate()
    evidence(candidate_id, "CATALOG_PICTURE")
    with SessionLocal() as db:
        db.add(CuratorEvidence(candidate_id=candidate_id, evidence_type="LISTING_DATA", source_kind=OFFICIAL_SOURCE,
                               value_json={"itemDetailsStatus": "FORBIDDEN"}, source_reference="item-status")); db.commit()
        svc, client = service(db, tmp_path)
        result = svc.sync(candidate_id)
        assert result["status"] == "AVAILABLE" and result["downloadedCount"] == 1
        assert result["assets"][0]["ownerId"] == candidate_id
        client.close()


def test_catalog_and_listing_are_supported_listing_preferred_and_assets_classified(tmp_path):
    candidate_id = candidate()
    evidence(candidate_id, "CATALOG_PICTURE", picture_id="SAME", url="https://http2.mlstatic.com/catalog.png")
    listing_id = evidence(candidate_id, "LISTING_PICTURE", picture_id="SAME", url="https://http2.mlstatic.com/listing.png")
    requests = []
    with SessionLocal() as db:
        svc, client = service(db, tmp_path, lambda request: requests.append(str(request.url)) or httpx.Response(200, headers={"content-type": "image/png"}, content=image_bytes()))
        result = svc.sync(candidate_id)
        assert requests == ["https://http2.mlstatic.com/listing.png"]
        assert result["sourcePictureCount"] == result["downloadedCount"] == 1
        asset = db.scalar(select(MediaAsset).where(MediaAsset.owner_id == candidate_id))
        assert asset.asset_type == "PRODUCT_IMAGE" and asset.owner_type == "CANDIDATE" and asset.owner_id == candidate_id
        assert asset.relative_path.startswith("assets/") and MediaStorage(tmp_path).resolve(asset.relative_path).is_file()
        assert asset.width == 32 and asset.height == 24 and asset.mime_type == "image/png"
        metadata = asset.metadata_
        assert metadata["provider"] == "MERCADO_LIVRE" and metadata["sourceKind"] == OFFICIAL_SOURCE
        assert metadata["sourceEvidenceType"] == "LISTING_PICTURE" and metadata["sourceEvidenceId"] == listing_id
        assert metadata["sourceReference"] == "REF:SAME" and metadata["remotePictureId"] == "SAME"
        assert metadata["remoteUrl"] == "https://http2.mlstatic.com/listing.png"
        assert metadata["position"] == 0 and metadata["classification"] == "HERO_IMAGE"
        assert metadata["contentHash"] == sha256(image_bytes()).hexdigest() and metadata["ingestedAt"]
        client.close()


def test_listing_picture_alone_is_valid_and_uses_alternates_after_hero(tmp_path):
    candidate_id = candidate()
    evidence(candidate_id, "LISTING_PICTURE", picture_id="L1", url="https://http2.mlstatic.com/one.png", position=0)
    evidence(candidate_id, "LISTING_PICTURE", picture_id="L2", url="https://http2.mlstatic.com/two.png", position=1)
    colors = iter([(200, 0, 0), (0, 200, 0)])
    with SessionLocal() as db:
        svc, client = service(db, tmp_path, lambda request: httpx.Response(200, headers={"content-type": "image/png"}, content=image_bytes(color=next(colors))))
        result = svc.sync(candidate_id)
        assert [asset["classification"] for asset in result["assets"]] == ["HERO_IMAGE", "ALTERNATE_IMAGE"]
        assert all(asset["ownerType"] == "CANDIDATE" and asset["ownerId"] == candidate_id for asset in result["assets"])
        client.close()


def test_sync_is_idempotent_and_does_not_duplicate_files_assets_or_logs(tmp_path):
    candidate_id = candidate(); evidence(candidate_id)
    requests = []
    with SessionLocal() as db:
        svc, client = service(db, tmp_path, lambda request: requests.append(request) or httpx.Response(200, headers={"content-type": "image/png"}, content=image_bytes()))
        first = svc.sync(candidate_id); counts1 = read_metrics(db, candidate_id)
        second = svc.sync(candidate_id); counts2 = read_metrics(db, candidate_id)
        assert first["downloadedCount"] == 1 and first["reusedCount"] == 0
        assert second["downloadedCount"] == 0 and second["reusedCount"] == 1
        assert counts2 == counts1 and len(requests) == 1
        assert len(list((tmp_path / "assets").glob("*"))) == 1
        client.close()


def test_changed_picture_id_with_same_content_hash_reuses_existing_asset(tmp_path):
    candidate_id = candidate(); evidence(candidate_id, picture_id="P1", url="https://http2.mlstatic.com/a.png")
    with SessionLocal() as db:
        svc, client = service(db, tmp_path)
        one = svc.sync(candidate_id); client.close()
    evidence(candidate_id, picture_id="P2", url="https://http2.mlstatic.com/b.png", position=1)
    with SessionLocal() as db:
        svc, client = service(db, tmp_path)
        two = svc.sync(candidate_id)
        assert two["downloadedCount"] == 1 and two["reusedCount"] == 1
        assert len(two["assets"]) == 1 and two["assets"][0]["mediaAssetId"] == one["assets"][0]["mediaAssetId"]
        row = db.get(MediaAsset, two["assets"][0]["mediaAssetId"])
        assert "P2" in row.metadata_["remotePictureIds"]
        assert len(list((tmp_path / "assets").glob("*"))) == 1
        client.close()


@pytest.mark.parametrize("url", [
    "http://http2.mlstatic.com/a.png", "https://localhost/a.png", "https://127.0.0.1/a.png",
    "https://169.254.169.254/a.png", "https://192.168.1.10/a.png", "file:///tmp/a.png",
    "data:image/png;base64,AAAA", "ftp://http2.mlstatic.com/a.png", "https://evil.example/a.png",
])
def test_unsafe_schemes_hosts_and_ip_literals_are_rejected_without_request(tmp_path, url):
    candidate_id = candidate(); evidence(candidate_id, url=url)
    calls = []
    with SessionLocal() as db:
        svc, client = service(db, tmp_path, lambda request: calls.append(request) or httpx.Response(200))
        result = svc.sync(candidate_id)
        assert result["failedCount"] == 1 and result["failures"][0]["code"] == "PRODUCT_MEDIA_REMOTE_HOST_NOT_ALLOWED"
        assert calls == []
        assert db.scalar(select(func.count()).select_from(MediaAsset)) == 0
        client.close()


def test_dns_private_address_is_blocked(tmp_path):
    candidate_id = candidate(); evidence(candidate_id)
    calls = []
    private_dns = lambda host, port, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", port))]
    with SessionLocal() as db:
        svc, client = service(db, tmp_path, lambda request: calls.append(request) or httpx.Response(200), resolver=private_dns)
        result = svc.sync(candidate_id)
        assert result["failures"][0]["code"] == "PRODUCT_MEDIA_REMOTE_HOST_NOT_ALLOWED" and calls == []
        client.close()


@pytest.mark.parametrize("redirect", ["http://http2.mlstatic.com/target.png", "https://127.0.0.1/private.png", "https://attacker.example/x.png"])
def test_redirect_to_non_https_or_disallowed_host_is_blocked(tmp_path, redirect):
    candidate_id = candidate(); evidence(candidate_id)
    requests = []
    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": redirect})
    with SessionLocal() as db:
        svc, client = service(db, tmp_path, handler)
        result = svc.sync(candidate_id)
        assert result["failedCount"] == 1 and result["failures"][0]["code"] == "PRODUCT_MEDIA_REMOTE_HOST_NOT_ALLOWED"
        assert requests == ["https://http2.mlstatic.com/pic-1.png"]
        assert db.scalar(select(func.count()).select_from(MediaAsset)) == 0
        client.close()


@pytest.mark.parametrize("status,headers,body,limit,expected", [
    (200, {"content-type": "image/png", "content-length": "20"}, image_bytes(), 10, "PRODUCT_MEDIA_TOO_LARGE"),
    (200, {"content-type": "text/html"}, b"<html>bad</html>", 10000, "PRODUCT_MEDIA_UNSUPPORTED_TYPE"),
    (200, {"content-type": "image/jpeg"}, b"<html>not jpeg</html>", 10000, "PRODUCT_MEDIA_INVALID_CONTENT"),
    (404, {"content-type": "image/png"}, image_bytes(), 10000, "PRODUCT_MEDIA_DOWNLOAD_FAILED"),
    (500, {"content-type": "image/png"}, image_bytes(), 10000, "PRODUCT_MEDIA_DOWNLOAD_FAILED"),
])
def test_status_size_mime_and_decoder_failures_never_create_asset(tmp_path, monkeypatch, status, headers, body, limit, expected):
    candidate_id = candidate(); evidence(candidate_id)
    monkeypatch.setattr(settings, "media_asset_max_bytes", limit)
    with SessionLocal() as db:
        svc, client = service(db, tmp_path, lambda request: httpx.Response(status, headers=headers, content=body))
        result = svc.sync(candidate_id)
        assert result["failedCount"] == 1 and result["failures"][0]["code"] == expected
        assert db.scalar(select(func.count()).select_from(MediaAsset)) == 0
        client.close()


def test_streamed_body_limit_and_timeout_are_partial_failures(tmp_path, monkeypatch):
    candidate_id = candidate(); evidence(candidate_id)
    monkeypatch.setattr(settings, "media_asset_max_bytes", 40)
    def oversized(request):
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"x" * 100)
    with SessionLocal() as db:
        svc, client = service(db, tmp_path, oversized)
        result = svc.sync(candidate_id)
        assert result["failures"][0]["code"] == "PRODUCT_MEDIA_TOO_LARGE"
        client.close()
    candidate2 = candidate(); evidence(candidate2)
    def timeout(request):
        raise httpx.ReadTimeout("upstream timeout")
    with SessionLocal() as db:
        svc, client = service(db, tmp_path, timeout)
        result = svc.sync(candidate2)
        assert result["failures"][0]["code"] == "PRODUCT_MEDIA_DOWNLOAD_FAILED"
        assert result["status"] == "DEGRADED"
        client.close()
    candidate3 = candidate(); evidence(candidate3)
    def protocol_error(request):
        raise httpx.RemoteProtocolError("connection reset")
    with SessionLocal() as db:
        svc, client = service(db, tmp_path, protocol_error)
        result = svc.sync(candidate3)
        assert result["failures"][0]["code"] == "PRODUCT_MEDIA_DOWNLOAD_FAILED"
        assert result["status"] == "DEGRADED"
        client.close()


def test_partial_failure_keeps_successful_official_asset(tmp_path):
    candidate_id = candidate()
    evidence(candidate_id, picture_id="OK", url="https://http2.mlstatic.com/ok.png", position=0)
    evidence(candidate_id, picture_id="BAD", url="https://http2.mlstatic.com/bad.png", position=1)
    def handler(request):
        return httpx.Response(500) if request.url.path.endswith("bad.png") else httpx.Response(200, headers={"content-type": "image/png"}, content=image_bytes())
    with SessionLocal() as db:
        svc, client = service(db, tmp_path, handler)
        result = svc.sync(candidate_id)
        assert result["status"] == "PARTIAL" and result["downloadedCount"] == 1 and result["failedCount"] == 1
        assert result["assets"][0]["classification"] == "HERO_IMAGE"
        assert db.scalar(select(func.count()).select_from(MediaAsset)) == 1
        client.close()


def test_unofficial_or_malformed_evidence_is_skipped(tmp_path):
    candidate_id = candidate(); evidence(candidate_id, official=False)
    with SessionLocal() as db:
        svc, client = service(db, tmp_path, lambda request: pytest.fail("untrusted evidence must not download"))
        result = svc.sync(candidate_id)
        assert result["status"] == "UNAVAILABLE" and result["skippedCount"] == 1
        assert result["reasonCode"] == "PRODUCT_MEDIA_SOURCE_NOT_OFFICIAL"
        client.close()


def test_product_media_analyzer_and_broll_director_use_ingested_assets(tmp_path, monkeypatch, client):
    candidate_id = candidate(); evidence(candidate_id, picture_id="H", url="https://http2.mlstatic.com/hero.png")
    with SessionLocal() as db:
        svc, ingestion_client = service(db, tmp_path); result = svc.sync(candidate_id); ingestion_client.close()
        monkeypatch.setattr("apps.api.app.services.product_media.perceptual_fingerprint", lambda path: "sha:" + sha256(path.read_bytes()).hexdigest()[:16])
        bundle = ProductMediaAnalyzer().analyze(db, candidate_id)
        assert bundle["assetCount"] == bundle["uniqueVisualGroups"] == 1
        assert bundle["assets"][0]["assetId"] == result["assets"][0]["mediaAssetId"]
        bundle_response = client.get(f"/api/v1/product-media-bundles/{candidate_id}")
        assert bundle_response.status_code == 200
        assert bundle_response.json()["assetCount"] == bundle_response.json()["uniqueVisualGroups"] == 1
        selected = BrollDirector().assign([{}], "HOOK", bundle)
        assert selected[0]["assetId"] == result["assets"][0]["mediaAssetId"]


def test_sync_and_current_endpoints_use_explicit_service(tmp_path, client, monkeypatch):
    candidate_id = candidate(); evidence(candidate_id)
    original = MarketplaceProductMediaService
    def factory(db):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": "image/png"}, content=image_bytes()))
        instance = original(db, client=httpx.Client(transport=transport, follow_redirects=False), dns_resolver=public_dns, storage=MediaStorage(tmp_path))
        instance._owns_client = True
        return instance
    monkeypatch.setattr("apps.api.app.services.marketplace_media_ingestion.MarketplaceProductMediaService", factory)
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    response = client.post(f"/api/v1/candidates/{candidate_id}/product-media/sync")
    assert response.status_code == 200 and response.json()["downloadedCount"] == 1
    current = client.get(f"/api/v1/candidates/{candidate_id}/product-media")
    assert current.status_code == 200 and current.json()["assetCount"] == 1


def test_pipeline_asset_resolver_never_mixes_candidate_assets(tmp_path, client, monkeypatch):
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    creative_id, campaign_id, *_ = make_creative(scenes=1)
    with SessionLocal() as db:
        campaign_candidate_id = db.get(__import__("apps.api.app.db.models", fromlist=["Campaign"]).Campaign, campaign_id).candidate_id
        db.get(CuratorCandidate, campaign_candidate_id).provider = "MERCADO_LIVRE"
        db.commit()
    evidence(campaign_candidate_id, picture_id="A", url="https://http2.mlstatic.com/candidate-a.png")
    with SessionLocal() as db:
        svc, network = service(db, tmp_path); synced = svc.sync(campaign_candidate_id); network.close()
        candidate_b = CuratorCandidate(provider="MERCADO_LIVRE", site_id="MLB", source_type="MANUAL", entity_type="ITEM", external_id="MLB999999999")
        db.add(candidate_b); db.commit(); db.refresh(candidate_b)
        asset_b = add_asset(db, "b.png", "image/png", image_bytes(color=(0, 0, 230)), "PRODUCT_IMAGE", "CANDIDATE", candidate_b.id, "Produto de outro candidato", classification="HERO_IMAGE")
        response = create(client, creative_id)
        assert response.status_code == 201
        job = db.get(MediaJob, response.json()["id"]); job.status = "PREPARING"; db.commit()
        captured = []
        class CaptureRenderer(FakeSceneRenderer):
            def render(self, spec, audio, width, height):
                captured.append(spec.product_asset_ids)
                return super().render(spec, audio, width, height)
        run_pipeline(db, job.id, voice=FakeVoiceRenderer(), scene_renderer=CaptureRenderer(),
                     composer=FakeTimelineComposer(), validator=FakeMediaValidator())
        assert captured and synced["assets"][0]["mediaAssetId"] in captured[0]
        assert asset_b.id not in captured[0]
        assert set(captured[0]) == {item.id for item in db.scalars(select(MediaAsset).where(
            MediaAsset.owner_type == "CANDIDATE", MediaAsset.owner_id == campaign_candidate_id,
            MediaAsset.asset_type == "PRODUCT_IMAGE", MediaAsset.active == True))}
