from dataclasses import asdict,dataclass


VOICE_STYLES={"CURIOUS_ENERGETIC","CONVERSATIONAL","CONFIDENT","CAUTION","EXPLANATORY","CONFIDENT_INVITING"}
TARGET_SHORT_VIDEO_SECONDS=(17.0,20.0)
FINAL_TIMING_PACE_ADJUSTMENT=1.06


@dataclass(frozen=True)
class VoiceDirection:
    voice_style:str
    pace:str
    energy:str
    emphasis_words:tuple[str,...]
    pause_before_ms:int
    pause_after_ms:int
    speed:float
    exaggeration_delta:float
    cfg_weight_delta:float

    def metadata(self):
        data=asdict(self);data["voiceStyle"]=data.pop("voice_style");data["emphasisWords"]=list(data.pop("emphasis_words"));data["pauseBeforeMs"]=data.pop("pause_before_ms");data["pauseAfterMs"]=data.pop("pause_after_ms");data["cfgWeightDelta"]=data.pop("cfg_weight_delta");data["exaggerationDelta"]=data.pop("exaggeration_delta");return data


PROFILES={
    "HOOK":VoiceDirection("CURIOUS_ENERGETIC","FAST","HIGH",(),0,40,1.20,.12,-.03),
    "PROBLEM":VoiceDirection("CONVERSATIONAL","MEDIUM_FAST","MEDIUM",(),20,50,1.18,.02,0),
    "VALUE":VoiceDirection("CONFIDENT","MEDIUM_FAST","MEDIUM_HIGH",(),20,50,1.18,.06,.02),
    "PROOF_OR_REASON":VoiceDirection("EXPLANATORY","MEDIUM_FAST","MEDIUM",(),30,60,1.15,-.02,.02),
    "OBJECTION":VoiceDirection("CAUTION","MEDIUM","MEDIUM_LOW",(),30,90,1.10,-.06,.05),
    "WARNING":VoiceDirection("CAUTION","MEDIUM","MEDIUM_LOW",(),30,90,1.10,-.06,.05),
    "CTA":VoiceDirection("CONFIDENT_INVITING","MEDIUM_FAST","HIGH",(),20,50,1.20,.08,-.01),
}


def direction_for_purpose(purpose:str|None)->VoiceDirection:return PROFILES.get((purpose or "").upper(),VoiceDirection("CONVERSATIONAL","MEDIUM_FAST","MEDIUM",(),40,70,1.16,0,0))
def final_timing_speed(direction:VoiceDirection)->float:return round(direction.speed*FINAL_TIMING_PACE_ADJUSTMENT,3)
def provider_parameters(direction:VoiceDirection,base:dict)->dict:return {"exaggeration":round(min(.9,max(.25,float(base["exaggeration"])+direction.exaggeration_delta)),2),"cfgWeight":round(min(.8,max(.2,float(base["cfgWeight"])+direction.cfg_weight_delta)),2)}
def estimated_spoken_duration(texts:list[str],words_per_minute=240)->float:return round(sum(len((x or "").split()) for x in texts)*60/words_per_minute,2)
def pace_target_status(seconds:float)->str:return "PASS" if seconds<=20.5 else "WARNING" if seconds<=25 else "FAIL"
def compress_segment(text:str)->str:
    replacements={"montar um móvel":"montar móvel","fazer um reparo":"fazer reparos","A ideia é comparar com o que você realmente precisa em casa.":"O ponto é comparar com o que você precisa em casa.","Agora, pra serviço pesado ou uso todo dia, eu já compararia com modelos mais robustos.":"Pra uso pesado ou todo dia, eu compararia com modelos mais robustos.","Dá uma olhada nos detalhes e no preço atual antes de escolher.":"Veja os detalhes e o preço atual antes de escolher."}
    result=text
    for source,target in replacements.items():result=result.replace(source,target)
    return result
def compress_script(segments:list[str])->list[str]:return [compress_segment(x) for x in segments]
def timing_polish(text:str|None,purpose:str|None)->str|None:return compress_segment(text) if text and (purpose or "").upper() in {"OBJECTION","CTA"} else text
