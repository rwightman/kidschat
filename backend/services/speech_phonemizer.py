"""
Optional phoneme generation for browser-side HeadTTS.

This allows the server to send Misaki-compatible phonemes to the browser so
HeadTTS can synthesize from `phonetic` input instead of re-running its own
dictionary/G2P path for tricky words like heteronyms.
"""

from __future__ import annotations

import logging
import os
import re

log = logging.getLogger("kidschat.speech_phonemizer")

HEADTTS_INPUT_MODE = os.getenv("HEADTTS_INPUT_MODE", "auto").lower()
HEADTTS_PHONEMIZER_USE_ESPEAK = (
    os.getenv("HEADTTS_PHONEMIZER_USE_ESPEAK", "true").lower()
    not in {"0", "false", "no", "off"}
)
HEADTTS_PHONEMIZER_USE_TRANSFORMER = (
    os.getenv("HEADTTS_PHONEMIZER_USE_TRANSFORMER", "false").lower()
    in {"1", "true", "yes", "on"}
)
HEADTTS_PHONEMIZER_LANGUAGE = os.getenv("HEADTTS_PHONEMIZER_LANGUAGE", "en-us").lower()


class SpeechPhonemizer:
    def __init__(
        self,
        mode: str | None = None,
        *,
        language: str | None = None,
        use_espeak: bool | None = None,
        use_transformer: bool | None = None,
    ):
        self.mode = (mode or HEADTTS_INPUT_MODE).lower()
        self.language = (language or HEADTTS_PHONEMIZER_LANGUAGE).lower()
        self.use_espeak = (
            HEADTTS_PHONEMIZER_USE_ESPEAK if use_espeak is None else use_espeak
        )
        self.use_transformer = (
            HEADTTS_PHONEMIZER_USE_TRANSFORMER
            if use_transformer is None
            else use_transformer
        )
        self._g2p = None
        self._attempted = False

    def phonemize(self, text: str) -> str | None:
        """Return HeadTTS-compatible phonemes, or None if disabled/unavailable."""
        if self.mode == "speech" or not text:
            return None

        g2p = self._get_g2p()
        if g2p is None:
            return None

        try:
            phonemes, _tokens = g2p(text)
        except Exception as e:
            log.warning("Speech phonemization failed, using text input: %s", e)
            return None

        if not phonemes:
            return None

        phonemes = re.sub(r"\s{2,}", " ", phonemes).strip()
        return phonemes or None

    def _get_g2p(self):
        if self._attempted:
            return self._g2p

        self._attempted = True

        if self.language not in {"en", "en-us", "en_us", "a"}:
            log.warning(
                "Speech phonemizer language %s is not supported yet; using plain speech.",
                self.language,
            )
            return None

        try:
            from misaki import en
        except ImportError:
            if self.mode == "phonetic":
                log.warning(
                    "HEADTTS_INPUT_MODE is set to 'phonetic' but misaki is not installed."
                )
            return None

        british = self.language in {"en-gb", "en_gb", "b"}
        fallback = None

        if self.use_espeak:
            try:
                from misaki import espeak

                fallback = espeak.EspeakFallback(british=british)
            except Exception as e:
                log.warning(
                    "Failed to initialize Misaki eSpeak fallback; continuing without it: %s",
                    e,
                )

        try:
            self._g2p = en.G2P(
                trf=self.use_transformer,
                british=british,
                fallback=fallback,
            )
        except Exception as e:
            log.warning("Failed to initialize Misaki G2P; using plain speech: %s", e)
            self._g2p = None

        return self._g2p
