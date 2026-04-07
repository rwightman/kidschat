# KidsChat

KidsChat is a local-first prototype web app for demonstrating AI to children in a playful, voice-friendly way. It combines a browser chat UI, local Ollama-hosted models, speech input/output, a talking-head avatar, and a small set of fun tools like pictures, sounds, jokes, math, and weather.

## Prototype Notice

This is a prototype/demo application.

- It is intended to demo AI to children in a fun setting with an adult present.
- It has not been tested, safety-reviewed, or hardened for extensive 1-on-1 interaction with children.
- It should not be treated as a child-safety product, tutoring product, or unsupervised companion app.
- Tool outputs come from local models plus live third-party data sources and can still be wrong, awkward, or inappropriate in edge cases.

If you use this with children, do it with adult supervision.

## What It Does

- Text input plus push-to-talk microphone input
- Local speech-to-text with `faster-whisper`
- Local LLM responses through Ollama
- Optional cloud escalation to Claude, OpenAI, or Gemini when API keys are configured
- Browser-rendered talking-head avatar with HeadTTS + TalkingHead
- Local/server fallback TTS with Piper or macOS `say`
- Tool calling for:
  - image search
  - sound search/playback
  - kid-friendly jokes and facts
  - weather
  - math
  - diagrams
  - simple SVG drawings

## Tech Stack

### Backend

- Python 3.11+
- FastAPI
- WebSockets
- Ollama Python client
- `faster-whisper` for STT
- Piper TTS and macOS `say` fallback
- Optional NeMo text normalization
- Optional Misaki + phonemizer/eSpeak phonetic preprocessing for HeadTTS

### Frontend

- Plain HTML, CSS, and vanilla JavaScript
- Mermaid for diagrams
- HeadTTS for browser-side speech
- TalkingHead + Three.js for the avatar

### External Services / Data Sources

- Ollama for local model hosting
- Open-Meteo for weather
- Openverse or Unsplash for images
- Openverse audio for sound clips
- Optional Claude / OpenAI / Gemini cloud fallback

## High-Level Architecture

1. The browser sends text or recorded audio to the backend over a WebSocket.
2. Audio is transcribed locally with `faster-whisper`.
3. The orchestrator sends the conversation to a local Ollama model first.
4. If the model wants tools, the backend runs them and sends structured results back to the UI.
5. If the local model cannot handle the prompt well enough, the app can escalate to a configured cloud provider.
6. The backend emits:
   - visible chat text
   - structured media events for images, sounds, diagrams, and SVG
   - a separate speech-only text path for TTS
7. The frontend renders chat/media and, when available, uses the talking head to speak with browser-side TTS.
8. If browser-side avatar speech is unavailable, the backend falls back to Piper or `say`.

## Current Feature Set

### Chat and Voice

- Conversational chat with a kid-friendly system prompt
- Press-and-hold microphone button for voice input
- Separate display text vs speech text path so spoken output can be cleaner than on-screen text
- Server-side speech cleanup and normalization for units, punctuation, markdown, and UI-specific phrases
- Optional server-side phonetic generation for better HeadTTS pronunciation

### Media and Interactive Tools

- `search_images`: shows image cards in the chat UI
- `play_sound`: shows an inline audio player for sound clips
- `create_diagram`: creates Mermaid diagrams for explicit chart/flow/cycle requests
- `draw_picture`: creates sanitized inline SVG drawings
- `do_math`: solves simple math expressions
- `get_weather`: fetches current weather
- `tell_joke`: returns kid-friendly jokes/riddles
- `fun_fact`: returns fun facts by topic

### Talking Head

- Browser-side talking-head panel with a local avatar asset
- Default local avatar: `frontend/static/avatars/julia.glb`
- Configurable Kokoro/HeadTTS voice and TalkingHead avatar selection
- Browser-side speech prefers phonetic input when available

## Local Model Notes

The app is local-model-first. `OLLAMA_MODEL` controls which local model is used.

Examples:

- `gpt-oss:20b`
- `gemma4:31b`
- `qwen3:30b`

The local adapter now has model-family-specific handling for some model families, such as:

- prompt shaping
- response cleanup
- model-specific Ollama sampling options

At the moment, the app uses local models for text/tool orchestration only. Even if a model supports vision, that is not fully wired into the product flow yet.

## Project Layout

```text
kidschat/
├── backend/
│   ├── app.py
│   ├── orchestrator.py
│   ├── services/
│   │   ├── llm_local.py
│   │   ├── llm_cloud.py
│   │   ├── stt.py
│   │   ├── tts.py
│   │   ├── speech_normalizer.py
│   │   └── speech_phonemizer.py
│   └── tools/
│       ├── registry.py
│       ├── search.py
│       ├── sound.py
│       ├── picture.py
│       ├── diagram.py
│       └── fun.py
├── frontend/
│   ├── templates/
│   │   └── index.html
│   └── static/
│       ├── avatars/
│       ├── css/
│       └── js/
├── config/
│   └── env.example
├── tests/
├── requirements.txt
└── README.md
```

## Quick Start

### 1. Create an environment

Using conda:

```bash
conda create -n kidschat python=3.11 -y
conda activate kidschat
pip install -r requirements.txt
```

Or with a venv:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp config/env.example .env
```

Edit `.env` as needed. The most important setting is:

```env
OLLAMA_MODEL=gpt-oss:20b
```

Other common examples:

```env
OLLAMA_MODEL=gemma4:31b
TTS_ENGINE=auto
TALKING_HEAD_CHARACTER=julia
HEADTTS_INPUT_MODE=auto
```

### 3. Install and run Ollama

Install Ollama, make sure it is running, and pull the model you want to use.

Examples:

```bash
ollama pull gpt-oss:20b
```

```bash
ollama pull gemma4:31b
```

### 4. Run the app

```bash
python -m uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://localhost:8000
```

## Configuration

See [config/env.example](config/env.example) for the current full set of options.

Important groups:

- local model:
  - `OLLAMA_MODEL`
  - `OLLAMA_HOST`
- STT:
  - `WHISPER_MODEL`
- server TTS:
  - `TTS_ENGINE`
  - `PIPER_VOICE`
- browser talking head:
  - `HEADTTS_VOICE`
  - `HEADTTS_LANGUAGE`
  - `HEADTTS_DICTIONARY_URL`
  - `HEADTTS_INPUT_MODE`
- avatar:
  - `TALKING_HEAD_CHARACTER`
  - `TALKING_HEAD_AVATAR_URL`
  - `TALKING_HEAD_BODY`
- speech preprocessing:
  - `SPEECH_NORMALIZER`
  - `HEADTTS_PHONEMIZER_USE_ESPEAK`

## Browser Notes

- Desktop Chrome or Edge currently gives the best talking-head / browser TTS experience.
- The app still works without the avatar path, but falls back to backend audio.
- Microphone access must be granted in the browser.

## Testing

Pytest tests cover the main backend paths and selected frontend-adjacent behavior.

Run:

```bash
python -m pytest -q
```

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE).

## Non-Goals / Limitations

- Not a production deployment
- Not a child-safety moderation system
- Not an educational accuracy guarantee
- Not hardened against prompt attacks, persistent misuse, or determined abuse
- Not tuned for long unsupervised sessions
- Browser avatar/TTS path depends on modern desktop browser support
- Live media/data providers can fail, rate-limit, or return imperfect results

## Future Directions

- Better multimodal support for local models with vision towers
- More deliberate kid-safe guardrails and supervision UX
- Better curated tool/data backends for children
- More avatars and voice choices
- More polished activity/animation around speech and listening
