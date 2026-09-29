from __future__ import annotations

from sqlalchemy.orm import Session

from apps.api.app.db.models import AppSettings
from apps.api.app.integrations.mercado_livre.radar import MercadoLivreRadar, RadarDomainError
from apps.api.app.services.operations import log_decision


class PreferredRadarExecutionService:
    """Aggregate isolated existing Radar runs for configured category scope."""
    def __init__(self, db: Session, radar: MercadoLivreRadar | None = None):
        self.db=db; self.radar=radar or MercadoLivreRadar(db); self.owns=radar is None
    def close(self):
        if self.owns: self.radar.close()
    def run(self) -> dict:
        settings=self.db.get(AppSettings,1)
        ids=list((settings.preferred_marketplace_category_ids if settings else []) or [])
        global_enabled=bool(settings and settings.include_global_trends_outside_preferred_categories)
        if not ids:
            return {"status":"NO_PREFERRED_CATEGORIES","message":"Nenhuma categoria preferida foi configurada.","preferredCategoryIds":[],"includeGlobalTrends":global_enabled,"categoriesRequested":0,"categoriesCompleted":0,"categoriesPartial":0,"categoriesFailed":0,"globalIncluded":False,"globalSucceeded":False,"runsCreated":0,"signalsFound":0,"runs":[],"failures":[]}
        log_decision(self.db,"OPERATOR","APP_SETTINGS","PREFERRED_RADAR_RUN_STARTED",metadata={"categoryIds":ids,"categoryCount":len(ids),"includeGlobalTrends":global_enabled})
        runs=[]; failures=[]
        for category_id in ids:
            try:
                row=self.radar.run(category_id,include_global=False); runs.append({"runId":row.id,"categoryId":category_id,"status":row.status,"discoveredCount":row.discovered_count})
            except RadarDomainError as exc: failures.append({"categoryId":category_id,"reasonCode":str(exc)})
        global_succeeded=False
        if global_enabled:
            try:
                row=self.radar.run(None,include_global=True); runs.append({"runId":row.id,"categoryId":None,"status":row.status,"discoveredCount":row.discovered_count}); global_succeeded=row.status in {"COMPLETED","PARTIAL"}
                if not global_succeeded: failures.append({"categoryId":None,"reasonCode":row.error_summary or "RADAR_FAILED"})
            except RadarDomainError as exc: failures.append({"categoryId":None,"reasonCode":str(exc)})
        category_runs=[row for row in runs if row["categoryId"] is not None]
        completed=sum(row["status"]=="COMPLETED" for row in category_runs)
        partial=sum(row["status"]=="PARTIAL" for row in category_runs)
        failed=len(ids)-completed-partial
        useful=completed+partial+(1 if global_succeeded else 0)
        status="COMPLETED" if completed==len(ids) and not failures and (not global_enabled or global_succeeded) else "PARTIAL" if useful else "FAILED"
        result={"status":status,"preferredCategoryIds":ids,"includeGlobalTrends":global_enabled,"categoriesRequested":len(ids),"categoriesCompleted":completed,"categoriesPartial":partial,"categoriesFailed":failed,"globalIncluded":global_enabled,"globalSucceeded":global_succeeded,"runsCreated":len(runs),"signalsFound":sum(x["discoveredCount"] for x in runs),"runs":runs,"failures":failures}
        log_decision(self.db,"SYSTEM","APP_SETTINGS","PREFERRED_RADAR_RUN_COMPLETED",metadata={"categoryIds":ids,"categoryCount":len(ids),"includeGlobalTrends":global_enabled,"runsCreated":len(runs),"signalsFound":result["signalsFound"],"failuresCount":len(failures)})
        self.db.commit(); return result
