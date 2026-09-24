import json,re,subprocess
from pathlib import Path
from apps.api.app.core.config import settings

def escape_filtergraph_path(path):
    """Encode a filename used inside an FFmpeg filter expression."""
    value=str(path).replace("\\","/")
    value=value.replace(":","\\:")
    # Quotes protect separators such as comma, semicolon and brackets. A
    # literal quote must briefly end the quoted section and be escaped.
    return "'"+value.replace("'","'\\''")+"'"

def _sanitized_stderr(value):
    if not value:return None
    text=str(value).replace("\x00","").strip()
    text=re.sub(r"(?i)(token|secret|password|api[_-]?key)(\s*[=:]\s*)\S+",r"\1\2<redacted>",text)
    return text[-4000:]

class MediaProcessError(RuntimeError):
    def __init__(self,message,stderr=None):super().__init__(message);self.sanitized_stderr=_sanitized_stderr(stderr)
class FFmpegAdapter:
    def __init__(self,ffmpeg=None,ffprobe=None,timeout=None):self.ffmpeg=ffmpeg or settings.ffmpeg_path;self.ffprobe=ffprobe or settings.ffprobe_path;self.timeout=timeout or settings.media_subprocess_timeout_seconds
    def run(self,args,input_text=None,timeout=None):
        try:return subprocess.run(args,shell=False,input=input_text,text=True,capture_output=True,timeout=timeout or self.timeout,check=True)
        except subprocess.TimeoutExpired as exc:raise MediaProcessError("Processo local excedeu o tempo limite.",getattr(exc,"stderr",None)) from exc
        except (subprocess.CalledProcessError,OSError) as exc:raise MediaProcessError("Ferramenta local de mídia falhou.",getattr(exc,"stderr",None)) from exc
    def version(self,tool):
        result=self.run([tool,"-version"],timeout=5);return result.stdout.splitlines()[0] if result.stdout else None
    def probe(self,path):
        result=self.run([self.ffprobe,"-v","error","-show_streams","-show_format","-of","json",str(path)]);return json.loads(result.stdout)
    def audio_duration(self,path):
        data=self.probe(path);return float(data.get("format",{}).get("duration") or 0)
    def trim_audio_edges(self,source,target,threshold_db,duration,padding):
        # Reverse-pass trimming targets file boundaries only and preserves pauses inside speech.
        edge=f"start_periods=1:start_duration={duration}:start_threshold={threshold_db}dB:start_silence={padding}"
        return self.run([self.ffmpeg,"-y","-i",str(source),"-af",f"silenceremove={edge},areverse,silenceremove={edge},areverse",str(target)])
    def silence_edges(self,source,threshold_db,duration,audio_duration):
        result=self.run([self.ffmpeg,"-i",str(source),"-af",f"silencedetect=noise={threshold_db}dB:d={duration}","-f","null","-"])
        text=result.stderr or "";starts=[float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)",text)];ends=[float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)",text)]
        leading=ends[0] if starts and ends and starts[0]<=.02 else 0.0
        trailing=max(0.0,audio_duration-starts[-1]) if starts and starts[-1]<audio_duration and (len(ends)<len(starts) or ends[-1]>=audio_duration-.05) else 0.0
        return {"leadingSilenceSeconds":round(leading,3),"trailingSilenceSeconds":round(trailing,3)}
    def direct_voice(self,source,target,speed,pause_before_ms,pause_after_ms):
        filters=[f"atempo={speed:.3f}"]
        if pause_before_ms:filters.append(f"adelay={pause_before_ms}:all=1")
        if pause_after_ms:filters.append(f"apad=pad_dur={pause_after_ms/1000:.3f}")
        return self.run([self.ffmpeg,"-y","-i",str(source),"-af",",".join(filters),str(target)])
    def render_scene(self,args):return self.run([self.ffmpeg,"-y",*args])
    def compose(self,args):return self.run([self.ffmpeg,"-y",*args])
