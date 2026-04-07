"""
Speech text normalization helpers for TTS.

This module optionally uses NVIDIA NeMo text normalization and adds a
small pre-expansion layer for compact measurements that NeMo does not
verbalize well on its own (for example `4.8C` or `14.8km/h`).
"""

from __future__ import annotations

import logging
import os
import re

log = logging.getLogger("kidschat.speech_normalizer")

SPEECH_NORMALIZER = os.getenv("SPEECH_NORMALIZER", "auto").lower()
SPEECH_NORMALIZER_INPUT_CASE = os.getenv(
    "SPEECH_NORMALIZER_INPUT_CASE", "cased"
)
SPEECH_NORMALIZER_LANG = os.getenv("SPEECH_NORMALIZER_LANG", "en")

_FALSE_VALUES = {"0", "false", "no", "off"}
EXPAND_COMPACT_UNITS = (
    os.getenv("SPEECH_NORMALIZER_EXPAND_COMPACT_UNITS", "true").lower()
    not in _FALSE_VALUES
)

TEMPERATURE_RE = re.compile(
    r"(?<![\w/])(?P<value>-?\d+(?:\.\d+)?)\s*°?\s*(?P<unit>[CF])\b"
)
KMH_RE = re.compile(r"(?<![\w/])(?P<value>-?\d+(?:\.\d+)?)\s*km/h\b", re.IGNORECASE)
MPH_RE = re.compile(r"(?<![\w/])(?P<value>-?\d+(?:\.\d+)?)\s*mph\b", re.IGNORECASE)
MPS_RE = re.compile(r"(?<![\w/])(?P<value>-?\d+(?:\.\d+)?)\s*m/s\b", re.IGNORECASE)
PERCENT_RE = re.compile(r"(?<![\w/])(?P<value>-?\d+(?:\.\d+)?)\s*%")


class SpeechNormalizer:
    def __init__(
        self,
        mode: str | None = None,
        *,
        input_case: str | None = None,
        lang: str | None = None,
        expand_compact_units: bool | None = None,
    ):
        self.mode = (mode or SPEECH_NORMALIZER).lower()
        self.input_case = input_case or SPEECH_NORMALIZER_INPUT_CASE
        self.lang = lang or SPEECH_NORMALIZER_LANG
        self.expand_compact_units = (
            EXPAND_COMPACT_UNITS
            if expand_compact_units is None
            else expand_compact_units
        )
        self._nemo_normalizer = None
        self._nemo_attempted = False

    def normalize(self, text: str) -> str:
        """Normalize text for speech output."""
        if not text:
            return ""

        expanded = self._expand_compact_measurements(text)
        if self.mode == "none":
            return expanded

        normalizer = self._get_nemo_normalizer()
        if normalizer is None:
            return expanded

        try:
            normalized = normalizer.normalize(expanded, verbose=False)
            normalized = re.sub(r"\s{2,}", " ", normalized).strip()
            return normalized or expanded
        except Exception as e:
            log.warning("Speech normalization failed, using expanded text: %s", e)
            return expanded

    def _get_nemo_normalizer(self):
        if self._nemo_attempted:
            return self._nemo_normalizer

        self._nemo_attempted = True

        try:
            from nemo_text_processing.text_normalization.normalize import Normalizer
        except ImportError:
            if self.mode == "nemo":
                log.warning(
                    "SPEECH_NORMALIZER is set to 'nemo' but nemo_text_processing "
                    "is not installed."
                )
            return None

        try:
            self._nemo_normalizer = Normalizer(
                input_case=self.input_case,
                lang=self.lang,
            )
        except Exception as e:
            log.warning("Failed to initialize NeMo speech normalizer: %s", e)
            self._nemo_normalizer = None

        return self._nemo_normalizer

    def _expand_compact_measurements(self, text: str) -> str:
        if not self.expand_compact_units:
            return text

        text = TEMPERATURE_RE.sub(self._replace_temperature, text)
        text = KMH_RE.sub(r"\g<value> kilometers per hour", text)
        text = MPH_RE.sub(r"\g<value> miles per hour", text)
        text = MPS_RE.sub(r"\g<value> meters per second", text)
        text = PERCENT_RE.sub(r"\g<value> percent", text)
        text = re.sub(r"\s{2,}", " ", text)
        return text.strip()

    @staticmethod
    def _replace_temperature(match: re.Match[str]) -> str:
        unit = match.group("unit").upper()
        label = "degrees Celsius" if unit == "C" else "degrees Fahrenheit"
        return f"{match.group('value')} {label}"
