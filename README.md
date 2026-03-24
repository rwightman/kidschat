# 🧒 KidsChat — AI Voice Assistant Demo

A real-time, voice-enabled AI assistant for kids, running locally on Apple Silicon
with cloud escalation for complex questions.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Web UI (Browser)                      │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ Mic Input │  │ Chat Display │  │ Media Canvas      │  │
│  │ (WebAudio)│  │ (bubbles)    │  │ (images/diagrams) │  │
│  └─────┬─────┘  └──────▲───────┘  └────────▲──────────┘  │
│        │               │                   │              │
│        │         WebSocket (JSON)           │              │
└────────┼───────────────┼───────────────────┼──────────────┘
         │               │                   │
┌────────▼───────────────┴───────────────────┴──────────────┐
│                  FastAPI Backend                           │
│                                                           │
│  ┌─────────┐   ┌──────────────┐   ┌────────────────────┐ │
│  │ Whisper  │   │  Router /    │   │  Tool Executor     │ │
│  │ (STT)   │──▶│  Orchestrator│──▶│  (search, images,  │ │
│  └─────────┘   │              │   │   diagrams, math)  │ │
│                │              │   └────────────────────┘ │
│  ┌─────────┐   │   ┌─────┐   │                          │
│  │ Piper / │◀──│   │Local│   │   ┌────────────────────┐ │
│  │ say TTS │   │   │ LLM │   │   │  Cloud Escalation  │ │
│  └─────────┘   │   │(oss)│   │   │  Claude / GPT /    │ │
│                │   └─────┘   │   │  Gemini            │ │
│                └──────────────┘   └────────────────────┘ │
└───────────────────────────────────────────────────────────┘
```

## Prerequisites

### 1. Install Ollama & pull model
```bash
brew install ollama
ollama serve  # in one terminal
ollama pull gpt-oss:20b
```

### 2. Install whisper.cpp (local speech-to-text)
```bash
brew install whisper-cpp
# Download a model:
whisper-cpp-download-model base.en
```
Or use faster-whisper via pip (see below).

### 3. Install Piper TTS (optional, for natural voice)
```bash
pip install piper-tts
# Or use macOS built-in: `say` command (zero setup)
```

### 4. Python dependencies
```bash
cd kidschat
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 5. API keys for cloud escalation
```bash
cp config/env.example .env
# Edit .env with your API keys (only needed for cloud features)
```

### 6. Run
```bash
# Terminal 1: Ollama
ollama serve

# Terminal 2: App
source .venv/bin/activate
python -m uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** in your browser.

## How It Works

1. **Kid speaks** → browser captures audio via WebAudio API
2. **Audio sent** → WebSocket streams PCM audio to backend
3. **Whisper transcribes** → local STT, no cloud needed
4. **Router decides** →
   - Simple/conversational → gpt-oss-20b locally (fast path, ~200ms)
   - Needs tools (images, search, diagrams) → local LLM with tool calling
   - Complex reasoning → escalate to Claude / GPT / Gemini
5. **Response streams back** → text, images, or diagrams via WebSocket
6. **TTS speaks** → Piper or macOS `say` reads response aloud

## Tool Calling

The local gpt-oss-20b model handles tool calls natively:

- `search_images` — fetch kid-safe images from the web
- `draw_diagram` — generate Mermaid diagrams
- `do_math` — evaluate math expressions with explanations
- `get_weather` — current weather for any location
- `tell_joke` — age-appropriate jokes and riddles
- `fun_fact` — random interesting facts

## Cloud Escalation Strategy

The router uses a confidence-based approach:
1. Local model runs on **low reasoning effort** first
2. If the model signals uncertainty OR the question matches complexity heuristics
   (multi-step reasoning, current events, creative writing), escalate
3. Cloud provider is chosen round-robin or by specialty
4. Response is streamed back through the same TTS pipeline

## Project Structure

```
kidschat/
├── backend/
│   ├── app.py              # FastAPI entry point + WebSocket handler
│   ├── orchestrator.py     # Main conversation loop & routing
│   ├── services/
│   │   ├── llm_local.py    # Ollama / gpt-oss-20b integration
│   │   ├── llm_cloud.py    # Claude, OpenAI, Gemini clients
│   │   ├── stt.py          # Whisper speech-to-text
│   │   └── tts.py          # Text-to-speech (Piper / say)
│   └── tools/
│       ├── registry.py     # Tool definitions & dispatch
│       ├── search.py       # Image search tool
│       ├── diagram.py      # Mermaid diagram tool
│       └── fun.py          # Jokes, facts, math
├── frontend/
│   ├── templates/
│   │   └── index.html      # Main UI
│   └── static/
│       ├── css/style.css    # Styling
│       └── js/app.js        # WebSocket client & audio
├── config/
│   └── env.example          # API key template
├── requirements.txt
└── README.md
```
