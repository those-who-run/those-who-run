"""Text to speech via Piper, with a phrase cache."""

from __future__ import annotations

import hashlib
import logging
import time
import wave
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)


class Speech(Protocol):
    def synthesize(self, text: str) -> Path:
        """Return a WAV file containing ``text``. May be cached."""


class PiperSpeech:
    """Piper TTS. Loads the ONNX voice once; synthesis is CPU-bound and synchronous."""

    def __init__(
        self,
        model_path: Path,
        cache_dir: Path,
        voice_cfg: dict[str, Any] | None = None,
        on_duration: Any | None = None,
    ) -> None:
        from piper import PiperVoice
        from piper.config import SynthesisConfig

        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cfg = voice_cfg or {}
        self._syn = SynthesisConfig(
            length_scale=cfg.get("length_scale"),
            noise_scale=cfg.get("noise_scale"),
            noise_w_scale=cfg.get("noise_w_scale"),
        )
        self._on_duration = on_duration
        log.info("loading piper voice %s", model_path)
        self._voice = PiperVoice.load(str(model_path))
        self._model_tag = hashlib.sha1(str(model_path).encode()).hexdigest()[:8]

    def synthesize(self, text: str) -> Path:
        key = hashlib.sha1(f"{self._model_tag}|{self._syn}|{text}".encode()).hexdigest()
        out = self.cache_dir / f"{key}.wav"
        if out.exists():
            return out
        started = time.perf_counter()
        tmp = out.with_suffix(".tmp.wav")
        with wave.open(str(tmp), "wb") as wav:
            self._voice.synthesize_wav(text, wav, syn_config=self._syn)
        tmp.replace(out)
        elapsed = time.perf_counter() - started
        if self._on_duration is not None:
            self._on_duration(elapsed)
        log.debug("synthesised %r in %.3fs", text, elapsed)
        return out
