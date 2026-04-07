from __future__ import annotations

from backend.services.speech_normalizer import SpeechNormalizer


class FakeNemoNormalizer:
    def __init__(self):
        self.calls = []

    def normalize(self, text: str, verbose: bool = False) -> str:
        self.calls.append((text, verbose))
        return f"spoken: {text}"


def test_none_mode_skips_nemo_and_preserves_text():
    normalizer = SpeechNormalizer(mode="none", expand_compact_units=False)

    assert normalizer.normalize("It is 4.8C.") == "It is 4.8C."


def test_compact_measurements_expand_before_nemo(monkeypatch):
    normalizer = SpeechNormalizer(mode="auto")
    fake_nemo = FakeNemoNormalizer()
    monkeypatch.setattr(normalizer, "_get_nemo_normalizer", lambda: fake_nemo)

    result = normalizer.normalize("It is 4.8C with winds of 14.8km/h and humidity of 25%.")

    assert result == (
        "spoken: It is 4.8 degrees Celsius with winds of 14.8 kilometers per hour "
        "and humidity of 25 percent."
    )
    assert fake_nemo.calls == [
        (
            "It is 4.8 degrees Celsius with winds of 14.8 kilometers per hour and humidity of 25 percent.",
            False,
        )
    ]


def test_auto_mode_falls_back_to_expanded_text_when_nemo_is_missing(monkeypatch):
    normalizer = SpeechNormalizer(mode="auto")
    monkeypatch.setattr(normalizer, "_get_nemo_normalizer", lambda: None)

    result = normalizer.normalize("It is 4.8C with winds of 14.8km/h.")

    assert result == "It is 4.8 degrees Celsius with winds of 14.8 kilometers per hour."
