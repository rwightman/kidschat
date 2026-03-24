from __future__ import annotations

import os
from types import SimpleNamespace

from tests.support import install_dependency_stubs

install_dependency_stubs()

from backend.services.stt import SpeechToText


class CapturingModel:
    def __init__(self):
        self.last_audio_input = None

    def transcribe(self, audio_input, **kwargs):
        self.last_audio_input = audio_input
        if isinstance(audio_input, str):
            assert os.path.exists(audio_input)
        return [SimpleNamespace(text="hello there")], SimpleNamespace(duration=1.0)


def test_raw_pcm_stays_in_memory():
    stt = SpeechToText()
    model = CapturingModel()
    stt._get_model = lambda: model

    text = stt._transcribe_sync(b"\x00\x01\x02\x03", 16000, "audio/raw")

    assert text == "hello there"
    assert hasattr(model.last_audio_input, "dtype")
    if hasattr(model.last_audio_input, "divisor"):
        assert model.last_audio_input.divisor == 32768.0
    else:
        assert model.last_audio_input.dtype.name == "float32"
        assert len(model.last_audio_input) == 2


def test_encoded_audio_uses_temp_file_and_cleans_it_up():
    stt = SpeechToText()
    model = CapturingModel()
    stt._get_model = lambda: model

    text = stt._transcribe_sync(b"RIFF....fake wav bytes", 16000, "audio/wav")

    assert text == "hello there"
    assert isinstance(model.last_audio_input, str)
    assert model.last_audio_input.endswith(".wav")
    assert not os.path.exists(model.last_audio_input)
