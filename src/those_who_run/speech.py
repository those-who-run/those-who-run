"""Text to speech via Piper, with a sentence cache.

A callout is spoken sentence by sentence with ``sentence_pause_secs`` of silence
between them: Piper's own gap after a full stop is too short to hear, so "Lap
two. one oh four point six. four point three over best." ran together. Each
sentence is cached on its own, so the fixed parts ("Lap two.", "Final lap.")
are synthesised once and only the numbers are new for each lap.

Text with nothing to say (no letters or digits, or audio Piper leaves empty)
gives no clip: ``synthesize`` returns None and leaves no file behind.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import re
import time
import wave
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Split on sentence ends. Callout text has no decimal points (numbers are words)."""
    return [part for part in (p.strip() for p in _SENTENCE_END.split(text)) if part]


def speakable(text: str) -> bool:
    """Whether ``text`` has anything to say: a letter or a digit."""
    return any(ch.isalnum() for ch in text)


class Speech(Protocol):
    def synthesize(self, text: str) -> Path | None:
        """Return a WAV file containing ``text``, or None when there is nothing to
        say. May be cached."""


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
        self._pause = max(float(cfg.get("sentence_pause_secs") or 0.0), 0.0)
        self._on_duration = on_duration
        log.info("loading piper voice %s", model_path)
        self._voice = PiperVoice.load(str(model_path))
        self._model_tag = hashlib.sha1(str(model_path).encode()).hexdigest()[:8]

    def synthesize(self, text: str) -> Path | None:
        if not speakable(text):
            return None
        out = self._path(f"{self._pause}|{text}")
        if out.exists():
            return out
        started = time.perf_counter()
        sentences = [s for s in split_sentences(text) if speakable(s)]
        parts = [p for p in (self._sentence(s) for s in sentences) if p is not None]
        if not parts:
            return None
        if len(parts) == 1:
            out = parts[0]
        else:
            join_wavs(parts, out, self._pause)
        elapsed = time.perf_counter() - started
        if self._on_duration is not None:
            self._on_duration(elapsed)
        log.debug("synthesised %r in %.3fs", text, elapsed)
        return out

    def _path(self, key: str) -> Path:
        digest = hashlib.sha1(f"{self._model_tag}|{self._syn}|{key}".encode()).hexdigest()
        return self.cache_dir / f"{digest}.wav"

    def _sentence(self, sentence: str) -> Path | None:
        out = self._path(sentence)
        if out.exists():
            return out
        tmp = out.with_suffix(".tmp.wav")
        try:
            wav = wave.open(str(tmp), "wb")  # noqa: SIM115 - closed below, see except
            try:
                self._voice.synthesize_wav(sentence, wav, syn_config=self._syn)
            except BaseException:
                # Closing a WAV with no params raises too; keep the voice's error.
                with contextlib.suppress(wave.Error):
                    wav.close()
                raise
            wav.close()
        except wave.Error as exc:
            # Piper wrote no audio, so the WAV header was never set.
            tmp.unlink(missing_ok=True)
            log.warning("no audio for %r: %s", sentence, exc)
            return None
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        tmp.replace(out)
        return out


def join_wavs(parts: list[Path], out: Path, pause_secs: float) -> None:
    """Concatenate WAV files that share a format, with silence between them."""
    tmp = out.with_suffix(".tmp.wav")
    with wave.open(str(tmp), "wb") as dst:
        for i, part in enumerate(parts):
            with wave.open(str(part), "rb") as src:
                if i == 0:
                    dst.setparams(src.getparams())
                    frame_bytes = src.getsampwidth() * src.getnchannels()
                    silence = b"\0" * (int(src.getframerate() * pause_secs) * frame_bytes)
                elif silence:
                    dst.writeframes(silence)
                dst.writeframes(src.readframes(src.getnframes()))
    tmp.replace(out)
