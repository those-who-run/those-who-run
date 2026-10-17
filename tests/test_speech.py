import os
import threading
import time
import wave

import pytest

from those_who_run.speech import (
    DEFAULT_CACHE_MAX_BYTES,
    STALE_SECS,
    ClipCache,
    PiperSpeech,
    join_wavs,
    split_sentences,
    voice_tag,
)

RATE = 1000


def _wav(path, frames):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"\x01\x00" * frames)
    return path


def _frames(path):
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes())


def test_split_sentences():
    assert split_sentences("Lap two. one oh four point six. four point three over best.") == [
        "Lap two.",
        "one oh four point six.",
        "four point three over best.",
    ]
    assert split_sentences("Final lap.") == ["Final lap."]
    assert split_sentences("Box now! Really?  Yes") == ["Box now!", "Really?", "Yes"]


def test_join_wavs_puts_silence_between_sentences(tmp_path):
    a, b = _wav(tmp_path / "a.wav", 10), _wav(tmp_path / "b.wav", 20)
    join_wavs([a, b], tmp_path / "out.wav", 0.35)
    data = _frames(tmp_path / "out.wav")
    assert data == b"\x01\x00" * 10 + b"\x00\x00" * 350 + b"\x01\x00" * 20


class FakeVoice:
    def __init__(self):
        self.calls = []

    def synthesize_wav(self, text, wav, syn_config=None):
        self.calls.append(text)
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(b"\x01\x00" * len(text))


def _speech(tmp_path, pause=0.1, max_bytes=DEFAULT_CACHE_MAX_BYTES, voice=None):
    sp = PiperSpeech.__new__(PiperSpeech)
    sp.cache = ClipCache(tmp_path, max_bytes)
    sp._syn = "syn"
    sp._pause = pause
    sp._on_duration = None
    sp._voice = voice or FakeVoice()
    sp._model_tag = "test"
    return sp


def test_each_sentence_is_synthesised_once_and_cached(tmp_path):
    sp = _speech(tmp_path)
    first = sp.synthesize("Lap two. one oh four point six.")
    sp.synthesize("Lap two. one oh five point one.")
    sp.synthesize("Lap two. one oh four point six.")
    assert sp._voice.calls == ["Lap two.", "one oh four point six.", "one oh five point one."]
    expected = b"\x01\x00" * 8 + b"\x00\x00" * 100 + b"\x01\x00" * 22
    assert _frames(first) == expected


def test_a_single_sentence_is_its_own_wav(tmp_path):
    sp = _speech(tmp_path)
    assert _frames(sp.synthesize("Final lap.")) == b"\x01\x00" * 10
    assert sp._voice.calls == ["Final lap."]


class SilentVoice(FakeVoice):
    """Piper on text it has no phonemes for: writes nothing, sets no params."""

    def synthesize_wav(self, text, wav, syn_config=None):
        self.calls.append(text)


def test_text_with_nothing_to_say_gives_no_clip_and_no_file(tmp_path):
    sp = _speech(tmp_path)
    for text in ("", ".", " . ! ", "..."):
        assert sp.synthesize(text) is None
    assert sp._voice.calls == []
    assert list(tmp_path.iterdir()) == []


def test_empty_audio_from_the_voice_leaves_the_cache_clean(tmp_path):
    sp = _speech(tmp_path)
    sp._voice = SilentVoice()
    assert sp.synthesize("Hmm.") is None
    assert sp.synthesize("Hmm. Hmm again.") is None
    assert list(tmp_path.iterdir()) == []


def test_a_failing_voice_leaves_no_temp_file(tmp_path):
    class Broken(FakeVoice):
        def synthesize_wav(self, text, wav, syn_config=None):
            raise RuntimeError("onnx")

    sp = _speech(tmp_path)
    sp._voice = Broken()
    with pytest.raises(RuntimeError):
        sp.synthesize("Final lap.")
    assert list(tmp_path.iterdir()) == []


def test_unspeakable_sentences_are_dropped_from_a_callout(tmp_path):
    sp = _speech(tmp_path)
    assert _frames(sp.synthesize("Final lap. .")) == b"\x01\x00" * 10
    assert sp._voice.calls == ["Final lap."]


def _dir_bytes(path):
    return sum(f.stat().st_size for f in path.iterdir())


def test_a_joined_callout_is_removed_once_played_and_its_sentences_kept(tmp_path):
    sp = _speech(tmp_path)
    joined = sp.synthesize("Lap two. one oh four point six.")
    assert joined.exists()
    sp.release(joined)
    assert not joined.exists()
    assert len(list(tmp_path.iterdir())) == 2, "one clip per sentence"
    single = sp.synthesize("Final lap.")
    sp.release(single)
    assert single.exists(), "a cached sentence survives release"


def test_a_hundred_lap_callouts_stay_under_the_cap(tmp_path):
    from those_who_run.verbalise import lap_time_words, number_words

    cap = 4000
    sp = _speech(tmp_path, max_bytes=cap)
    for lap in range(1, 101):
        text = f"Lap {number_words(lap)}. {lap_time_words(100000 + lap * 137)}. one over best."
        clip = sp.synthesize(text)
        assert clip.exists()
        sp.release(clip)
        assert _dir_bytes(tmp_path) <= cap, lap
    assert sp.cache.total_bytes == _dir_bytes(tmp_path)
    assert not [f for f in tmp_path.iterdir() if not f.name.endswith(".wav") or "-" in f.name]


def test_eviction_is_least_recently_used(tmp_path):
    clip = 44 + 2 * len("Lap one.")  # header plus one frame per character
    sp = _speech(tmp_path, max_bytes=3 * clip)
    for text in ("Lap one.", "Lap two.", "Lap six."):
        sp.synthesize(text)
    sp.synthesize("Lap one.")  # a hit: now the most recent
    sp.synthesize("Lap ten.")  # over the cap: "Lap two." is the oldest
    calls = len(sp._voice.calls)
    sp.synthesize("Lap one.")
    sp.synthesize("Lap six.")
    assert len(sp._voice.calls) == calls, "kept"
    sp.synthesize("Lap two.")
    assert sp._voice.calls[-1] == "Lap two.", "evicted, so synthesised again"


def test_the_cache_reopens_with_its_clips_and_drops_stale_leftovers(tmp_path):
    sp = _speech(tmp_path)
    sp.synthesize("Final lap.")
    joined = sp.synthesize("Lap two. Box.")  # never released: a crash mid-playback
    tmp = tmp_path / "abc.1234.tmp.wav"
    tmp.write_bytes(b"half")
    old = time.time() - STALE_SECS - 60
    for f in (joined, tmp):
        os.utime(f, (old, old))
    again = _speech(tmp_path)
    names = sorted(f.name for f in tmp_path.iterdir())
    assert len(names) == 3 and all(len(n) == 44 for n in names), names
    assert again.cache.total_bytes == _dir_bytes(tmp_path)
    again.synthesize("Final lap.")
    assert again._voice.calls == []


def test_touching_the_voice_file_changes_the_cache_key(tmp_path):
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"onnx")
    before = voice_tag(model)
    assert voice_tag(model) == before
    st = model.stat()
    os.utime(model, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    assert voice_tag(model) != before
    touched = voice_tag(model)
    (tmp_path / "voice.onnx.json").write_text("{}")
    assert voice_tag(model) != touched, "the voice config counts too"


def test_two_threads_synthesising_the_same_text_both_get_a_valid_wav(tmp_path):
    both_inside = threading.Barrier(2, timeout=5)

    class SlowVoice(FakeVoice):
        def synthesize_wav(self, text, wav, syn_config=None):
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(RATE)
            both_inside.wait()  # both threads are writing the same sentence now
            for _ in range(len(text)):
                wav.writeframes(b"\x01\x00")
                time.sleep(0.001)

    sp = _speech(tmp_path, voice=SlowVoice())
    results, errors = [], []

    def run():
        try:
            results.append(sp.synthesize("Final lap."))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(results) == 2
    for clip in results:
        assert _frames(clip) == b"\x01\x00" * 10
    assert [f.name for f in tmp_path.iterdir()] == [results[0].name]


def test_speech_seconds_only_observes_real_synthesis(tmp_path):
    seen = []
    sp = _speech(tmp_path)
    sp._on_duration = seen.append
    sp.synthesize("Lap two. one oh four point six.")
    sp.synthesize("Lap two. one oh four point six.")
    sp.synthesize("Lap two.")
    assert len(seen) == 1
    sp.synthesize("Lap two. one oh five point one.")
    assert len(seen) == 2


def test_a_cache_dir_owned_by_someone_else_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: os.stat(tmp_path).st_uid + 1)
    with pytest.raises(PermissionError, match="GT7_CACHE_DIR"):
        ClipCache(tmp_path / "cache")


def test_reopening_leaves_another_process_s_live_files_alone(tmp_path):
    """``say`` opening the cache while the engineer is mid-callout."""
    running = _speech(tmp_path)
    joined = running.synthesize("Lap two. Box.")
    tmp = tmp_path / "abc.1234.tmp.wav"
    tmp.write_bytes(b"being written")
    _speech(tmp_path)
    assert joined.exists() and tmp.exists()


def test_a_silent_sentence_is_left_out_of_the_join(tmp_path):
    class PartlySilent(FakeVoice):
        def synthesize_wav(self, text, wav, syn_config=None):
            if text != "Hmm.":
                super().synthesize_wav(text, wav, syn_config)

    sp = _speech(tmp_path, voice=PartlySilent())
    clip = sp.synthesize("Final lap. Hmm.")
    assert _frames(clip) == b"\x01\x00" * 10, "one sentence left: no join"
    sp.release(clip)
    assert clip.exists()
    clip = sp.synthesize("Lap two. Hmm. Box.")
    assert _frames(clip) == b"\x01\x00" * 8 + b"\x00\x00" * 100 + b"\x01\x00" * 4
    sp.release(clip)
    assert not clip.exists()


def test_release_of_nothing_is_a_no_op(tmp_path):
    sp = _speech(tmp_path)
    sp.release(None)
    sp.release(sp.synthesize("."))
