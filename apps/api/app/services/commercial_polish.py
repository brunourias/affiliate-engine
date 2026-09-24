import re,unicodedata
from dataclasses import replace


HEADLINES={"HOOK":"PRECISA MESMO DE TANTO?","PROBLEM":"NÃO PRECISA EXAGERAR","VALUE":"O SUFICIENTE PARA O DIA A DIA","PROOF_OR_REASON":"PAGAR MAIS NÃO É SEMPRE MELHOR","OBJECTION":"USO PESADO MUDA A ESCOLHA","WARNING":"ATENÇÃO AO TIPO DE USO","CTA":"VEJA PREÇO E DETALHES"}


def tokens(text:str)->set[str]:
    plain=unicodedata.normalize("NFKD",text or "").encode("ascii","ignore").decode().casefold();values={x for x in re.findall(r"[a-z0-9]+",plain) if len(x)>2};return {"uso" if x in {"uso","usar"} else x for x in values}


def headline_redundancy(headline:str,subtitle:str)->float:
    left,right=tokens(headline),tokens(subtitle)
    matched=sum(any(a==b or (len(a)>=3 and len(b)>=3 and a[:3]==b[:3]) for b in right) for a in left);return round(matched/max(1,len(left)),3)


def polish_headline(purpose:str|None,headline:str|None,subtitle:str|None)->tuple[str,bool,str]:
    current=(headline or "").strip();score=headline_redundancy(current,subtitle or "");replacement=HEADLINES.get((purpose or "").upper(),current)
    adjusted=bool(current and score>=.6 and replacement and replacement!=current);final=replacement if adjusted else current;return final,adjusted,("WARNING" if headline_redundancy(final,subtitle or "")>=.6 else "PASS")


def shot_delta(previous,current)->int:
    return sum((previous.shot_type!=current.shot_type,previous.anchor!=current.anchor,abs(previous.scale_end-current.scale_start)>=.08,previous.background_style!=current.background_style,previous.text_layout!=current.text_layout))


def polish_shots(shots,purpose:str|None):
    if not shots:return [],0,"WARNING"
    result=[shots[0]];adjusted=0
    for index,current in enumerate(shots[1:],1):
        previous=result[-1]
        if shot_delta(previous,current)<2:
            anchors=("LEFT","RIGHT","CENTER");anchor=next(x for x in anchors if x!=previous.anchor);background="NEUTRAL_LIGHT" if previous.background_style!="NEUTRAL_LIGHT" else "BLURRED_PRODUCT";current=replace(current,anchor=anchor,background_style=background,scale_start=min(.96,max(.62,previous.scale_end+.09)),pattern_interrupt_type="PRODUCT_REPOSITION");adjusted+=1
        result.append(current)
    return result,adjusted,("PASS" if all(shot_delta(a,b)>=2 for a,b in zip(result,result[1:])) else "WARNING")


def dead_air_metrics(audios:list[dict|None])->dict:
    voiced=[x for x in audios if x];gaps=[]
    for previous,current in zip(voiced,voiced[1:]):gaps.append(int((previous.get("voiceMetadata",{}).get("pauseAfterMs",0) or 0)+(current.get("voiceMetadata",{}).get("pauseBeforeMs",0) or 0)))
    return {"maxGapMilliseconds":max(gaps,default=0),"gapsOver150Ms":sum(x>150 for x in gaps),"gapsOver250Ms":sum(x>250 for x in gaps),"gapsOver500Ms":sum(x>500 for x in gaps)}


def commercial_checks(shots,headline_status:str,dead_air:dict,purpose:str|None)->dict:
    holds=[x.end-x.start for x in shots];scales=[max(x.scale_start,x.scale_end) for x in shots]
    return {"COMMERCIAL_PACING":"PASS" if max(holds,default=0)<=2.5 else "WARNING","HEADLINE_SUBTITLE_REDUNDANCY":headline_status,"SHOT_VISUAL_DELTA":"PASS" if all(shot_delta(a,b)>=2 for a,b in zip(shots,shots[1:])) else "WARNING","CTA_CLARITY":"PASS" if (purpose or "").upper()!="CTA" or bool(shots) else "WARNING","DEAD_AIR":"PASS" if dead_air.get("gapsOver250Ms",0)==0 else "WARNING","PRODUCT_DOMINANCE":"PASS" if scales and max(scales)>=.75 else "WARNING"}
