"""Text to speech via Piper, with a sentence cache.

A callout is spoken sentence by sentence with ``sentence_pause_secs`` of silence
between them: Piper's own gap after a full stop is too short to hear, so "Lap
two. one oh four point six. four point three over best." ran together. Each
sentence is cached on its own, so the fixed parts ("Lap two.", "Final lap.")
are synthesised once and only the numbers are new for each lap.

Text with nothing to say (no letters or digits, or audio Piper leaves empty)
gives no clip: ``synthesize`` returns None and leaves no file behind.

The cache (``ClipCache``) is capped in bytes and evicts the least recently used
sentence. A callout of several sentences is joined into a one-off WAV that the
player hands back with ``release`` once it has played; it is never cached, as
almost every lap's text is new. The cache key covers the voice file's path,
size and modification time, so a voice replaced in place is not served from
old clips, and every write goes to a temp file of its own before an atomic
rename, so two threads synthesising the same text cannot corrupt a clip.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import re
import threading
import time
import uuid
import wave
from collections import OrderedDict
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_CLIP_NAME = re.compile(r"^[0-9a-f]{40}\.wav$")
JOINED_PREFIX = "joined-"
DEFAULT_CACHE_MAX_BYTES = 100 * 1024 * 1024
# A joined or temp file older than this was left by a crash. Younger ones may
# belong to another process sharing the directory (``say`` beside a running
# engineer), so start-up leaves them alone.
STALE_SECS = 600.0


def split_sentences(text: str) -> list[str]:
    """Split on sentence ends. Callout text has no decimal points (numbers are words)."""
    return [part for part in (p.strip() for p in _SENTENCE_END.split(text)) if part]


def speakable(text: str) -> bool:
    """Whether ``text`` has anything to say: a letter or a digit."""
    return any(ch.isalnum() for ch in text)


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()


def voice_tag(model_path: Path) -> str:
    """Identifies the voice file as it is now: its path, size and modification time,
    and those of its ``.json`` config beside it, so replacing either one (even at
    the same path) gives new cache keys."""
    parts = []
    for path in (Path(model_path), Path(f"{model_path}.json")):
        try:
            st = path.stat()
        except FileNotFoundError:
            parts.append(f"{path}|missing")
            continue
        parts.append(f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}")
    return _sha1("|".join(parts))[:12]


def _unique_tmp(out: Path) -> Path:
    return out.with_name(f"{out.stem}.{uuid.uuid4().hex}.tmp.wav")


class Speech(Protocol):
    def synthesize(self, text: str) -> Path | None:
        """Return a WAV file containing ``text``, or None when there is nothing to
        say. May be cached."""

    def release(self, clip: Path | None) -> None:
        """``clip`` has been played: a one-off clip is removed, a cached one kept,
        and None (nothing was said) is ignored."""


class ClipCache:
    """A directory of sentence clips, capped at ``max_bytes`` with least recently
    used eviction. The index lives in memory, seeded from the files' modification
    times at start-up (a hit touches the file, so the order survives a restart).
    Safe to share between threads."""

    def __init__(self, cache_dir: Path, max_bytes: int = DEFAULT_CACHE_MAX_BYTES) -> None:
        self.dir = Path(cache_dir)
        self.max_bytes = max(int(max_bytes), 0)
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        _check_owner(self.dir)
        self._lock = threading.Lock()
        self._sizes: OrderedDict[Path, int] = OrderedDict()
        self.total_bytes = 0
        found = []
        stale_before = time.time() - STALE_SECS
        for path in self.dir.iterdir():
            try:
                st = path.stat()
            except FileNotFoundError:
                continue
            if path.name.startswith(JOINED_PREFIX) or path.name.endswith(".tmp.wav"):
                if st.st_mtime < stale_before:
                    path.unlink(missing_ok=True)  # left by a crash: never read again
            elif _CLIP_NAME.match(path.name) and path.is_file():
                found.append((st.st_mtime_ns, path, st.st_size))
        for _, path, size in sorted(found):
            self._sizes[path] = size
            self.total_bytes += size
        self.trim()

    def path(self, key: str) -> Path:
        return self.dir / f"{_sha1(key)}.wav"

    def get(self, key: str) -> Path | None:
        """The cached clip for ``key``, marked as just used, or None."""
        out = self.path(key)
        with self._lock:
            if not out.exists():
                self._forget(out)
                return None
            if out in self._sizes:
                self._sizes.move_to_end(out)
            else:  # written by another process sharing the directory
                self._add(out)
        try:
            os.utime(out)
        except FileNotFoundError:
            return None
        return out

    def put(self, tmp: Path, key: str) -> Path:
        """Move a finished temp file into the cache as ``key``'s clip."""
        out = self.path(key)
        with self._lock:
            os.replace(tmp, out)
            self._forget(out)
            self._add(out)
        return out

    def trim(self) -> None:
        """Evict least recently used clips until the cache is under its cap. The most
        recent clip is always kept, so the one just returned is still there."""
        with self._lock:
            while self.total_bytes > self.max_bytes and len(self._sizes) > 1:
                path, size = self._sizes.popitem(last=False)
                self.total_bytes -= size
                path.unlink(missing_ok=True)

    def one_off(self) -> Path:
        """A fresh path for a clip that is played once and then released."""
        return self.dir / f"{JOINED_PREFIX}{uuid.uuid4().hex}.wav"

    def release(self, clip: Path | None) -> None:
        if clip is not None and clip.parent == self.dir and clip.name.startswith(JOINED_PREFIX):
            clip.unlink(missing_ok=True)

    def _add(self, path: Path) -> None:
        size = path.stat().st_size
        self._sizes[path] = size
        self.total_bytes += size

    def _forget(self, path: Path) -> None:
        size = self._sizes.pop(path, None)
        if size is not None:
            self.total_bytes -= size


def _check_owner(path: Path) -> None:
    """Refuse a cache directory someone else owns: they could plant clips in it."""
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:
        return
    owner = path.stat().st_uid
    if owner != geteuid():
        raise PermissionError(
            f"speech cache {path} is owned by uid {owner}, not this user; set GT7_CACHE_DIR"
        )


class PiperSpeech:
    """Piper TTS. Loads the ONNX voice once; synthesis is CPU-bound and synchronous."""

    def __init__(
        self,
        model_path: Path,
        cache_dir: Path,
        voice_cfg: dict[str, Any] | None = None,
        on_duration: Any | None = None,
        max_cache_bytes: int = DEFAULT_CACHE_MAX_BYTES,
    ) -> None:
        from piper import PiperVoice
        from piper.config import SynthesisConfig

        self.cache = ClipCache(cache_dir, max_cache_bytes)
        cfg = voice_cfg or {}
        self._syn = SynthesisConfig(
            length_scale=cfg.get("length_scale"),
            noise_scale=cfg.get("noise_scale"),
            noise_w_scale=cfg.get("noise_w_scale"),
        )
        self._pause = max(float(cfg.get("sentence_pause_secs") or 0.0), 0.0)
        self._on_duration = on_duration
        log.info("loading piper voice %s", model_path)
        self._model_tag = voice_tag(model_path)
        self._voice = PiperVoice.load(str(model_path))

    def synthesize(self, text: str) -> Path | None:
        if not speakable(text):
            return None
        started = time.perf_counter()
        synthesised = False
        parts = []
        for sentence in (s for s in split_sentences(text) if speakable(s)):
            clip, fresh = self._sentence(sentence)
            synthesised = synthesised or fresh
            if clip is not None:
                parts.append(clip)
        if not parts:
            out = None
        elif len(parts) == 1:
            out = parts[0]
        else:
            out = self.cache.one_off()
            join_wavs(parts, out, self._pause)
        self.cache.trim()
        elapsed = time.perf_counter() - started
        if synthesised:
            if self._on_duration is not None:
                self._on_duration(elapsed)
            log.debug("synthesised %r in %.3fs", text, elapsed)
        return out

    def release(self, clip: Path | None) -> None:
        self.cache.release(clip)

    def _key(self, sentence: str) -> str:
        return f"{self._model_tag}|{self._syn}|{sentence}"

    def _sentence(self, sentence: str) -> tuple[Path | None, bool]:
        """The clip for one sentence (None when Piper gives no audio for it), and
        whether Piper was asked to synthesise it."""
        key = self._key(sentence)
        cached = self.cache.get(key)
        if cached is not None:
            return cached, False
        tmp = _unique_tmp(self.cache.path(key))
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
            return None, True
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return self.cache.put(tmp, key), True


def join_wavs(parts: list[Path], out: Path, pause_secs: float) -> None:
    """Concatenate WAV files that share a format, with silence between them."""
    tmp = _unique_tmp(out)
    try:
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
    finally:
        tmp.unlink(missing_ok=True)
