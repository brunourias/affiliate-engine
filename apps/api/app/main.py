from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apps.api.app.api.routes import router
from apps.api.app.core.config import settings
from apps.api.app.core.logging import configure_logging
from apps.api.app.services.scheduler import scheduler
from apps.api.app.db.session import SessionLocal
from apps.api.app.services.media_pipeline import recover_interrupted
configure_logging(settings.log_level); log=logging.getLogger("app")
@asynccontextmanager
async def lifespan(app):
    log.info("application_startup")
    with SessionLocal() as db:recover_interrupted(db)
    scheduler.start(); yield; await scheduler.stop(); log.info("application_shutdown")
app=FastAPI(title="Affiliate Engine API",version="1.0.0-v1a",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=settings.cors_origin_list,allow_credentials=False,allow_methods=["GET","POST","PATCH","DELETE","OPTIONS"],allow_headers=["Content-Type"])
app.include_router(router,prefix="/api/v1")
