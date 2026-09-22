import re
import subprocess
import logging
from pathlib import Path

from apps.api.app.core.config import settings
from apps.api.app.services.ffmpeg_adapter import MediaProcessError
from apps.api.app.services.media_storage import MediaStorage

CHATTERBOX_RUNNER = Path(__file__).resolve().parents[2] / "scripts" / "chatterbox_tts.py"
VOICE_PROFILES = ("BRUNO", "CAROL", "NARRATOR")
CHATTERBOX_IMPORT_PROBE = "from chatterbox.mtl_tts import ChatterboxMultilingualTTS; print('IMPORT_OK')"
logger = logging.getLogger(__name__)


class TTSNormalizer:
    """Deterministic substitutions applied only to the text sent to TTS."""

    def __init__(self, overrides=None):
        self.overrides = dict(overrides if overrides is not None else settings.tts_pronunciation_overrides)

    def normalize(self, text):
        result = text or ""
        for source, replacement in sorted(self.overrides.items(), key=lambda item: len(item[0]), reverse=True):
            if source:
                result = re.sub(rf"(?<!\w){re.escape(source)}(?!\w)", replacement, result, flags=re.IGNORECASE)
        result=result.rstrip()
        return result if not result or result.endswith((".","!","?")) else result+"."


def chatterbox_profile(speaker):
    key = speaker.lower()
    return {
        "exaggeration": getattr(settings, f"chatterbox_exaggeration_{key}"),
        "cfgWeight": getattr(settings, f"chatterbox_cfg_weight_{key}"),
        "reference": getattr(settings, f"chatterbox_reference_{key}"),
    }


def resolve_local_reference(configured):
    if not configured:
        return None
    storage = MediaStorage()
    candidate = Path(configured)
    resolved = candidate.resolve() if candidate.is_absolute() else storage.resolve(configured).resolve()
    try:
        resolved.relative_to(storage.root.resolve())
    except ValueError as exc:
        raise ValueError("Reference audio fora do storage local permitido.") from exc
    if not resolved.is_file():
        raise ValueError("Reference audio não encontrado.")
    return resolved


def chatterbox_probe(python_path):
    """Checks the isolated runtime and import only; never loads model weights."""
    if not python_path or not Path(python_path).is_file():
        return "NOT_CONFIGURED", "CHATTERBOX_PYTHON_NOT_CONFIGURED"
    if not CHATTERBOX_RUNNER.is_file():
        return "ERROR", "CHATTERBOX_RUNNER_NOT_FOUND"
    try:
        result = subprocess.run(
            [python_path, "-c", CHATTERBOX_IMPORT_PROBE],
            shell=False,
            capture_output=True,
            text=True,
            timeout=settings.chatterbox_diagnostic_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        error=MediaProcessError("Diagnóstico do Chatterbox excedeu o tempo limite.",getattr(exc,"stderr",None));logger.warning("Chatterbox import probe timed out: %s",error.sanitized_stderr or "no stderr")
        return "ERROR", "CHATTERBOX_IMPORT_FAILED"
    except OSError as exc:
        logger.warning("Chatterbox import probe could not start: %s",type(exc).__name__)
        return "ERROR", "CHATTERBOX_IMPORT_FAILED"
    if result.returncode==0 and "IMPORT_OK" in (result.stdout or "").splitlines():
        return "AVAILABLE", None
    error=MediaProcessError("Import do Chatterbox falhou.",result.stderr);logger.warning("Chatterbox import probe failed: %s",error.sanitized_stderr or "unexpected stdout")
    return "ERROR", "CHATTERBOX_IMPORT_FAILED"
