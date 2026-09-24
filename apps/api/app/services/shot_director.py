from dataclasses import asdict,dataclass
from math import ceil


@dataclass(frozen=True)
class Shot:
    shot_type:str;start:float;end:float;crop_mode:str;scale_start:float;scale_end:float;anchor:str;background_style:str;text_layout:str;transition_style:str;persona_visible:bool;pattern_interrupt_type:str
    def metadata(self,index:int)->dict:
        data=asdict(self);return {"shotIndex":index,"shotType":data.pop("shot_type"),"start":round(self.start,3),"end":round(self.end,3),"crop":data.pop("crop_mode"),"scaleStart":self.scale_start,"scaleEnd":self.scale_end,"anchor":self.anchor,"backgroundStyle":data.pop("background_style"),"headlineLayout":data.pop("text_layout"),"transitionStyle":data.pop("transition_style"),"personaVisible":data.pop("persona_visible"),"patternInterruptType":data.pop("pattern_interrupt_type")}


SEQUENCES={
    "HOOK":[("CLOSEUP","CENTER","BLURRED_PRODUCT","CENTER_PUNCH","ZOOM_PUNCH",.84,.96,False),("HERO","CENTER","SOFT_GRADIENT","TOP_BANNER","CROP_CHANGE",.68,.76,True)],
    "WARNING":[("OFFSET_LEFT","LEFT","COLOR_WASH","RIGHT_BLOCK","WARNING_CARD",.70,.79,True),("CLOSEUP","CENTER","BLURRED_PRODUCT","TOP_BANNER","BACKGROUND_CHANGE",.78,.88,False)],
    "CTA":[("FULL_BLEED","CENTER","BLURRED_PRODUCT","CENTER_PUNCH","ZOOM_PUNCH",.82,.94,False),("OFFSET_RIGHT","RIGHT","COLOR_WASH","LEFT_BLOCK","PRODUCT_REPOSITION",.72,.80,False)],
    "DEFAULT":[("HERO","CENTER","BLURRED_PRODUCT","TOP_BANNER","BACKGROUND_CHANGE",.66,.74,True),("CLOSEUP","CENTER","NEUTRAL_LIGHT","LEFT_BLOCK","CROP_CHANGE",.76,.86,False),("OFFSET_LEFT","LEFT","COLOR_WASH","RIGHT_BLOCK","PRODUCT_REPOSITION",.70,.78,True)],
}


class ShotDirector:
    def plan(self,purpose:str|None,visual_intent:str|None,duration:float,has_product:bool,persona_visible:bool,headline:str|None,asset_dimensions:tuple[int|None,int|None]=(None,None))->list[Shot]:
        if duration<=0:return []
        source=SEQUENCES.get((purpose or "").upper(),SEQUENCES["DEFAULT"]);count=1 if duration<2.4 else min(len(source),max(2,ceil(duration/2.2)));step=duration/count;shots=[];cursor=0.0
        for index,(kind,anchor,background,text_layout,interrupt,start_scale,end_scale,show_persona) in enumerate(source[:count]):
            end=duration if index==count-1 else (max(.8,duration-1.8) if (purpose or "").upper()=="CTA" and count==2 else cursor+step)
            shots.append(Shot(kind,cursor,end,"SAFE_COVER" if kind in {"CLOSEUP","DETAIL","FULL_BLEED"} else "SAFE_CONTAIN",start_scale if has_product else 0,end_scale if has_product else 0,anchor,background,text_layout,"CUT" if index else "FADE",bool(persona_visible and show_persona),"NONE" if index==0 else interrupt));cursor=end
        return shots


def visual_checks(shots:list[Shot],duration:float,purpose:str|None)->dict:
    largest_gap=max((x.end-x.start for x in shots),default=duration);scales=[max(x.scale_start,x.scale_end) for x in shots]
    return {"PRODUCT_PROMINENCE":"PASS" if scales and max(scales)>=.60 else "WARNING","VISUAL_STAGNATION":"PASS" if largest_gap<=2.5 else "WARNING","BACKGROUND_MONOTONY":"PASS" if len({x.background_style for x in shots})>1 or len(shots)==1 else "WARNING","SHOT_VARIATION":"PASS" if duration<2.4 or len({x.shot_type for x in shots})>1 else "WARNING","CTA_VISUAL_STRENGTH":"PASS" if (purpose or "").upper()!="CTA" or (scales and max(scales)>=.75) else "WARNING"}
