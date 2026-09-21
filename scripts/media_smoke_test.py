"""Diagnóstico manual opcional da mídia local; não instala nem baixa componentes."""
import json, subprocess, sys, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from apps.api.app.core.config import settings
from apps.api.app.services.media import diagnostics

def main():
    report=diagnostics();print(json.dumps(report,ensure_ascii=False,indent=2))
    if report["ffprobe"]["status"]!="AVAILABLE" or report["tts"]["status"]!="AVAILABLE":
        print("Smoke de voz não executado: configure FFprobe e ao menos o perfil NARRATOR.");return 2
    profile=report["tts"]["profiles"]["NARRATOR"]
    if profile["status"]!="AVAILABLE":print("Smoke não executado: perfil NARRATOR indisponível.");return 2
    mode=settings.tts_invocation_mode.upper();command=([settings.tts_python_path or sys.executable,"-m",settings.tts_python_module] if mode=="MODULE" else [settings.tts_executable_path]);model=settings.tts_model_narrator;config=settings.tts_model_config_narrator or str(Path(model).with_suffix(Path(model).suffix+".json"))
    with tempfile.TemporaryDirectory(prefix="affiliate-media-smoke-") as folder:
        wav=Path(folder)/"voice.wav"
        subprocess.run([*command,"--model",model,"--config",config,"--output_file",str(wav)],shell=False,input="Teste local de voz do Affiliate Engine.",text=True,capture_output=True,timeout=30,check=True)
        if not wav.is_file() or wav.stat().st_size==0:raise RuntimeError("Piper não gerou WAV válido")
        probe=subprocess.run([settings.ffprobe_path,"-v","error","-show_format","-of","json",str(wav)],shell=False,capture_output=True,text=True,timeout=10,check=True);print("WAV temporário válido:",json.loads(probe.stdout).get("format",{}).get("duration","duração indisponível"))
    return 0
if __name__=="__main__":raise SystemExit(main())
