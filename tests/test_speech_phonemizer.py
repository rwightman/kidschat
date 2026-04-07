from __future__ import annotations

from backend.services.speech_phonemizer import SpeechPhonemizer


class FakeG2P:
    def __init__(self):
        self.calls = []

    def __call__(self, text):
        self.calls.append(text)
        return "ðə wˈɪnd ɪz stɹˈɔŋ tədˈA.", []


def test_phonemizer_disabled_in_speech_mode():
    phonemizer = SpeechPhonemizer(mode="speech")

    assert phonemizer.phonemize("The wind is strong today.") is None


def test_phonemizer_returns_misaki_compatible_text(monkeypatch):
    phonemizer = SpeechPhonemizer(mode="auto")
    fake_g2p = FakeG2P()
    monkeypatch.setattr(phonemizer, "_get_g2p", lambda: fake_g2p)

    phonemes = phonemizer.phonemize("The wind is strong today.")

    assert phonemes == "ðə wˈɪnd ɪz stɹˈɔŋ tədˈA."
    assert fake_g2p.calls == ["The wind is strong today."]


def test_phonemizer_falls_back_cleanly_when_unavailable(monkeypatch):
    phonemizer = SpeechPhonemizer(mode="auto")
    monkeypatch.setattr(phonemizer, "_get_g2p", lambda: None)

    assert phonemizer.phonemize("The wind is strong today.") is None
