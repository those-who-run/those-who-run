import wave

from those_who_run.speech import PiperSpeech, join_wavs, split_sentences

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


def _speech(tmp_path, pause=0.1):
    sp = PiperSpeech.__new__(PiperSpeech)
    sp.cache_dir = tmp_path
    sp._syn = "syn"
    sp._pause = pause
    sp._on_duration = None
    sp._voice = FakeVoice()
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
