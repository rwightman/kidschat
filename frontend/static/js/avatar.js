import { TalkingHead } from "talkinghead";
import { HeadTTS } from "headtts";

const HEADTTS_CDN_ROOT = "https://cdn.jsdelivr.net/npm/@met4citizen/headtts@1.2";
const DEFAULT_AVATAR_URL =
  "/static/avatars/julia.glb";
const DEFAULT_AVATAR_BODY = "F";
const DEFAULT_HEADTTS_VOICE = "af_bella";
const DEFAULT_HEADTTS_LANGUAGE = "en-us";
const DEFAULT_HEADTTS_DICTIONARY_URL =
  `${HEADTTS_CDN_ROOT}/dictionaries/`;

const shell = document.getElementById("avatar-shell");
const stage = document.getElementById("avatar-stage");
const statusEl = document.getElementById("avatar-status");
const noteEl = document.getElementById("avatar-note");
const toggleBtn = document.getElementById("avatar-toggle");
const placeholderEl = document.getElementById("avatar-stage-placeholder");

const avatarUrl = shell?.dataset.avatarUrl?.trim() || DEFAULT_AVATAR_URL;
const avatarBody = (() => {
  const value = shell?.dataset.avatarBody?.trim()?.toUpperCase() || DEFAULT_AVATAR_BODY;
  return value === "M" || value === "F" ? value : DEFAULT_AVATAR_BODY;
})();
const avatarVoice = shell?.dataset.avatarVoice?.trim() || DEFAULT_HEADTTS_VOICE;
const avatarLanguage = shell?.dataset.avatarLanguage?.trim() || DEFAULT_HEADTTS_LANGUAGE;
const avatarDictionaryUrl = (() => {
  const value = shell?.dataset.avatarDictionaryUrl?.trim();
  if (!value) return null;
  return value;
})();

let enabled = true;
let head = null;
let headtts = null;
let ready = false;
let initPromise = null;

function setStatus(text, tone = "idle") {
  if (statusEl) {
    statusEl.textContent = text;
    statusEl.dataset.tone = tone;
  }
}

function setNote(text) {
  if (noteEl) {
    noteEl.textContent = text;
  }
}

function updateToggle() {
  if (!toggleBtn) return;
  toggleBtn.textContent = enabled ? "Avatar Voice On" : "Avatar Voice Off";
  toggleBtn.classList.toggle("is-off", !enabled);
  toggleBtn.setAttribute("aria-pressed", enabled ? "true" : "false");
}

function showPlaceholder(text) {
  if (!placeholderEl) return;
  placeholderEl.hidden = false;
  placeholderEl.textContent = text;
}

function hidePlaceholder() {
  if (!placeholderEl) return;
  placeholderEl.hidden = true;
}

async function initAvatar() {
  if (!shell || !stage) return false;
  if (ready) return true;
  if (initPromise) return initPromise;

  initPromise = (async () => {
    setStatus("Loading avatar and voice...", "loading");
    showPlaceholder("Loading avatar and voice...");

    try {
      head = new TalkingHead(stage, {
        lipsyncModules: ["en"],
        mixerGainSpeech: 2.2,
        cameraView: "upper",
        cameraDistance: 0.05,
        cameraY: 0.02,
        cameraRotateEnable: false,
        cameraZoomEnable: false,
        cameraPanEnable: false,
      });

      await head.showAvatar({
        url: avatarUrl,
        body: avatarBody,
        lipsyncLang: "en",
        avatarMood: "neutral",
      });

      headtts = new HeadTTS({
        endpoints: ["webgpu", "wasm"],
        workerModule: `${HEADTTS_CDN_ROOT}/modules/worker-tts.mjs`,
        dictionaryURL: avatarDictionaryUrl ?? DEFAULT_HEADTTS_DICTIONARY_URL,
        languages: [avatarLanguage],
        voices: [avatarVoice],
      });

      headtts.onstart = () => {
        setStatus("Talking...", "speaking");
      };

      headtts.onend = () => {
        setStatus("Talking head ready", "ready");
      };

      headtts.onerror = (error) => {
        console.error("HeadTTS error:", error);
        setStatus("Avatar voice hit an error", "error");
        setNote("Falling back to the standard voice when the browser-side avatar is unavailable.");
      };

      headtts.onmessage = (message) => {
        if (message.type === "audio") {
          try {
            head.speakAudio(message.data);
          } catch (error) {
            console.error("TalkingHead speakAudio failed:", error);
            setStatus("Avatar playback failed", "error");
          }
          return;
        }

        if (message.type === "error") {
          console.error("HeadTTS synthesis error:", message.data?.error || message.data);
          setStatus("Avatar voice could not speak", "error");
        }
      };

      await headtts.connect(
        null,
        (progress) => {
          const loaded = Number(progress.loaded || 0);
          const total = Number(progress.total || 0);
          if (loaded > 0 && total > 0) {
            const pct = Math.min(99, Math.round((loaded / total) * 100));
            setStatus(`Loading avatar voice... ${pct}%`, "loading");
          } else {
            setStatus("Loading avatar voice...", "loading");
          }
        }
      );
      await headtts.setup({
        voice: avatarVoice,
        language: avatarLanguage,
        speed: 1,
        audioEncoding: "wav",
      });

      ready = true;
      hidePlaceholder();
      setStatus("Talking head ready", "ready");
      setNote("Desktop Chrome or Edge works best. Until the avatar is ready, KidsChat uses its standard voice.");
      return true;
    } catch (error) {
      console.error("Talking head initialization failed:", error);
      ready = false;
      head = null;
      headtts = null;
      setStatus("Avatar unavailable", "error");
      setNote("Using the standard voice instead. Browser-side WebGPU or the remote avatar/model assets may be unavailable.");
      showPlaceholder("Avatar unavailable");
      return false;
    } finally {
      initPromise = null;
    }
  })();

  return initPromise;
}

function warmupAvatar() {
  if (!enabled || ready || initPromise) return;
  void initAvatar();
}

function enqueueSpeech(payload) {
  if (!enabled || !ready || !headtts) {
    return false;
  }

  const speechText = typeof payload === "string" ? payload : payload?.speechText;
  const phoneticText =
    typeof payload === "string" ? null : payload?.phoneticText || null;
  const inputType =
    typeof payload === "string" ? "speech" : payload?.inputType || (phoneticText ? "phonetic" : "speech");
  const displayText =
    typeof payload === "string" ? payload : payload?.displayText || speechText;

  const speakValue = phoneticText || speechText;

  if (!speakValue || !speakValue.trim()) {
    return false;
  }

  if (head?.audioCtx?.state === "suspended") {
    head.audioCtx.resume().catch((error) => {
      console.warn("TalkingHead audio context resume failed:", error);
    });
  }

  headtts
    .synthesize({
      input: [
        {
          type: inputType,
          value: speakValue,
          subtitles: displayText,
        },
      ],
    })
    .catch((error) => {
      console.error("HeadTTS synthesize failed:", error);
      setStatus("Avatar voice could not speak", "error");
    });

  return true;
}

if (toggleBtn) {
  updateToggle();
  toggleBtn.addEventListener("click", () => {
    enabled = !enabled;
    updateToggle();
    if (enabled) {
      setStatus(
        ready ? "Talking head ready" : "Loading avatar and voice...",
        ready ? "ready" : "loading"
      );
      warmupAvatar();
    } else {
      setStatus("Avatar voice off", "idle");
      setNote("KidsChat will keep using its standard voice.");
    }
  });
}

window.kidschatAvatar = {
  enqueueSpeech,
};

warmupAvatar();
