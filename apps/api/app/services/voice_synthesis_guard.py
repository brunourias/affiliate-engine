from dataclasses import asdict,dataclass


@dataclass(frozen=True)
class SynthesisValidation:
    word_count:int;character_count:int;expected_duration:float;minimum_duration:float;maximum_duration:float;status:str;reason:str|None
    def metadata(self)->dict:
        data=asdict(self);return {"wordCount":data["word_count"],"characterCount":data["character_count"],"expectedDuration":data["expected_duration"],"minAcceptedDuration":data["minimum_duration"],"maxAcceptedDuration":data["maximum_duration"],"validationStatus":data["status"],"rejectionReason":data["reason"]}


class VoiceSynthesisGuard:
    """Conservative pt-BR plausibility guard; it rejects gross TTS anomalies, not natural variation."""
    def validate(self,text:str,trimmed_duration:float,leading_silence:float=0,trailing_silence:float=0)->SynthesisValidation:
        words=len((text or "").split());characters=len("".join((text or "").split()));expected=max(.6,words/3.2);minimum=max(.35,expected*.32);maximum=max(8.0,expected*2.0,expected+3.0);reason=None
        if trimmed_duration<=0 or trimmed_duration<minimum or trimmed_duration>maximum:reason="DURATION_OUTLIER"
        elif max(leading_silence,trailing_silence)>max(2.5,expected*.65):reason="EDGE_SILENCE_OUTLIER"
        return SynthesisValidation(words,characters,round(expected,3),round(minimum,3),round(maximum,3),"REJECTED" if reason else "VALID",reason)


def conservative_parameters(original:dict)->dict:
    return {"exaggeration":round(min(float(original["exaggeration"]),.58),2),"cfgWeight":round(min(.55,max(.4,float(original["cfgWeight"]))),2)}
