"""
Speech-to-text using faster-whisper (runs locally on CPU/Metal).
"""

import asyncio
import logging
import os
import tempfile

import numpy as np

log = logging.getLogger("kidschat.stt")

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base.en")


class SpeechToText:
    def __init__(self):
        self._model = None

    def _get_model(self):
        """Lazy-load the Whisper model on first use."""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel

                log.info(f"Loading Whisper model: {WHISPER_MODEL}")
                # On Apple Silicon, "auto" will use CoreML if available,
                # otherwise falls back to CPU which is still fast
                self._model = WhisperModel(
                    WHISPER_MODEL,
                    device="auto",
                    compute_type="int8",
                )
                log.info("Whisper model loaded")
            except ImportError:
                log.error(
                    "faster-whisper not installed. "
                    "Run: pip install faster-whisper"
                )
                raise
        return self._model

    async def transcribe(
        self,
        audio_bytes: bytes,
        sample_rate: int = 16000,
        mime_type: str = "audio/raw",
    ) -> str:
        """
        Transcribe incoming audio bytes to text.

        Args:
            audio_bytes: Raw or containerized audio bytes
            sample_rate: Sample rate for raw PCM input
            mime_type: MIME type sent by the browser

        Returns:
            Transcribed text string
        """
        # Run in executor to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._transcribe_sync, audio_bytes, sample_rate, mime_type
        )

    def _transcribe_sync(
        self,
        audio_bytes: bytes,
        sample_rate: int,
        mime_type: str,
    ) -> str:
        """Synchronous transcription."""
        model = self._get_model()
        temp_path = None

        if not audio_bytes:
            return ""

        try:
            if mime_type in {"audio/raw", "audio/pcm"}:
                # Convert raw PCM bytes to float32 numpy array.
                audio_input = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
                audio_input /= 32768.0  # Normalize to [-1, 1]

                if sample_rate != 16000:
                    log.warning(
                        f"Raw PCM provided at {sample_rate} Hz; expected 16000 Hz"
                    )
            else:
                suffix = self._suffix_for_mime_type(mime_type)
                with tempfile.NamedTemporaryFile(
                    suffix=suffix, delete=False
                ) as temp_audio:
                    temp_audio.write(audio_bytes)
                    temp_path = temp_audio.name

                audio_input = temp_path

            segments, info = model.transcribe(
                audio_input,
                beam_size=3,
                language="en",
                vad_filter=True,  # Filter out silence
                vad_parameters=dict(
                    min_silence_duration_ms=500,
                    speech_pad_ms=200,
                ),
            )

            text = " ".join(seg.text.strip() for seg in segments)
            log.info(f"Transcribed ({info.duration:.1f}s): {text[:80]}")
            return text
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def _suffix_for_mime_type(self, mime_type: str) -> str:
        """Best-effort file suffix for encoded audio passed through tempfile."""
        suffix_map = {
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/webm": ".webm",
            "audio/ogg": ".ogg",
            "audio/mp4": ".mp4",
            "audio/mpeg": ".mp3",
        }
        return suffix_map.get(mime_type, ".bin")
