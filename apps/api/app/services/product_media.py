import hashlib,subprocess
from collections import Counter
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from apps.api.app.core.config import settings
from apps.api.app.db.models import MediaAsset
from apps.api.app.services.media_storage import MediaStorage

CLASSIFICATIONS={"HERO_IMAGE","ALTERNATE_IMAGE","DETAIL_IMAGE","ACCESSORY_IMAGE","PACKAGE_IMAGE","CONTEXT_IMAGE","FEATURE_IMAGE","VIDEO_CLIP","UNKNOWN_PRODUCT_MEDIA"}
PURPOSE_PREFERENCES={"HOOK":["HERO_IMAGE","ALTERNATE_IMAGE"],"PROBLEM":["ALTERNATE_IMAGE","CONTEXT_IMAGE"],"VALUE":["DETAIL_IMAGE","FEATURE_IMAGE"],"PROOF_OR_REASON":["DETAIL_IMAGE","ACCESSORY_IMAGE","PACKAGE_IMAGE"],"WARNING":["DETAIL_IMAGE","HERO_IMAGE"],"OBJECTION":["DETAIL_IMAGE","HERO_IMAGE"],"CTA":["HERO_IMAGE","ALTERNATE_IMAGE"]}

def perceptual_fingerprint(path:Path)->str:
    if not path.is_file():return "missing:"+hashlib.sha256(str(path).encode()).hexdigest()[:16]
    try:
        result=subprocess.run([settings.ffmpeg_path,"-v","error","-i",str(path),"-vf","scale=9:8,format=gray","-frames:v","1","-f","rawvideo","pipe:1"],shell=False,capture_output=True,timeout=20,check=True);pixels=result.stdout
        if len(pixels)>=72:return f"dh:{int(''.join('1' if pixels[y*9+x]>pixels[y*9+x+1] else '0' for y in range(8) for x in range(8)),2):016x}"
    except (OSError,subprocess.SubprocessError):pass
    return "sha:"+hashlib.sha256(path.read_bytes()).hexdigest()[:16]

def hamming(left:str,right:str)->int:
    if not left.startswith("dh:") or not right.startswith("dh:"):return 0 if left==right else 65
    return (int(left[3:],16)^int(right[3:],16)).bit_count()

class ProductMediaAnalyzer:
    def analyze(self,db:Session,owner_id:str)->dict:
        rows=db.scalars(select(MediaAsset).where(MediaAsset.owner_type=="CANDIDATE",MediaAsset.owner_id==owner_id,MediaAsset.active==True,MediaAsset.asset_type.in_(("PRODUCT_IMAGE","PRODUCT_VIDEO"))).order_by(MediaAsset.created_at)).all();items=[];groups=[]
        for row in rows:
            path=MediaStorage().resolve(row.relative_path);fingerprint=perceptual_fingerprint(path);group=next((index for index,value in enumerate(groups) if hamming(value,fingerprint)<=8),None)
            if group is None:groups.append(fingerprint);group=len(groups)-1
            meta=row.metadata_ or {};classification=meta.get("classification") if meta.get("classification") in CLASSIFICATIONS else ("VIDEO_CLIP" if row.asset_type=="PRODUCT_VIDEO" else "UNKNOWN_PRODUCT_MEDIA");quality=min(100,round(((row.width or 0)*(row.height or 0))**.5/12)) if row.width and row.height else 50
            items.append({"assetId":row.id,"mediaType":row.asset_type,"width":row.width,"height":row.height,"aspectRatio":round(row.width/row.height,3) if row.width and row.height else None,"hasAlpha":bool(meta.get("hasAlpha")),"classification":classification,"confidence":"HIGH" if meta.get("classification") else "LOW","qualityScore":quality,"visualFingerprint":fingerprint,"duplicateGroup":f"PRODUCT_MEDIA_{group+1:02}","usableFor":meta.get("usableFor") or ["GENERAL"],"warnings":[] if path.is_file() else ["FILE_MISSING"]})
        unique=len(groups);types=len({x["classification"] for x in items});videos=sum(x["mediaType"]=="PRODUCT_VIDEO" for x in items);score=min(100,unique*20+max(0,types-1)*10+videos*15);level="HIGH" if score>=61 else "MEDIUM" if score>=31 else "LOW"
        return {"ownerId":owner_id,"assetCount":len(items),"uniqueVisualGroups":unique,"videoCount":videos,"detailCount":sum(x["classification"]=="DETAIL_IMAGE" for x in items),"heroCount":sum(x["classification"]=="HERO_IMAGE" for x in items),"diversityScore":score,"diversityLevel":level,"qualityCheck":"PASS" if unique>=3 else "WARNING","warning":None if unique>=3 else "Limited source media: visual variation is renderer-generated.","assets":items}

class BrollDirector:
    def assign(self,shots:list,purpose:str|None,bundle:dict)->list[dict]:
        assets=[x for x in bundle["assets"] if not x["warnings"]];preferences=PURPOSE_PREFERENCES.get((purpose or "").upper(),[]);ranked=sorted(assets,key=lambda x:(preferences.index(x["classification"]) if x["classification"] in preferences else 99,-x["qualityScore"],x["assetId"]));result=[];last_group=None;usage=Counter()
        for _shot in shots:
            choices=[x for x in ranked if x["duplicateGroup"]!=last_group] or ranked
            selected=min(choices,key=lambda x:(usage[x["assetId"]],ranked.index(x))) if choices else None
            if selected:last_group=selected["duplicateGroup"]
            if selected:usage[selected["assetId"]]+=1
            result.append(selected)
        return result

def repetition_metrics(assignments:list[dict|None])->dict:
    ids=[x["assetId"] for x in assignments if x];groups=[x["duplicateGroup"] for x in assignments if x];counts=Counter(ids);runs=[];last=None;run=0
    for value in ids:
        run=run+1 if value==last else 1;runs.append(run);last=value
    return {"totalShots":len(assignments),"uniqueSourceAssets":len(set(ids)),"uniqueVisualGroups":len(set(groups)),"sourceAssetSwitches":sum(a!=b for a,b in zip(ids,ids[1:])),"longestSameAssetRun":max(runs,default=0),"percentageUsingMostCommonAsset":round(max(counts.values(),default=0)*100/max(1,len(ids)),1)}
