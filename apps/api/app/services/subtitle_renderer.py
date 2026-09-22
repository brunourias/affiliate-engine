import re
from pathlib import Path
from apps.api.app.core.config import settings

def timestamp(seconds,ass=False):
    if ass:
        cs=round(seconds*100);h,cs=divmod(cs,360000);m,cs=divmod(cs,6000);s,cs=divmod(cs,100);return f"{h}:{m:02}:{s:02}.{cs:02}"
    ms=round(seconds*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000);return f"{h:02}:{m:02}:{s:02},{ms:03}"
def blocks(text,max_chars=64):
    sentences=[x.strip() for x in re.split(r"(?<=[,;:.!?])\s+",text.strip()) if x.strip()];out=[]
    for sentence in sentences:
        words=sentence.split();current=[]
        for word in words:
            if current and len(" ".join(current+[word]))>max_chars:out.append(" ".join(current));current=[word]
            else:current.append(word)
        if current:out.append(" ".join(current))
    return out or ([text.strip()] if text.strip() else [])
def cue_weight(text):
    words=max(1,len(text.split()));pause=.75 if text.rstrip().endswith((".","!","?")) else (.35 if text.rstrip().endswith((",",";",":")) else 0);return words+pause
def cues(text,duration,lead_in=None,tail_padding=0):
    lead=settings.subtitle_lead_in_seconds if lead_in is None else lead_in;start=min(max(0,lead),duration);finish=max(start,duration-max(0,tail_padding));parts=blocks(text);weights=[cue_weight(x) for x in parts];total=sum(weights);cursor=start;available=finish-start;result=[]
    for i,(part,weight) in enumerate(zip(parts,weights)):
        end=finish if i==len(parts)-1 else cursor+available*weight/total;result.append((cursor,end,part));cursor=end
    return result
class SubtitleRenderer:
    def write(self,text,duration,directory:Path,stem:str,width:int,height:int):
        directory.mkdir(parents=True,exist_ok=True);items=cues(text,duration);srt=directory/f"{stem}.srt";ass=directory/f"{stem}.ass"
        srt.write_text("\n\n".join(f"{i}\n{timestamp(a)} --> {timestamp(b)}\n{t}" for i,(a,b,t) in enumerate(items,1)),encoding="utf-8")
        margin=int(height*settings.media_safe_margin_ratio);size=max(24,round(height*.035));header=f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, Bold, Alignment, MarginL, MarginR, MarginV, Outline, Shadow\nStyle: Normal,{settings.media_font_name},{size},&H00FFFFFF,&H00102020,-1,2,{margin},{margin},{margin},2,1\n\n[Events]\nFormat: Layer, Start, End, Style, Text\n"
        lines="\n".join(f"Dialogue: 0,{timestamp(a,True)},{timestamp(b,True)},Normal,{t.replace(chr(10),' ')}" for a,b,t in items);ass.write_text(header+lines+"\n",encoding="utf-8");return {"srt":srt,"ass":ass}
