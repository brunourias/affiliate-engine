from dataclasses import dataclass

AVATAR_STATES={
    "BRUNO":{"NEUTRAL","EXPLAINING","APPROVING","WARNING","QUESTIONING","POINTING","COMPARING"},
    "CAROL":{"NEUTRAL","CURIOUS","APPROVING","WARNING","QUESTIONING","AGREEING","THINKING"},
}

@dataclass(frozen=True)
class Box:
    x:int;y:int;width:int;height:int

@dataclass(frozen=True)
class SafeAreas:
    canvas_width:int;canvas_height:int;top:int;bottom:int;side:int;subtitle_top:int

def safe_areas(width:int,height:int)->SafeAreas:
    return SafeAreas(width,height,round(height*.08),round(height*.18),round(width*.08),round(height*.72))

def fit_asset(source_width:int,source_height:int,box:Box)->Box:
    if min(source_width,source_height,box.width,box.height)<=0:raise ValueError("Dimensões devem ser positivas")
    scale=min(box.width/source_width,box.height/source_height)
    width=max(1,round(source_width*scale));height=max(1,round(source_height*scale))
    return Box(box.x+(box.width-width)//2,box.y+(box.height-height)//2,width,height)

def layout_boxes(width:int,height:int,layout:str)->dict[str,Box]:
    safe=safe_areas(width,height);usable_bottom=safe.subtitle_top-round(height*.03);usable_height=usable_bottom-safe.top
    if layout=="MIXED":
        product=Box(safe.side,safe.top,round(width*.58),usable_height)
        avatar=Box(round(width*.66),safe.top+round(height*.12),width-safe.side-round(width*.66),round(usable_height*.72))
    elif layout in {"WARNING","CTA"}:
        product=Box(safe.side,safe.top,round(width*.52),usable_height)
        avatar=Box(round(width*.60),safe.top+round(height*.10),width-safe.side-round(width*.60),round(usable_height*.78))
    else:
        product=avatar=Box(safe.side,safe.top,width-2*safe.side,usable_height)
    return {"product":product,"avatar":avatar}

def normalize_avatar_state(speaker:str|None,state:str|None)->str|None:
    speaker=(speaker or "").upper()
    if speaker not in AVATAR_STATES:return None
    requested=(state or "NEUTRAL").upper()
    return requested if requested in AVATAR_STATES[speaker] else "NEUTRAL"
