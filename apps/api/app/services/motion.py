from dataclasses import dataclass

from apps.api.app.core.config import settings


MOTION_PRESETS={"STATIC","SLOW_ZOOM_IN","SLOW_ZOOM_OUT","PAN_LEFT","PAN_RIGHT","FLOAT_UP","FLOAT_DOWN"}


@dataclass(frozen=True)
class MotionPlan:
    motion_preset:str
    product_motion:str
    avatar_motion:str
    enter_duration_ms:int
    exit_duration_ms:int
    zoom_percent:float
    avatar_float_pixels:int

    def metadata(self)->dict:
        return {
            "motionPreset":self.motion_preset,
            "productMotion":self.product_motion,
            "avatarMotion":self.avatar_motion,
            "enterDurationMs":self.enter_duration_ms,
            "exitDurationMs":self.exit_duration_ms,
        }


def select_motion(layout:str,order_index:int,has_product:bool,has_avatar:bool,width:int,height:int,purpose:str|None=None)->MotionPlan:
    product="STATIC";avatar="STATIC"
    if has_product:
        if layout in {"PRODUCT","MIXED","CTA"}:product="SLOW_ZOOM_IN" if order_index%2==0 else "SLOW_ZOOM_OUT"
        elif layout=="WARNING":product="SLOW_ZOOM_OUT"
        elif layout=="BRAND_FALLBACK":product="SLOW_ZOOM_IN"
    if has_avatar:avatar="STATIC"
    primary=product if product!="STATIC" else avatar
    proportional_float=max(1,round(settings.media_motion_avatar_float_pixels*height/1920))
    level=.14 if (purpose or "").upper()=="HOOK" else .10 if (purpose or "").upper() in {"WARNING","CTA"} else .08
    return MotionPlan(primary,product,avatar,settings.media_motion_enter_duration_ms,settings.media_motion_exit_duration_ms,level if has_product else settings.media_motion_zoom_percent,proportional_float)


def product_scale_filter(label:str,output_label:str,box_width:int,box_height:int,duration:float,plan:MotionPlan)->str:
    maximum=1+plan.zoom_percent
    base_width=max(2,round(box_width/maximum));base_height=max(2,round(box_height/maximum))
    if plan.product_motion=="SLOW_ZOOM_IN":factor=f"1+{plan.zoom_percent:.4f}*t/{duration:.6f}"
    elif plan.product_motion=="SLOW_ZOOM_OUT":factor=f"{maximum:.4f}-{plan.zoom_percent:.4f}*t/{duration:.6f}"
    else:factor="1"
    enter=plan.enter_duration_ms/1000
    return f"[{label}]format=rgba,scale={base_width}:{base_height}:force_original_aspect_ratio=decrease,scale=w='trunc(iw*({factor})/2)*2':h='trunc(ih*({factor})/2)*2':eval=frame,fade=t=in:st=0:d={enter:.3f}:alpha=1[{output_label}]"


def avatar_filter(label:str,output_label:str,box_width:int,box_height:int,plan:MotionPlan)->str:
    enter=plan.enter_duration_ms/1000
    return f"[{label}]format=rgba,scale={box_width}:{box_height}:force_original_aspect_ratio=decrease,fade=t=in:st=0:d={enter:.3f}:alpha=1[{output_label}]"


def overlay_position(role:str,box,duration:float,plan:MotionPlan)->tuple[str,str]:
    x=f"{box.x}+({box.width}-w)/2";base=f"{box.y}+({box.height}-h)/2"
    if role=="avatar" and plan.avatar_motion in {"FLOAT_UP","FLOAT_DOWN"}:
        direction="+" if plan.avatar_motion=="FLOAT_UP" else "-"
        y=f"{base}{direction}{plan.avatar_float_pixels}*(1-t/{duration:.6f})"
    else:y=base
    return x,y
