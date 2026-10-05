"""Materialize official Mercado Livre picture evidence as local product assets."""
from __future__ import annotations

import hashlib
import ipaddress
import socket
import warnings
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.config import settings
from apps.api.app.db.models import CuratorCandidate, CuratorEvidence, MediaAsset
from apps.api.app.services.media_storage import MediaStorage
from apps.api.app.services.operations import log_decision

OFFICIAL_SOURCE = "MERCADO_LIVRE_OFFICIAL_API"
PICTURE_TYPES = {"CATALOG_PICTURE", "LISTING_PICTURE"}
MIME_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_REDIRECTS = 3
REQUEST_TIMEOUT_SECONDS = 12.0
USER_AGENT = "AffiliateEngine/0.2 product-media-ingestion"


class ProductMediaError(ValueError):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class MarketplaceProductMediaService:
    def __init__(self, db: Session, *, client: httpx.Client | None = None, dns_resolver=None,
                 storage: MediaStorage | None = None):
        self.db = db
        self.client = client or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False,
                                              headers={"User-Agent": USER_AGENT})
        self._owns_client = client is None
        self.dns_resolver = dns_resolver or socket.getaddrinfo
        self.storage = storage or MediaStorage()

    def close(self):
        if self._owns_client:
            self.client.close()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _allowed_host(host: str) -> bool:
        host = host.lower().rstrip(".")
        return host == "http2.mlstatic.com" or host == "mlstatic.com" or host.endswith(".mlstatic.com")

    def _validate_url(self, value: str) -> tuple[str | None, str | None]:
        try:
            parts = urlsplit(value)
            host = (parts.hostname or "").lower().rstrip(".")
            port = parts.port
        except (TypeError, ValueError):
            return None, "PRODUCT_MEDIA_REMOTE_HOST_NOT_ALLOWED"
        if (parts.scheme.lower() != "https" or not host or parts.username or parts.password
                or port not in (None, 443) or not self._allowed_host(host)):
            return None, "PRODUCT_MEDIA_REMOTE_HOST_NOT_ALLOWED"
        try:
            literal = ipaddress.ip_address(host.strip("[]"))
            if not literal.is_global:
                return None, "PRODUCT_MEDIA_REMOTE_HOST_NOT_ALLOWED"
        except ValueError:
            try:
                addresses = self.dns_resolver(host, 443, type=socket.SOCK_STREAM)
            except (OSError, socket.gaierror):
                return None, "PRODUCT_MEDIA_REMOTE_HOST_NOT_ALLOWED"
            if not addresses:
                return None, "PRODUCT_MEDIA_REMOTE_HOST_NOT_ALLOWED"
            for entry in addresses:
                try:
                    if not ipaddress.ip_address(entry[4][0]).is_global:
                        return None, "PRODUCT_MEDIA_REMOTE_HOST_NOT_ALLOWED"
                except (IndexError, TypeError, ValueError):
                    return None, "PRODUCT_MEDIA_REMOTE_HOST_NOT_ALLOWED"
        return host, None

    @staticmethod
    def _evidence_picture(row: CuratorEvidence) -> tuple[dict | None, str | None]:
        value = row.value_json if isinstance(row.value_json, dict) else {}
        if row.source_kind != OFFICIAL_SOURCE or value.get("provenance") != OFFICIAL_SOURCE:
            return None, "PRODUCT_MEDIA_SOURCE_NOT_OFFICIAL"
        remote_url = value.get("secure_url") or value.get("url")
        if not isinstance(remote_url, str) or not remote_url.strip():
            return None, "PRODUCT_MEDIA_SOURCE_NOT_FOUND"
        picture_id = value.get("id")
        if picture_id is None or not str(picture_id).strip():
            picture_id = "url:" + hashlib.sha256(remote_url.strip().encode("utf-8")).hexdigest()[:32]
        try:
            position = max(0, int(value.get("position", 0)))
        except (TypeError, ValueError):
            position = 0
        return {
            "evidence": row,
            "remoteUrl": remote_url.strip(),
            "remotePictureId": str(picture_id)[:200],
            "position": position,
            "evidenceType": row.evidence_type,
            "sourceReference": row.source_reference,
            "sourceEvidenceId": row.id,
        }, None

    @staticmethod
    def _coalesce_pictures(pictures: list[dict]) -> list[dict]:
        # A listing picture is more specific than a catalog picture. Keeping the
        # first matching remote ID (or exact URL when no ID exists) enforces that
        # precedence before any download is attempted.
        pictures.sort(key=lambda item: (
            0 if item["evidenceType"] == "LISTING_PICTURE" else 1,
            item["position"], item["sourceEvidenceId"],
        ))
        unique = []
        seen = set()
        for item in pictures:
            key = item["remotePictureId"]
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def _download(self, initial_url: str) -> tuple[bytes | None, str | None, str | None]:
        current = initial_url
        for redirect_count in range(MAX_REDIRECTS + 1):
            _, unsafe_reason = self._validate_url(current)
            if unsafe_reason:
                return None, None, unsafe_reason
            try:
                with self.client.stream("GET", current, follow_redirects=False,
                                        headers={"User-Agent": USER_AGENT}) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location or redirect_count >= MAX_REDIRECTS:
                            return None, None, "PRODUCT_MEDIA_DOWNLOAD_FAILED"
                        next_url = urljoin(current, location)
                        if self._validate_url(next_url)[1]:
                            return None, None, "PRODUCT_MEDIA_REMOTE_HOST_NOT_ALLOWED"
                        current = next_url
                        continue
                    if response.status_code != 200:
                        return None, None, "PRODUCT_MEDIA_DOWNLOAD_FAILED"
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if content_type not in MIME_EXTENSIONS:
                        return None, None, "PRODUCT_MEDIA_UNSUPPORTED_TYPE"
                    max_bytes = max(1, int(settings.media_asset_max_bytes))
                    content_length = response.headers.get("content-length")
                    if content_length:
                        try:
                            if int(content_length) > max_bytes:
                                return None, None, "PRODUCT_MEDIA_TOO_LARGE"
                        except ValueError:
                            pass
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            return None, None, "PRODUCT_MEDIA_TOO_LARGE"
                    if not body:
                        return None, None, "PRODUCT_MEDIA_INVALID_CONTENT"
                    return bytes(body), content_type, None
            except (httpx.HTTPError, OSError):
                return None, None, "PRODUCT_MEDIA_DOWNLOAD_FAILED"
        return None, None, "PRODUCT_MEDIA_DOWNLOAD_FAILED"

    @staticmethod
    def _validate_image(data: bytes, mime: str, remote_url: str) -> tuple[int, int, str | None]:
        extension = MIME_EXTENSIONS.get(mime)
        if not extension:
            raise ProductMediaError("PRODUCT_MEDIA_UNSUPPORTED_TYPE", "O formato da imagem não é compatível.")
        remote_suffix = Path(urlsplit(remote_url).path).suffix.lower()
        expected_suffixes = {"image/jpeg": {".jpg", ".jpeg"}, "image/png": {".png"}, "image/webp": {".webp"}}
        if remote_suffix and remote_suffix in {".jpg", ".jpeg", ".png", ".webp"} and remote_suffix not in expected_suffixes[mime]:
            raise ProductMediaError("PRODUCT_MEDIA_INVALID_CONTENT", "O formato informado não corresponde à imagem.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(data)) as image:
                    actual = (image.format or "").upper()
                    expected = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}[mime]
                    if actual != expected:
                        raise ProductMediaError("PRODUCT_MEDIA_INVALID_CONTENT", "O conteúdo recebido não é uma imagem válida.")
                    image.verify()
                with Image.open(BytesIO(data)) as image:
                    image.load()
                    width, height = image.size
            if width <= 0 or height <= 0:
                raise ProductMediaError("PRODUCT_MEDIA_INVALID_CONTENT", "A imagem não possui dimensões válidas.")
            return width, height, extension
        except ProductMediaError:
            raise
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ProductMediaError("PRODUCT_MEDIA_INVALID_CONTENT", "O conteúdo recebido não é uma imagem válida.") from exc

    def _existing_assets(self, candidate_id: str) -> list[MediaAsset]:
        return list(self.db.scalars(select(MediaAsset).where(
            MediaAsset.owner_type == "CANDIDATE", MediaAsset.owner_id == candidate_id,
            MediaAsset.asset_type == "PRODUCT_IMAGE",
        ).order_by(MediaAsset.created_at, MediaAsset.id)))

    @staticmethod
    def _asset_summary(asset: MediaAsset) -> dict:
        metadata = asset.metadata_ or {}
        return {
            "mediaAssetId": asset.id, "assetType": asset.asset_type,
            "ownerType": asset.owner_type, "ownerId": asset.owner_id,
            "logicalName": asset.logical_name, "classification": metadata.get("classification"),
            "mimeType": asset.mime_type, "width": asset.width, "height": asset.height,
            "fileSizeBytes": asset.file_size_bytes, "active": asset.active,
        }

    def current(self, candidate_id: str) -> dict:
        candidate = self.db.get(CuratorCandidate, candidate_id)
        if not candidate:
            raise ProductMediaError("CANDIDATE_NOT_FOUND", "Candidato não encontrado.", 404)
        if candidate.provider != "MERCADO_LIVRE":
            raise ProductMediaError("PRODUCT_MEDIA_SOURCE_NOT_OFFICIAL", "Este candidato não possui origem oficial do Mercado Livre.")
        rows = [asset for asset in self._existing_assets(candidate.id) if (asset.metadata_ or {}).get("provider") == "MERCADO_LIVRE"]
        return {"candidateId": candidate.id, "provider": "MERCADO_LIVRE",
                "status": "AVAILABLE" if any(item.active for item in rows) else "UNAVAILABLE",
                "assetCount": sum(bool(item.active) for item in rows),
                "assets": [self._asset_summary(item) for item in rows]}

    def sync(self, candidate_id: str) -> dict:
        candidate = self.db.get(CuratorCandidate, candidate_id)
        if not candidate:
            raise ProductMediaError("CANDIDATE_NOT_FOUND", "Candidato não encontrado.", 404)
        if candidate.provider != "MERCADO_LIVRE":
            raise ProductMediaError("PRODUCT_MEDIA_SOURCE_NOT_OFFICIAL", "Este candidato não possui origem oficial do Mercado Livre.")

        evidence_rows = list(self.db.scalars(select(CuratorEvidence).where(
            CuratorEvidence.candidate_id == candidate.id,
            CuratorEvidence.evidence_type.in_(PICTURE_TYPES),
        ).order_by(CuratorEvidence.observed_at, CuratorEvidence.id)))
        pictures = []
        skipped = 0
        source_errors = []
        for evidence in evidence_rows:
            picture, reason = self._evidence_picture(evidence)
            if reason:
                skipped += 1
                source_errors.append(reason)
            else:
                pictures.append(picture)
        pictures = self._coalesce_pictures(pictures)
        if not pictures:
            return {"candidateId": candidate.id, "provider": "MERCADO_LIVRE", "status": "UNAVAILABLE",
                    "reasonCode": "PRODUCT_MEDIA_SOURCE_NOT_FOUND" if not evidence_rows else "PRODUCT_MEDIA_SOURCE_NOT_OFFICIAL",
                    "sourcePictureCount": 0, "downloadedCount": 0, "reusedCount": 0,
                    "skippedCount": skipped, "failedCount": 0, "assets": []}

        existing = self._existing_assets(candidate.id)
        by_remote_id = {}
        by_hash = {}
        for asset in existing:
            metadata = asset.metadata_ or {}
            if metadata.get("provider") != "MERCADO_LIVRE":
                continue
            picture_id = metadata.get("remotePictureId")
            if picture_id:
                by_remote_id.setdefault(str(picture_id), asset)
            digest = metadata.get("contentHash")
            if digest:
                by_hash.setdefault(str(digest), asset)

        downloaded = reused = failed = 0
        reused_asset_ids: set[str] = set()
        failures = []
        output_assets = []
        created_paths: list[Path] = []
        changed = False
        hero_assigned = False
        sync_started = False
        active_output = False

        def append_asset(asset: MediaAsset) -> None:
            nonlocal active_output
            active_output = active_output or bool(asset.active)
            if not any(item["mediaAssetId"] == asset.id for item in output_assets):
                output_assets.append(self._asset_summary(asset))

        def count_reused(asset: MediaAsset) -> None:
            nonlocal reused
            if asset.id not in reused_asset_ids:
                reused_asset_ids.add(asset.id)
                reused += 1

        def start_log():
            nonlocal sync_started
            if not sync_started:
                log_decision(self.db, "OPERATOR", "PRODUCT_MEDIA", "PRODUCT_MEDIA_SYNC_STARTED", candidate.id,
                             metadata={"candidateId": candidate.id, "provider": "MERCADO_LIVRE", "sourcePictureCount": len(pictures)})
                sync_started = True

        try:
            for item in pictures:
                _, invalid_url = self._validate_url(item["remoteUrl"])
                if invalid_url:
                    failed += 1
                    failures.append({"remotePictureId": item["remotePictureId"], "code": invalid_url})
                    continue
                existing_asset = by_remote_id.get(item["remotePictureId"])
                if existing_asset:
                    count_reused(existing_asset)
                    metadata = dict(existing_asset.metadata_ or {})
                    desired_classification = "HERO_IMAGE" if not hero_assigned else "ALTERNATE_IMAGE"
                    hero_assigned = True
                    before = dict(metadata)
                    metadata.update({
                        "provider": "MERCADO_LIVRE", "sourceKind": OFFICIAL_SOURCE,
                        "sourceEvidenceType": item["evidenceType"], "sourceEvidenceId": item["sourceEvidenceId"],
                        "sourceReference": item["sourceReference"], "remotePictureId": item["remotePictureId"],
                        "remoteUrl": item["remoteUrl"], "position": item["position"],
                        "classification": metadata.get("classification") or desired_classification,
                        "contentHash": metadata.get("contentHash"),
                    })
                    if metadata != before:
                        start_log(); existing_asset.metadata_ = metadata; changed = True
                        log_decision(self.db, "SYSTEM", "MEDIA_ASSET", "PRODUCT_MEDIA_REUSED", existing_asset.id,
                                     metadata={"candidateId": candidate.id, "mediaAssetId": existing_asset.id,
                                               "remotePictureId": item["remotePictureId"], "sourceEvidenceId": item["sourceEvidenceId"],
                                               "position": item["position"], "classification": metadata.get("classification"),
                                               "contentHash": metadata.get("contentHash")})
                    append_asset(existing_asset)
                    continue

                data, mime, error = self._download(item["remoteUrl"])
                if error:
                    failed += 1
                    failures.append({"remotePictureId": item["remotePictureId"], "code": error})
                    continue
                downloaded += 1
                try:
                    width, height, extension = self._validate_image(data, mime, item["remoteUrl"])
                except ProductMediaError as exc:
                    failed += 1
                    failures.append({"remotePictureId": item["remotePictureId"], "code": exc.code})
                    continue
                digest = hashlib.sha256(data).hexdigest()
                duplicate = by_hash.get(digest)
                if duplicate:
                    count_reused(duplicate)
                    metadata = dict(duplicate.metadata_ or {})
                    known_ids = list(metadata.get("remotePictureIds") or [metadata.get("remotePictureId")])
                    known_ids = [value for value in known_ids if value]
                    if item["remotePictureId"] not in known_ids:
                        known_ids.append(item["remotePictureId"])
                    before = dict(metadata)
                    metadata["remotePictureIds"] = known_ids
                    metadata.setdefault("alternateEvidenceIds", [])
                    if item["sourceEvidenceId"] not in metadata["alternateEvidenceIds"]:
                        metadata["alternateEvidenceIds"].append(item["sourceEvidenceId"])
                    if item["evidenceType"] == "LISTING_PICTURE":
                        metadata.update({"sourceEvidenceType": item["evidenceType"], "sourceEvidenceId": item["sourceEvidenceId"],
                                         "sourceReference": item["sourceReference"], "remotePictureId": item["remotePictureId"],
                                         "remoteUrl": item["remoteUrl"], "position": item["position"]})
                    if metadata != before:
                        start_log(); duplicate.metadata_ = metadata; changed = True
                        log_decision(self.db, "SYSTEM", "MEDIA_ASSET", "PRODUCT_MEDIA_REUSED", duplicate.id,
                                     metadata={"candidateId": candidate.id, "mediaAssetId": duplicate.id,
                                               "remotePictureId": item["remotePictureId"], "sourceEvidenceId": item["sourceEvidenceId"],
                                               "position": item["position"], "classification": metadata.get("classification"),
                                               "contentHash": digest})
                    by_remote_id[item["remotePictureId"]] = duplicate
                    append_asset(duplicate)
                    continue

                classification = "HERO_IMAGE" if not hero_assigned else "ALTERNATE_IMAGE"
                hero_assigned = True
                relative, path = self.storage.asset_path(extension)
                path.write_bytes(data)
                created_paths.append(path)
                metadata = {
                    "provider": "MERCADO_LIVRE", "sourceKind": OFFICIAL_SOURCE,
                    "sourceEvidenceType": item["evidenceType"], "sourceEvidenceId": item["sourceEvidenceId"],
                    "sourceReference": item["sourceReference"], "remotePictureId": item["remotePictureId"],
                    "remoteUrl": item["remoteUrl"], "position": item["position"],
                    "classification": classification, "ingestedAt": self._now().isoformat(), "contentHash": digest,
                }
                asset = MediaAsset(asset_type="PRODUCT_IMAGE", owner_type="CANDIDATE", owner_id=candidate.id,
                                   logical_name=f"Mercado Livre — imagem {len(output_assets) + 1}"[:200],
                                   relative_path=relative, mime_type=mime, width=width, height=height,
                                   file_size_bytes=len(data), metadata_=metadata)
                self.db.add(asset); self.db.flush()
                by_remote_id[item["remotePictureId"]] = asset; by_hash[digest] = asset
                append_asset(asset)
                start_log(); changed = True
                log_decision(self.db, "SYSTEM", "MEDIA_ASSET", "PRODUCT_MEDIA_INGESTED", asset.id,
                             metadata={"candidateId": candidate.id, "mediaAssetId": asset.id,
                                       "remotePictureId": item["remotePictureId"], "sourceEvidenceId": item["sourceEvidenceId"],
                                       "position": item["position"], "classification": classification,
                                       "contentHash": digest})

            if changed or failed:
                start_log()
                status = "PARTIAL" if failed and output_assets else "DEGRADED" if failed else "AVAILABLE"
                log_decision(self.db, "OPERATOR", "PRODUCT_MEDIA", "PRODUCT_MEDIA_SYNC_COMPLETED", candidate.id,
                             metadata={"candidateId": candidate.id, "provider": "MERCADO_LIVRE",
                                       "sourcePictureCount": len(pictures), "downloadedCount": downloaded,
                                       "reusedCount": reused, "skippedCount": skipped,
                                       "failedCount": failed, "status": status})
            else:
                status = "AVAILABLE" if active_output else "UNAVAILABLE"
            self.db.commit()
        except Exception:
            self.db.rollback()
            for path in created_paths:
                path.unlink(missing_ok=True)
            raise

        reason_code = None
        if not output_assets:
            status = "DEGRADED"
            reason_code = (failures[0]["code"] if failures else
                           source_errors[0] if source_errors else "PRODUCT_MEDIA_SOURCE_NOT_FOUND")
        return {"candidateId": candidate.id, "provider": "MERCADO_LIVRE", "status": status,
                "reasonCode": reason_code, "sourcePictureCount": len(pictures),
                "downloadedCount": downloaded, "reusedCount": reused,
                "skippedCount": skipped, "failedCount": failed, "failures": failures,
                "assets": output_assets}
