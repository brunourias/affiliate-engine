"""Isolated Chatterbox CLI. Diagnostics never instantiate or download a model."""
import argparse
import json
import sys
import time
from pathlib import Path


def parser():
    result = argparse.ArgumentParser()
    result.add_argument("--diagnose", action="store_true")
    result.add_argument("--batch", action="store_true")
    result.add_argument("--output")
    result.add_argument("--language", default="pt")
    result.add_argument("--exaggeration", type=float, default=0.6)
    result.add_argument("--cfg-weight", type=float, default=0.4)
    result.add_argument("--reference")
    return result


def main():
    args = parser().parse_args()
    started = time.perf_counter()
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    import_duration = time.perf_counter() - started
    if args.diagnose:
        print("Chatterbox module available")
        return 0
    if args.batch:
        payload=json.loads(sys.stdin.read());device="cuda" if __import__("torch").cuda.is_available() else "cpu";load_started=time.perf_counter();model=ChatterboxMultilingualTTS.from_pretrained(device=device);model_load=time.perf_counter()-load_started;synthesis=0.0;scene_metrics=[]
        import torchaudio
        for item in payload["items"]:
            generate_started=time.perf_counter();kwargs={"language_id":item["language"],"exaggeration":item["exaggeration"],"cfg_weight":item["cfgWeight"]}
            if item.get("reference"):kwargs["audio_prompt_path"]=item["reference"]
            wav=model.generate(item["text"],**kwargs);elapsed=time.perf_counter()-generate_started;synthesis+=elapsed;output=Path(item["output"]);output.parent.mkdir(parents=True,exist_ok=True);torchaudio.save(str(output),wav,model.sr);scene_metrics.append({"sceneIndex":item["sceneIndex"],"synthesisDuration":round(elapsed,3)})
        print("AFFILIATE_RESULT="+json.dumps({"importDuration":round(import_duration,3),"modelLoadDuration":round(model_load,3),"synthesisDuration":round(synthesis,3),"totalDuration":round(time.perf_counter()-started,3),"scenes":scene_metrics},separators=(",",":")));return 0
    if not args.output:
        parser().error("--output is required")
    import torch
    import torchaudio
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = ChatterboxMultilingualTTS.from_pretrained(device=device)
    kwargs = {
        "language_id": args.language,
        "exaggeration": args.exaggeration,
        "cfg_weight": args.cfg_weight,
    }
    if args.reference:
        kwargs["audio_prompt_path"] = args.reference
    wav = model.generate(sys.stdin.read(), **kwargs)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(output), wav, model.sr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
