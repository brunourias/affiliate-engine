from __future__ import annotations
from datetime import datetime,timezone
from hashlib import sha256
import json,re
from urllib.parse import urlsplit,urlunsplit
from uuid import NAMESPACE_URL,uuid5
import httpx
from sqlalchemy import select,update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from apps.api.app.core.config import settings
from apps.api.app.db.models import AppSettings,Creative,PublicationExecution
from apps.api.app.services.instagram_oauth import InstagramConnectionService,SecureTokenStore,WindowsCredentialManagerTokenStore,normalize_instagram_account_type
from apps.api.app.services.media_delivery import PublicMediaReachabilityValidator
from apps.api.app.services.media_storage import MediaStorage
from apps.api.app.services.operations import log_decision,settings_row
from apps.api.app.services.publication_connectors import CaptionComposer

CONNECTOR="INSTAGRAM_CONTENT_PUBLISHING";REQUIRED_SCOPE="instagram_business_content_publish"
def now():return datetime.now(timezone.utc)

class InstagramPublishError(Exception):
    def __init__(self,code:str,message:str,status=409):super().__init__(message);self.code=code;self.message=message;self.status=status

class InstagramContentPublishingClient:
    def __init__(self,http_client=None):self.http=http_client
    def _request(self,method:str,path:str,token:str,**kwargs)->dict:
        try:
            if self.http:response=self.http.request(method,"https://graph.instagram.com"+path,headers={"Authorization":f"Bearer {token}"},**kwargs)
            else:
                with httpx.Client(timeout=settings.instagram_oauth_timeout_seconds) as client:response=client.request(method,"https://graph.instagram.com"+path,headers={"Authorization":f"Bearer {token}"},**kwargs)
            response.raise_for_status();result=response.json()
            if not isinstance(result,dict):raise ValueError
            return result
        except httpx.TimeoutException as exc:raise InstagramPublishError("INSTAGRAM_API_TIMEOUT","O Instagram não respondeu dentro do tempo esperado.",504) from exc
        except Exception as exc:raise InstagramPublishError("INSTAGRAM_API_ERROR","O Instagram não concluiu a solicitação.",502) from exc
    def publishing_limit(self,account_id:str,token:str)->dict:return self._request("GET",f"/{account_id}/content_publishing_limit",token,params={"fields":"quota_usage,config"})
    def create_image_container(self,account_id:str,image_url:str,caption:str,token:str)->str:
        result=self._request("POST",f"/{account_id}/media",token,data={"image_url":image_url,"caption":caption});container=result.get("id")
        if not container:raise InstagramPublishError("CONTAINER_CREATION_FAILED","O Instagram não retornou o identificador do container.",502)
        return str(container)
    def publish_container(self,account_id:str,container_id:str,token:str)->str:
        result=self._request("POST",f"/{account_id}/media_publish",token,data={"creation_id":container_id});media=result.get("id")
        if not media:raise InstagramPublishError("PUBLICATION_FAILED","O Instagram não retornou o identificador da publicação.",502)
        return str(media)

class InstagramStaticPublisher:
    def __init__(self,db:Session,client:InstagramContentPublishingClient|None=None,store:SecureTokenStore|None=None):self.db=db;self.client=client or InstagramContentPublishingClient();self.store=store or WindowsCredentialManagerTokenStore()
    def publish(self,creative_id:str,candidate_id:str,confirm:bool)->dict:
        if confirm is not True:raise InstagramPublishError("EXPLICIT_CONFIRMATION_REQUIRED","Confirme explicitamente a publicação.")
        creative=self.db.get(Creative,creative_id)
        if not creative:raise InstagramPublishError("CREATIVE_NOT_FOUND","Creative não encontrado.",404)
        if creative.status!="APPROVED":raise InstagramPublishError("CREATIVE_NOT_APPROVED","O Creative precisa estar aprovado.")
        package=self._manifest(f"publication_packages/{creative_id}/{candidate_id}/manifest.json","PUBLICATION_PACKAGE_NOT_FOUND")
        self._validate_package(package,creative_id,candidate_id)
        delivery=self._manifest(f"public_delivery/manifests/{candidate_id}/media-delivery-manifest.json","MEDIA_DELIVERY_NOT_READY")
        image_url=self._validate_delivery(delivery,candidate_id)
        connection=InstagramConnectionService(self.db,self.store).connection()
        if not connection or connection.status!="CONNECTED" or not connection.token_store_reference:raise InstagramPublishError("INSTAGRAM_CONNECTION_REQUIRED","Conecte uma conta profissional do Instagram.")
        if not connection.account_id:raise InstagramPublishError("INSTAGRAM_ACCOUNT_ID_REQUIRED","A conexão do Instagram não possui um identificador de conta válido.")
        account_type=normalize_instagram_account_type(connection.account_type)
        if account_type not in {"BUSINESS","CREATOR"}:raise InstagramPublishError("ACCOUNT_NOT_SUPPORTED","A conta do Instagram precisa ser Business ou Creator.")
        if REQUIRED_SCOPE not in (connection.scopes or []):raise InstagramPublishError("INSTAGRAM_PERMISSION_REQUIRED","A permissão de publicação do Instagram não foi concedida.")
        execution_fingerprint=sha256(f"{package['packageFingerprint']}:{connection.account_id}:{CONNECTOR}".encode()).hexdigest();existing=self.db.scalar(select(PublicationExecution).where(PublicationExecution.execution_fingerprint==execution_fingerprint))
        if existing:
            if existing.status=="PUBLISHED":return self._public(existing)
            if existing.status in {"PUBLISHING","FAILED"}:raise InstagramPublishError("EXECUTION_ALREADY_ATTEMPTED","Esta execução já iniciou uma tentativa remota e não será repetida automaticamente.")
            execution=existing
        else:
            execution=PublicationExecution(id=str(uuid5(NAMESPACE_URL,execution_fingerprint)),creative_id=creative_id,publication_candidate_id=candidate_id,package_fingerprint=package["packageFingerprint"],execution_fingerprint=execution_fingerprint,channel="INSTAGRAM",connector=CONNECTOR,status="PLANNED");self.db.add(execution)
            try:self.db.commit()
            except IntegrityError:
                self.db.rollback();execution=self.db.scalar(select(PublicationExecution).where(PublicationExecution.execution_fingerprint==execution_fingerprint))
                if execution and execution.status=="PUBLISHED":return self._public(execution)
                if not execution:raise InstagramPublishError("EXECUTION_ALREADY_ATTEMPTED","Esta execução já foi iniciada e não será repetida automaticamente.")
        self._assert_switches();caption=CaptionComposer().compose(creative.cta or "",package.get("disclosurePlan") or {},[],[])["text"]
        execution,acquired=self._acquire_execution(execution.id,connection.account_id)
        if not acquired:return self._public(execution)
        try:
            token=self.store.load(connection.token_store_reference)
            self._assert_switches();execution.remote_request_executed=True;self.db.commit();limit=self.client.publishing_limit(connection.account_id,token);limit_record=limit.get("data",[limit])[0] if isinstance(limit.get("data",[limit]),list) and limit.get("data",[limit]) else limit;usage=limit_record.get("quota_usage");maximum=(limit_record.get("config") or {}).get("quota_total") if isinstance(limit_record.get("config"),dict) else None
            if usage is not None and maximum is not None and int(usage)>=int(maximum):raise InstagramPublishError("PUBLISHING_LIMIT_REACHED","O limite de publicação do Instagram foi atingido.")
            self._assert_switches();container_id=self.client.create_image_container(connection.account_id,image_url,caption,token);execution.container_id=container_id;log_decision(self.db,"SYSTEM","PUBLICATION_EXECUTION","INSTAGRAM_CONTAINER_CREATED",execution.id,metadata=self._metadata(execution,connection.account_id));self.db.commit()
            self._assert_switches();platform_media_id=self.client.publish_container(connection.account_id,container_id,token);execution.platform_media_id=platform_media_id;execution.status="PUBLISHED";execution.published_at=now();log_decision(self.db,"OPERATOR","PUBLICATION_EXECUTION","INSTAGRAM_PUBLICATION_SUCCEEDED",execution.id,metadata=self._metadata(execution,connection.account_id));self.db.commit();return self._public(execution)
        except (InstagramPublishError,KeyError,RuntimeError) as exc:
            code=exc.code if isinstance(exc,InstagramPublishError) else "SECURE_TOKEN_UNAVAILABLE";execution.remote_request_executed=execution.remote_request_executed or isinstance(exc,InstagramPublishError) and code in {"INSTAGRAM_API_TIMEOUT","INSTAGRAM_API_ERROR"};execution.status="FAILED";execution.failure_code=code;log_decision(self.db,"SYSTEM","PUBLICATION_EXECUTION","INSTAGRAM_PUBLICATION_FAILED",execution.id,reason="A publicação não foi concluída.",metadata={**self._metadata(execution,connection.account_id),"reasonCode":code});self.db.commit();raise InstagramPublishError(code,exc.message if isinstance(exc,InstagramPublishError) else "Não foi possível acessar a credencial segura.",exc.status if isinstance(exc,InstagramPublishError) else 409) from exc
    def _acquire_execution(self,execution_id:str,account_id:str)->tuple[PublicationExecution,bool]:
        acquired=self.db.execute(update(PublicationExecution).where(PublicationExecution.id==execution_id,PublicationExecution.status=="PLANNED").values(status="PUBLISHING",updated_at=now())).rowcount
        if acquired!=1:
            self.db.rollback();current=self.db.get(PublicationExecution,execution_id)
            if current and current.status=="PUBLISHED":return current,False
            raise InstagramPublishError("EXECUTION_ALREADY_ATTEMPTED","Esta execução já iniciou uma tentativa remota e não será repetida automaticamente.")
        execution=self.db.get(PublicationExecution,execution_id);log_decision(self.db,"OPERATOR","PUBLICATION_EXECUTION","INSTAGRAM_PUBLICATION_REQUESTED",execution.id,metadata=self._metadata(execution,account_id));self.db.commit();return execution,True
    def _assert_switches(self):
        config=settings_row(self.db)
        if not config.system_automation_enabled:raise InstagramPublishError("KILL_SWITCH_ACTIVE","O Kill Switch está ativo.")
        if not config.publishing_enabled:raise InstagramPublishError("PUBLISHING_DISABLED","A publicação está desabilitada nas configurações.")
    @staticmethod
    def _validate_package(package:dict,creative_id:str,candidate_id:str):
        if package.get("creativeId")!=creative_id or package.get("publicationCandidateId")!=candidate_id:raise InstagramPublishError("PUBLICATION_PACKAGE_MISMATCH","O pacote não corresponde ao Creative.")
        if package.get("readinessStatus") not in {"READY","READY_WITH_WARNINGS"} or package.get("blockers"):raise InstagramPublishError("PUBLICATION_PACKAGE_NOT_READY","O pacote de publicação ainda possui bloqueios.")
        if package.get("channel")!="INSTAGRAM":raise InstagramPublishError("CHANNEL_NOT_SUPPORTED","O pacote não pertence ao Instagram.")
        if package.get("format")!="STATIC_CARD":raise InstagramPublishError("FORMAT_NOT_SUPPORTED","Nesta fase somente imagem estática é permitida.")
        if len(package.get("assetFiles") or [])!=1:raise InstagramPublishError("SINGLE_IMAGE_REQUIRED","Selecione exatamente uma imagem estática.")
    @staticmethod
    def _validate_delivery(delivery:dict,candidate_id:str)->str:
        hosted=delivery.get("hostedAssets") or []
        if delivery.get("publicationCandidateId")!=candidate_id or delivery.get("readiness")!="READY":raise InstagramPublishError("MEDIA_DELIVERY_NOT_READY","A entrega pública da mídia não está pronta.")
        if delivery.get("format")!="STATIC_CARD" or len(hosted)!=1:raise InstagramPublishError("SINGLE_IMAGE_REQUIRED","A entrega deve conter exatamente uma imagem estática.")
        asset=hosted[0];url=asset.get("publicUrl");parts=urlsplit(url or "");origin=urlunsplit((parts.scheme,parts.netloc,"","",""))
        try:
            expires=datetime.fromisoformat(asset["expiresAt"]);expires=expires.replace(tzinfo=timezone.utc) if expires.tzinfo is None else expires;expired=expires<=now()
        except (KeyError,TypeError,ValueError):expired=True
        if asset.get("contentType") not in {"image/jpeg","image/png"} or asset.get("status")!="AVAILABLE" or expired or parts.scheme!="https" or PublicMediaReachabilityValidator().validate(origin)!="VALID":raise InstagramPublishError("PUBLIC_MEDIA_SOURCE_REQUIRED","A imagem precisa ter uma URL HTTPS pública válida.")
        return url
    @staticmethod
    def _manifest(relative:str,code:str)->dict:
        if not re.fullmatch(r"[A-Za-z0-9_./-]+",relative) or ".." in relative:raise InstagramPublishError(code,"Manifesto de publicação inválido.")
        path=MediaStorage().resolve(relative)
        try:return json.loads(path.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError) as exc:raise InstagramPublishError(code,"Manifesto de publicação não encontrado.") from exc
    @staticmethod
    def _metadata(row:PublicationExecution,account_id:str)->dict:return {"executionId":row.id,"creativeId":row.creative_id,"candidateId":row.publication_candidate_id,"packageFingerprint":row.package_fingerprint,"accountId":account_id,"containerId":row.container_id,"platformMediaId":row.platform_media_id}
    @staticmethod
    def _public(row:PublicationExecution)->dict:
        published=row.published_at.replace(tzinfo=timezone.utc) if row.published_at and row.published_at.tzinfo is None else row.published_at
        return {"executionId":row.id,"status":row.status,"channel":row.channel,"connector":row.connector,"platformMediaId":row.platform_media_id,"remoteRequestExecuted":row.remote_request_executed,"failureCode":row.failure_code,"publishedAt":published.isoformat() if published else None}
