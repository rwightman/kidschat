"""
Text-to-speech service.

Supports two backends:
  - "say": macOS built-in TTS (zero setup, decent quality)
  - "piper": Piper TTS (better quality, local ONNX voice model)

Audio is returned as base64-encoded WAV for playback in the browser.
"""

import asyncio
import base64
import io
import logging
import os
import re
import tempfile
import wave
from pathlib import Path

log = logging.getLogger("kidschat.tts")

TTS_ENGINE = os.getenv("TTS_ENGINE", "auto").lower()
PIPER_VOICE = os.getenv("PIPER_VOICE", "en_US-lessac-medium")
PIPER_DOWNLOAD_DIR = Path(
    os.getenv(
        "PIPER_DOWNLOAD_DIR",
        Path.home() / ".cache" / "kidschat" / "piper",
    )
).expanduser()
PIPER_SENTENCE_PAUSE_MS = int(os.getenv("PIPER_SENTENCE_PAUSE_MS", "180"))
PIPER_LINE_PAUSE_MS = int(os.getenv("PIPER_LINE_PAUSE_MS", "320"))
EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U0001F1E6-\U0001F1FF"
    "\u2600-\u27BF"
    "]",
    flags=re.UNICODE,
)
SCREEN_LANGUAGE_RE = re.compile(
    r"(?i)(?:\s*[-,:;]?\s*)?"
    r"(?:just\s+)?(?:click|tap|press)\s+(?:the\s+)?play button"
    r"(?:\s+to\s+hear\s+(?:it|the sound))?"
    r"[.!]?"
)


def clean_text_for_speech(text: str, preserve_line_breaks: bool = False) -> str:
    """Strip markdown and screen-only text for natural speech output."""
    # Remove fenced/inline code before generic markdown cleanup.
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`(.*?)`", r"\1", text)
    # Convert Markdown images/links to their visible labels.
    text = re.sub(r"!\[(.*?)\]\(.*?\)", r"\1", text)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    # Drop common Markdown block syntax that sounds awkward when spoken.
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s{0,3}>\s?", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    text = re.sub(r"(?m)^\s*\d+\.\s+", "", text)
    # Remove markdown emphasis markers.
    text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}(.*?)_{1,3}", r"\1", text)
    text = re.sub(r"~~(.*?)~~", r"\1", text)
    # Remove [ESCALATE] markers
    text = re.sub(r"\[ESCALATE\].*", "", text)
    # Remove emoji and similar symbols that sound awkward in TTS
    text = EMOJI_RE.sub("", text)
    # Remove screen-specific instructions that should not be spoken
    text = SCREEN_LANGUAGE_RE.sub("", text)
    text = re.sub(r"(?i)\b(?:in|on)\s+the\s+app\b", "", text)
    text = re.sub(r"(?i)\b(?:on\s+the\s+card|in\s+the\s+card)\b", "", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)

    if preserve_line_breaks:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text).strip()
    else:
        text = re.sub(r"\s+", " ", text).strip()

    # Truncate very long responses for TTS (read first ~500 chars)
    compact_text = re.sub(r"\s+", " ", text).strip()
    if len(compact_text) > 500:
        # Find a sentence boundary near 500 chars
        cutoff = compact_text[:500].rfind(".")
        if cutoff > 200:
            text = compact_text[: cutoff + 1]
        else:
            text = compact_text[:500] + "..."

    return text


class TextToSpeech:
    def __init__(self):
        self._piper_voice = None
        self._piper_syn_config = None

    async def synthesize(self, text: str) -> str | None:
        """
        Convert text to speech audio.

        Returns:
            Base64-encoded WAV audio string, or None if TTS is unavailable.
        """
        if not text or not text.strip():
            return None

        # Clean text for speech (remove markdown, special chars)
        engines = self._engine_order()
        if not engines:
            log.warning(f"Unknown TTS engine: {TTS_ENGINE}")
            return None

        for engine in engines:
            match engine:
                case "piper":
                    audio_b64 = await self._piper_tts(
                        self._clean_for_speech(text, preserve_line_breaks=True)
                    )
                case "say":
                    audio_b64 = await self._say_tts(self._clean_for_speech(text))
                case _:
                    log.warning(f"Unknown TTS engine: {engine}")
                    continue

            if audio_b64:
                return audio_b64

        return None

    def _engine_order(self) -> list[str]:
        if TTS_ENGINE == "auto":
            return ["piper", "say"]
        if TTS_ENGINE == "piper":
            return ["piper", "say"]
        if TTS_ENGINE == "say":
            return ["say"]
        return []

    async def _say_tts(self, text: str) -> str | None:
        """Use macOS `say` command to generate speech."""
        with tempfile.TemporaryDirectory(prefix="kidschat-tts-") as tempdir:
            aiffpath = Path(tempdir) / "speech.aiff"
            wavpath = Path(tempdir) / "speech.wav"

            try:
                # Keep the `say` step simple and let afconvert handle WAV encoding.
                proc = await asyncio.create_subprocess_exec(
                    "say",
                    "-v", "Samantha",
                    "-r", "190",  # Slightly slower for kids
                    "-o", str(aiffpath),
                    text,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError:
                log.warning("macOS `say` command is not available")
                return None

            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                log.warning(f"say failed: {stderr.decode().strip()}")
                return None

            try:
                proc2 = await asyncio.create_subprocess_exec(
                    "afconvert",
                    "-f", "WAVE",
                    "-d", "LEI16@22050",
                    str(aiffpath),
                    str(wavpath),
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError:
                log.warning("macOS `afconvert` command is not available")
                return None

            _, stderr2 = await proc2.communicate()
            if proc2.returncode != 0:
                log.warning(f"afconvert failed: {stderr2.decode().strip()}")
                return None

            if not wavpath.exists():
                log.warning("afconvert completed without producing a WAV file")
                return None

            audio_bytes = wavpath.read_bytes()
            return base64.b64encode(audio_bytes).decode("ascii")

    async def _piper_tts(self, text: str) -> str | None:
        """Use Piper TTS for higher quality local synthesis."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._piper_tts_sync, text)

    def _piper_tts_sync(self, text: str) -> str | None:
        try:
            voice, syn_config = self._get_piper_voice()
        except ImportError:
            log.warning("piper-tts is not installed")
            return None
        except Exception as e:
            log.warning(f"Failed to initialize Piper: {e}")
            return None

        try:
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wav_file:
                wrote_audio = False
                segments = self._split_piper_segments(text)

                for segment_index, segment in enumerate(segments):
                    segment_chunks = list(voice.synthesize(segment, syn_config))
                    if not segment_chunks:
                        continue

                    for chunk_index, chunk in enumerate(segment_chunks):
                        if not wrote_audio:
                            wav_file.setframerate(chunk.sample_rate)
                            wav_file.setsampwidth(chunk.sample_width)
                            wav_file.setnchannels(chunk.sample_channels)
                            wrote_audio = True
                        elif chunk_index > 0:
                            self._write_silence(wav_file, chunk, PIPER_SENTENCE_PAUSE_MS)

                        wav_file.writeframes(chunk.audio_int16_bytes)

                    if segment_index < len(segments) - 1:
                        self._write_silence(
                            wav_file,
                            segment_chunks[-1],
                            PIPER_LINE_PAUSE_MS,
                        )

            if not wrote_audio:
                log.warning("Piper produced no audio")
                return None

            return base64.b64encode(wav_buffer.getvalue()).decode("ascii")
        except Exception as e:
            log.warning(f"Piper synthesis failed: {e}")
            return None

    def _get_piper_voice(self):
        if self._piper_voice is not None and self._piper_syn_config is not None:
            return self._piper_voice, self._piper_syn_config

        from piper import PiperVoice, SynthesisConfig
        from piper.download_voices import download_voice

        PIPER_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

        model_path = PIPER_DOWNLOAD_DIR / f"{PIPER_VOICE}.onnx"
        config_path = PIPER_DOWNLOAD_DIR / f"{PIPER_VOICE}.onnx.json"

        if not model_path.exists() or not config_path.exists():
            log.info(
                "Downloading Piper voice %s to %s",
                PIPER_VOICE,
                PIPER_DOWNLOAD_DIR,
            )
            download_voice(PIPER_VOICE, PIPER_DOWNLOAD_DIR)

        self._piper_voice = PiperVoice.load(model_path, config_path=config_path)
        self._piper_syn_config = SynthesisConfig()
        return self._piper_voice, self._piper_syn_config

    def _split_piper_segments(self, text: str) -> list[str]:
        """Break cleaned text into line-based segments for stronger pauses."""
        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        segments = [line for line in lines if line]
        return segments or [re.sub(r"\s+", " ", text).strip()]

    def _write_silence(self, wav_file: wave.Wave_write, chunk, pause_ms: int) -> None:
        """Append a stretch of silence to the WAV stream."""
        if pause_ms <= 0:
            return

        sample_width = max(1, int(chunk.sample_width))
        channels = max(1, int(chunk.sample_channels))
        frame_count = int(chunk.sample_rate * (pause_ms / 1000.0))
        wav_file.writeframes(bytes(frame_count * sample_width * channels))

    def _clean_for_speech(self, text: str, preserve_line_breaks: bool = False) -> str:
        """Strip markdown and special formatting for natural speech."""
        return clean_text_for_speech(text, preserve_line_breaks=preserve_line_breaks)
