from __future__ import annotations

import asyncio
import base64
import io
from pathlib import Path
import wave

import backend.services.tts as tts_module
from backend.services.tts import TextToSpeech


class FakeProcess:
    def __init__(self, returncode: int = 0, stderr: bytes = b""):
        self.returncode = returncode
        self._stderr = stderr

    async def communicate(self, input=None):
        return b"", self._stderr


class FakeAudioChunk:
    def __init__(self, audio_bytes: bytes):
        self.sample_rate = 22050
        self.sample_width = 2
        self.sample_channels = 1
        self.audio_int16_bytes = audio_bytes


class FakePiperVoice:
    def __init__(self, chunks_by_text):
        self.chunks_by_text = chunks_by_text
        self.calls = []

    def synthesize(self, text, syn_config):
        self.calls.append((text, syn_config))
        return list(self.chunks_by_text.get(text, []))


async def _fake_tts_result(value):
    return value


def test_auto_tts_prefers_piper_then_falls_back_to_say(monkeypatch):
    monkeypatch.setattr(tts_module, "TTS_ENGINE", "auto")
    tts = TextToSpeech()
    monkeypatch.setattr(tts, "_piper_tts", lambda text: _fake_tts_result(None))
    monkeypatch.setattr(tts, "_say_tts", lambda text: _fake_tts_result("say-audio"))

    audio_b64 = asyncio.run(tts.synthesize("Hello there"))

    assert audio_b64 == "say-audio"


def test_piper_tts_encodes_wav_audio(monkeypatch):
    tts = TextToSpeech()
    voice = FakePiperVoice({"Hello there": [FakeAudioChunk(b"\x00\x00\x01\x00")]})
    syn_config = object()
    monkeypatch.setattr(tts, "_get_piper_voice", lambda: (voice, syn_config))

    audio_b64 = asyncio.run(tts._piper_tts("Hello there"))

    audio_bytes = base64.b64decode(audio_b64)
    with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
        assert wav_file.getframerate() == 22050
        assert wav_file.getnchannels() == 1
        assert wav_file.readframes(2) == b"\x00\x00\x01\x00"

    assert voice.calls == [("Hello there", syn_config)]


def test_piper_tts_inserts_sentence_and_line_pauses(monkeypatch):
    monkeypatch.setattr(tts_module, "PIPER_SENTENCE_PAUSE_MS", 100)
    monkeypatch.setattr(tts_module, "PIPER_LINE_PAUSE_MS", 200)

    tts = TextToSpeech()
    voice = FakePiperVoice(
        {
            "First line. Another sentence.": [
                FakeAudioChunk(b"\x01\x00" * 2),
                FakeAudioChunk(b"\x02\x00" * 2),
            ],
            "Second line.": [
                FakeAudioChunk(b"\x03\x00" * 2),
            ],
        }
    )
    syn_config = object()
    monkeypatch.setattr(tts, "_get_piper_voice", lambda: (voice, syn_config))

    audio_b64 = asyncio.run(tts._piper_tts("First line. Another sentence.\nSecond line."))

    audio_bytes = base64.b64decode(audio_b64)
    with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
        frames = wav_file.readframes(wav_file.getnframes())

    sentence_pause = bytes(int(22050 * 0.1) * 2)
    line_pause = bytes(int(22050 * 0.2) * 2)
    expected = (
        b"\x01\x00" * 2
        + sentence_pause
        + b"\x02\x00" * 2
        + line_pause
        + b"\x03\x00" * 2
    )

    assert frames == expected
    assert voice.calls == [
        ("First line. Another sentence.", syn_config),
        ("Second line.", syn_config),
    ]


def test_say_tts_generates_wav_without_invalid_say_flags(monkeypatch):
    tts = TextToSpeech()
    calls = []
    wav_bytes = b"RIFFfake-wav"

    async def fake_create_subprocess_exec(*args, **kwargs):
        calls.append(args)
        if args[0] == "say":
            Path(args[6]).write_bytes(b"FORMfake-aiff")
        if args[0] == "afconvert":
            Path(args[6]).write_bytes(wav_bytes)
        return FakeProcess()

    monkeypatch.setattr("backend.services.tts.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    audio_b64 = asyncio.run(tts._say_tts("Hello there"))

    assert audio_b64 == base64.b64encode(wav_bytes).decode("ascii")
    assert calls[0][0] == "say"
    assert "--data-format=LEI16@22050" not in calls[0]
    assert calls[1][0] == "afconvert"


def test_say_tts_returns_none_when_conversion_fails(monkeypatch):
    tts = TextToSpeech()

    async def fake_create_subprocess_exec(*args, **kwargs):
        if args[0] == "say":
            Path(args[6]).write_bytes(b"FORMfake-aiff")
            return FakeProcess()
        return FakeProcess(returncode=1, stderr=b"bad format")

    monkeypatch.setattr("backend.services.tts.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    audio_b64 = asyncio.run(tts._say_tts("Hello there"))

    assert audio_b64 is None


def test_clean_for_speech_removes_markdown_emoji_and_screen_instructions():
    tts = TextToSpeech()

    cleaned = tts._clean_for_speech(
        "**Here’s** a little _cat_ meowing sound for you 😺 just click the play button to hear it!"
    )

    assert cleaned == "Here’s a little cat meowing sound for you"
