from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func,select
from sqlalchemy.orm import Session

from apps.api.app.db.models import Campaign,Creative,CreativeScene,CuratorCandidate,DecisionLog
from apps.api.app.services.operations import log_decision
from apps.api.app.services.voice_director import direction_for_purpose,estimated_spoken_duration,pace_target_status

HOOK_TYPES={"CURIOSITY","PROBLEM","CONTRARIAN","QUESTION","VALUE","WARNING","COMPARISON"}
CREATIVE_ANGLES={"COST_BENEFIT","PROBLEM_SOLUTION","BEGINNER_FRIENDLY","HOME_USE","CONVENIENCE","COMPARISON","WARNING_BEFORE_BUYING","UNDERRATED","USE_CASE"}
CTA_TYPES={"CHECK_PRICE","CHECK_DETAILS","COMPARE","SEE_OFFER","SEE_IF_IT_FITS"}
VOICE_STYLES={"ENERGETIC","CURIOUS","CAUTION","EXPLANATORY","CONFIDENT","CTA"}


def _subject(db:Session,row:Creative)->str:
    from apps.api.app.services.creatives import resolve_content_subject
    campaign=db.get(Campaign,row.campaign_id);candidate=db.get(CuratorCandidate,campaign.candidate_id)
    return resolve_content_subject(candidate,campaign)


def choose_direction(db:Session,row:Creative)->dict:
    subject=_subject(db,row);normalized=subject.casefold();verdict=(row.editorial_verdict_snapshot or "").upper();price=(row.price_verdict_snapshot or "").upper()
    if verdict=="NOT_RECOMMENDED" or price in {"OVERPRICED","AVOID"}:angle,reason="WARNING_BEFORE_BUYING","A análise editorial ou de preço exige cautela antes da decisão."
    elif any(term in normalized for term in ("doméstic","casa","lar")):angle,reason="HOME_USE","O nome validado do produto indica um caso de uso doméstico."
    elif row.angle_type_snapshot=="LIMITATION_FIRST":angle,reason="WARNING_BEFORE_BUYING","O ângulo editorial existente prioriza limitações."
    else:angle,reason="USE_CASE","A direção prioriza adequação ao uso sem inventar atributos."
    persona="CAROL" if angle in {"HOME_USE","CONVENIENCE","BEGINNER_FRIENDLY"} else "BRUNO"
    hook_type="WARNING" if angle=="WARNING_BEFORE_BUYING" else "QUESTION" if angle in {"HOME_USE","USE_CASE"} else "VALUE"
    cta_type="SEE_IF_IT_FITS" if angle in {"HOME_USE","USE_CASE","WARNING_BEFORE_BUYING"} else "CHECK_DETAILS"
    return {"subject":subject,"creativeAngle":angle,"angleReason":reason,"persona":persona,"hookType":hook_type,"ctaType":cta_type}


def _copy(direction:dict,warnings:list|None=None)->tuple[str,str,list[dict]]:
    persona=direction["persona"]
    if direction["creativeAngle"]=="HOME_USE":
        hook="Você precisa mesmo de uma parafusadeira profissional pra usar em casa?" if persona=="CAROL" else "Pra usar em casa, precisa mesmo gastar numa parafusadeira profissional?"
        problem="Se é só pra montar um móvel ou fazer um reparo de vez em quando, provavelmente não."
        value="É aí que um modelo mais simples começa a fazer sentido."
        proof="A ideia é comparar com o que você realmente precisa em casa."
        objection="Agora, pra serviço pesado ou uso todo dia, eu já compararia com modelos mais robustos."
    elif direction["creativeAngle"]=="WARNING_BEFORE_BUYING":
        hook="Antes de comprar, pensa em como você realmente vai usar isso aqui.";problem="Tem diferença entre um uso de vez em quando e uma rotina mais pesada.";value="O ponto é escolher pelo seu uso, não só pela promessa.";proof="Olha os detalhes e os pontos de atenção antes de comparar.";objection="Se a exigência for maior, vale colocar outras opções na conta."
    else:
        hook="Isso aqui combina mesmo com o que você precisa?";problem="Primeiro, pensa no uso que vai fazer no dia a dia.";value="A escolha fica mais simples quando o caso de uso está claro.";proof="Confere os detalhes disponíveis e compara com a sua necessidade.";objection="Se o uso mudar, a melhor escolha também pode mudar."
    cta="Dá uma olhada nos detalhes e no preço atual antes de escolher." if direction["ctaType"] in {"CHECK_DETAILS","SEE_IF_IT_FITS"} else "Compara com as outras opções antes de decidir."
    warning_text=" ".join(str(x.get("message",x.get("code",""))) for x in (warnings or [])).strip()
    if warning_text:proof=f"{proof} {warning_text}"
    rows=[
        ("HOOK",hook,2.2,[("PRECISA MESMO DE UMA PROFISSIONAL?","PRODUCT_HERO",2.2)],persona,"HIGH","CURIOUS"),
        ("PROBLEM",problem,2.5,[("USO EM CASA","PRODUCT_HERO",1.2),("REPAROS OCASIONAIS","PRODUCT_CLOSEUP",1.3)],persona,"HIGH","EXPLANATORY"),
        ("VALUE",value,2.2,[("UMA OPÇÃO MAIS SIMPLES","TEXT_CARD",.9),("PODE SER O BASTANTE","PRODUCT_DETAIL",1.3)],persona,"MEDIUM","CONFIDENT"),
        ("PROOF_OR_REASON",proof,2.4,[("O QUE VOCÊ PRECISA?","PRODUCT_DETAIL",2.4)],None,"MEDIUM","EXPLANATORY"),
        ("OBJECTION",objection,2.7,[("USO PESADO? ATENÇÃO","WARNING",1.2),("COMPARE A CATEGORIA","COMPARISON",1.5)],persona,"HIGH","CAUTION"),
        ("CTA",cta,2.1,[("DETALHES + PREÇO ATUAL","CTA",2.1)],persona,"HIGH","CTA"),
    ]
    storyboard=[]
    for index,(purpose,text,duration,units,speaker,emphasis,_voice_style) in enumerate(rows):
        voice=direction_for_purpose(purpose)
        speech_id=f"segment-{index+1:02}";visual_units=[{"speechSegmentId":speech_id,"visualUnitIndex":unit_index,"visualIntent":intent,"onScreenText":on_screen,"estimatedDuration":unit_duration} for unit_index,(on_screen,intent,unit_duration) in enumerate(units)]
        storyboard.append({"orderIndex":index,"speechSegmentId":speech_id,"purpose":purpose,"scriptSegment":text,"onScreenText":visual_units[0]["onScreenText"],"visualIntent":visual_units[0]["visualIntent"],"recommendedDuration":duration,"productFocus":True,"avatarVisible":bool(speaker),"avatarSpeaker":speaker,"visualEmphasis":emphasis,"visualUnits":visual_units,"voiceDirection":voice.metadata()})
    return hook,cta,storyboard


def quality_checks(row:Creative,storyboard:list[dict],compliance_status="PASS")->dict:
    first=storyboard[0] if storyboard else {};has_cta=any(x["purpose"]=="CTA" and x["scriptSegment"].strip() for x in storyboard);long=any(x["recommendedDuration"]>3.5 or len(x["scriptSegment"].split())>20 for x in storyboard);texts=" ".join(x.get("scriptSegment","") for x in storyboard).casefold();cta=next((x["scriptSegment"].casefold() for x in storyboard if x["purpose"]=="CTA"),"");subject=str(getattr(row,"title","") or "").split(":")[0].casefold();formal=any(x in texts for x in ("pode ser adequado","deve ser comparada","informações disponíveis","considere as limitações","faz sentido para o seu uso"));personal=any(x in texts for x in ("eu testei","eu comprei","uso todos os dias"));durations={x["recommendedDuration"] for x in storyboard};units=[u for x in storyboard for u in x.get("visualUnits",[])];catalog=bool(subject and len(subject.split())>1 and subject in texts)
    styles={x.get("voiceDirection",{}).get("voiceStyle") for x in storyboard};pauses=[x.get("voiceDirection",{}).get("pauseAfterMs",0) for x in storyboard];estimated=estimated_spoken_duration([x.get("scriptSegment","") for x in storyboard]);cta_energy=next((x.get("voiceDirection",{}).get("energy") for x in storyboard if x["purpose"]=="CTA"),None)
    return {"hookStrength":"PASS" if bool(row.hook or first.get("purpose")=="HOOK") else "FAIL","productVisibility":"PASS" if first.get("productFocus") else "FAIL","benefitClarity":"PASS" if any(x["purpose"]=="VALUE" for x in storyboard) else "WARNING","scenePacing":"WARNING" if long else "PASS","ctaClarity":"PASS" if has_cta else "FAIL","compliance":"PASS" if compliance_status=="PASS" and not personal else "FAIL","naturalSpeech":"WARNING" if formal else "PASS","catalogLanguage":"FAIL" if catalog else "PASS","ctaNaturalness":"PASS" if any(x in cta for x in ("dá uma olhada","confere","compara","vê ")) else "FAIL" if not cta else "WARNING","rhythmVariation":"PASS" if len(durations)>1 else "WARNING","visualVariation":"PASS" if len({u["visualIntent"] for u in units})>=3 and all(u["estimatedDuration"]<=3 for u in units) else "WARNING","voiceVariation":"PASS" if len(styles-{None})>1 else "WARNING","voiceMonotony":"PASS" if len(styles-{None})>1 else "WARNING","paceTarget":pace_target_status(estimated),"excessiveSilence":"WARNING" if any(x>220 for x in pauses) else "PASS","ctaEnergy":"PASS" if cta_energy in {"HIGH","MEDIUM_HIGH"} else "WARNING"}


def direction_for(db:Session,row:Creative)->dict:
    direction=choose_direction(db,row);hook,cta,planned=_copy(direction,row.required_warnings);scenes=db.scalars(select(CreativeScene).where(CreativeScene.creative_id==row.id).order_by(CreativeScene.order_index)).all()
    decision=db.scalar(select(DecisionLog).where(DecisionLog.entity_id==row.id,DecisionLog.action=="TIKTOK_FIRST_VARIANT_CREATED").order_by(DecisionLog.timestamp.desc()));stored=(decision.metadata_ or {}).get("storyboard") if decision else None
    storyboard=stored or ([{"sceneId":s.id,"orderIndex":s.order_index,"speechSegmentId":f"segment-{s.order_index+1:02}","purpose":s.purpose,"scriptSegment":s.narration_text or "","onScreenText":s.on_screen_text or "","visualIntent":s.visual_instruction or s.scene_type,"recommendedDuration":float(s.duration_seconds or 0),"productFocus":s.scene_type in {"PRODUCT","MIXED","WARNING","CTA"},"avatarVisible":s.speaker in {"BRUNO","CAROL"},"avatarSpeaker":s.speaker if s.speaker in {"BRUNO","CAROL"} else None,"visualEmphasis":"HIGH" if s.purpose in {"HOOK","CTA"} else "MEDIUM","visualUnits":[{"speechSegmentId":f"segment-{s.order_index+1:02}","visualUnitIndex":0,"visualIntent":s.visual_instruction or s.scene_type,"onScreenText":s.on_screen_text or "","estimatedDuration":float(s.duration_seconds or 0)}]} for s in scenes] or planned)
    storyboard=[{**item,"voiceDirection":item.get("voiceDirection") or direction_for_purpose(item.get("purpose")).metadata()} for item in storyboard]
    intents=[u["visualIntent"] for item in storyboard for u in item.get("visualUnits",[{"visualIntent":item["visualIntent"]}])];effective={**direction,"hookText":row.hook or hook,"ctaText":row.cta or cta,"storyboard":storyboard,"patternInterrupts":[current for previous,current in zip(intents,intents[1:]) if current!=previous]}
    from apps.api.app.services.creatives import compliance
    effective["qualityChecks"]=quality_checks(row,storyboard,compliance(db,row)["status"])
    effective["estimatedSpokenDurationSeconds"]=estimated_spoken_duration([x.get("scriptSegment","") for x in storyboard])
    return effective


def create_tiktok_variant(db:Session,source:Creative)->Creative:
    if source.status!="APPROVED":raise HTTPException(409,"A versão TikTok-first deve partir de um Creative aprovado")
    count=db.scalar(select(func.count()).select_from(Creative).where(Creative.parent_creative_id==source.id,Creative.generation_mode=="TIKTOK_FIRST")) or 0
    if count>=3:raise HTTPException(409,"Limite de três variações TikTok-first atingido")
    direction=choose_direction(db,source);hook,cta,storyboard=_copy(direction,source.required_warnings);group=source.variant_group or str(uuid4())
    copy=Creative(campaign_id=source.campaign_id,experiment_id=source.experiment_id,name=f"TikTok — {direction['subject']} — {count+1}",status="DRAFT",content_type="SHORT_VIDEO",target_channel="TIKTOK",angle_type_snapshot=direction["creativeAngle"],objective_snapshot=source.objective_snapshot,editorial_verdict_snapshot=source.editorial_verdict_snapshot,price_verdict_snapshot=source.price_verdict_snapshot,title=source.title,content_premise=f"Conteúdo curto sobre {direction['subject']} orientado a uso real, retenção e decisão informada.",hook=hook,body_script=" ".join(x["scriptSegment"] for x in storyboard),cta=cta,estimated_duration_seconds=round(sum(x["recommendedDuration"] for x in storyboard)),disclosure_text=source.disclosure_text,required_warnings=list(source.required_warnings or []),forbidden_claims=list(source.forbidden_claims or []),generation_mode="TIKTOK_FIRST",variant_group=group,parent_creative_id=source.id,variant_label=f"TikTok {count+1}")
    try:
        db.add(copy);db.flush()
        for item in storyboard:
            speaker=item["avatarSpeaker"] or "NARRATOR";scene_type="MIXED" if item["avatarVisible"] and item["productFocus"] else "PRODUCT" if item["productFocus"] else "TEXT"
            warning_codes=[str(x.get("code",x.get("message","WARNING"))) for x in (source.required_warnings or [])] if item["purpose"]=="PROOF_OR_REASON" else []
            db.add(CreativeScene(creative_id=copy.id,order_index=item["orderIndex"],scene_type=scene_type,speaker=speaker,purpose=item["purpose"],narration_text=item["scriptSegment"],on_screen_text=item["onScreenText"],visual_instruction=item["visualIntent"],avatar_state="NEUTRAL" if speaker in {"BRUNO","CAROL"} else None,duration_seconds=round(item["recommendedDuration"]),required_warning_codes=warning_codes))
        db.flush()
        from apps.api.app.services.creatives import compliance
        checks=quality_checks(copy,storyboard,compliance(db,copy)["status"]);log_decision(db,"SYSTEM","CREATIVE","TIKTOK_FIRST_VARIANT_CREATED",copy.id,reason=direction["angleReason"],metadata={"sourceCreativeId":source.id,"creativeAngle":direction["creativeAngle"],"angleReason":direction["angleReason"],"hookType":direction["hookType"],"hookText":hook,"persona":direction["persona"],"storyboardSceneCount":len(storyboard),"storyboard":storyboard,"patternInterrupts":[u["visualIntent"] for x in storyboard for u in x["visualUnits"]][1:],"ctaType":direction["ctaType"],"voiceDirections":[{"orderIndex":x["orderIndex"],**x["voiceDirection"]} for x in storyboard],"qualityChecks":checks});db.commit();db.refresh(copy);return copy
    except Exception:
        db.rollback();raise
