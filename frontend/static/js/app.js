/* ==========================================================
   KidsChat — Frontend Client
   WebSocket connection, audio recording, message rendering
   ========================================================== */

(() => {
  "use strict";

  // ---- DOM refs ----
  const chatArea    = document.getElementById("chat-area");
  const messagesEl  = document.getElementById("messages");
  const textInput   = document.getElementById("text-input");
  const sendBtn     = document.getElementById("send-btn");
  const micBtn      = document.getElementById("mic-btn");
  const cameraBtn   = document.getElementById("camera-btn");
  const connDot     = document.getElementById("connection-dot");
  const connText    = document.getElementById("connection-text");
  const srcBadge    = document.getElementById("source-badge");
  const cameraModal = document.getElementById("camera-modal");
  const cameraPreview = document.getElementById("camera-preview");
  const cameraStill = document.getElementById("camera-still");
  const cameraHelp = document.getElementById("camera-help");
  const cameraPrompt = document.getElementById("camera-prompt");
  const cameraCloseBtn = document.getElementById("camera-close-btn");
  const cameraCaptureBtn = document.getElementById("camera-capture-btn");
  const cameraRetakeBtn = document.getElementById("camera-retake-btn");
  const cameraSendBtn = document.getElementById("camera-send-btn");
  const cameraUiReady = Boolean(
    cameraBtn &&
    cameraModal &&
    cameraPreview &&
    cameraStill &&
    cameraHelp &&
    cameraPrompt &&
    cameraCloseBtn &&
    cameraCaptureBtn &&
    cameraRetakeBtn &&
    cameraSendBtn
  );

  // ---- State ----
  let ws = null;
  let isRecording = false;
  let mediaRecorder = null;
  let mediaStream = null;
  let audioChunks = [];
  let audioContext = null;
  let isMicHeld = false;
  let recordingStartPromise = null;
  let welcomeVisible = true;
  let pingTimerId = null;
  let suppressNextServerAudio = false;
  let cameraStream = null;
  let capturedImageDataUrl = "";

  // ---- WebSocket ----
  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws/chat`);

    ws.onopen = () => {
      setConnectionStatus("connected", "Connected");

      if (pingTimerId) {
        clearInterval(pingTimerId);
      }

      // Keepalive ping every 30s
      pingTimerId = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }));
        }
      }, 30000);
    };

    ws.onmessage = (evt) => {
      const msg = JSON.parse(evt.data);
      handleServerMessage(msg);
    };

    ws.onclose = () => {
      if (pingTimerId) {
        clearInterval(pingTimerId);
        pingTimerId = null;
      }
      setConnectionStatus("error", "Disconnected — reconnecting...");
      setTimeout(connect, 2000);
    };

    ws.onerror = () => {
      setConnectionStatus("error", "Connection error");
    };
  }

  function setConnectionStatus(state, text) {
    connDot.className = `dot dot-${state}`;
    connText.textContent = text;
  }

  function send(msg) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg));
    }
  }

  // ---- Handle incoming messages ----
  let currentBotBubble = null;
  let currentImages = [];

  function handleServerMessage(msg) {
    switch (msg.type) {

      case "status":
        showStatus(msg.content);
        break;

      case "server_state":
        setConnectionStatus(msg.content.state, msg.content.text);
        break;

      case "source":
        showSource(msg.content);
        break;

      case "user_transcript":
        // The server echoes what it heard
        addMessage("user", msg.content);
        break;

      case "text":
        removeStatus();
        addMessage("bot", msg.content);
        break;

      case "image":
        removeStatus();
        addImage(msg.content);
        break;

      case "diagram":
        removeStatus();
        addDiagram(msg.content);
        break;

      case "svg":
        removeStatus();
        addSvg(msg.content);
        break;

      case "sound":
        removeStatus();
        addSound(msg.content);
        break;

      case "speech":
        suppressNextServerAudio = Boolean(
          window.kidschatAvatar?.enqueueSpeech?.(msg.content)
        );
        break;

      case "audio":
        if (suppressNextServerAudio) {
          suppressNextServerAudio = false;
          break;
        }
        if (msg.content) playAudio(msg.content);
        break;

      case "done":
        suppressNextServerAudio = false;
        currentBotBubble = null;
        currentImages = [];
        break;

      case "pong":
        break;
    }
  }

  // ---- Render helpers ----
  function hideWelcome() {
    if (!welcomeVisible) return;
    const w = document.querySelector(".welcome-message");
    if (w) {
      w.style.opacity = "0";
      w.style.transform = "translateY(-20px)";
      w.style.transition = "all 0.3s ease";
      setTimeout(() => w.remove(), 300);
    }
    welcomeVisible = false;
  }

  function addMessage(role, text) {
    hideWelcome();

    const wrapper = document.createElement("div");
    wrapper.className = `message ${role}`;

    const avatar = document.createElement("div");
    avatar.className = "message-avatar";
    avatar.textContent = role === "user" ? "😊" : "🤖";

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.innerHTML = renderMarkdown(text);

    wrapper.appendChild(avatar);
    wrapper.appendChild(bubble);
    messagesEl.appendChild(wrapper);

    if (role === "bot") {
      currentBotBubble = bubble;
    }

    scrollToBottom();
  }

  function addVisionMessage(imageDataUrl, prompt) {
    hideWelcome();

    const wrapper = document.createElement("div");
    wrapper.className = "message user";

    const avatar = document.createElement("div");
    avatar.className = "message-avatar";
    avatar.textContent = "😊";

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";

    const promptText = document.createElement("div");
    promptText.className = "message-vision-prompt";
    promptText.innerHTML = renderMarkdown(prompt || "What do you see in this picture?");
    bubble.appendChild(promptText);

    const img = document.createElement("img");
    img.className = "message-vision-image";
    img.src = imageDataUrl;
    img.alt = "Captured picture";
    bubble.appendChild(img);

    wrapper.appendChild(avatar);
    wrapper.appendChild(bubble);
    messagesEl.appendChild(wrapper);
    scrollToBottom();
  }

  function ensureBotBubble() {
    if (currentBotBubble) return currentBotBubble;

    const wrapper = document.createElement("div");
    wrapper.className = "message bot";

    const avatar = document.createElement("div");
    avatar.className = "message-avatar";
    avatar.textContent = "🤖";

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";

    wrapper.appendChild(avatar);
    wrapper.appendChild(bubble);
    messagesEl.appendChild(wrapper);
    currentBotBubble = bubble;
    return bubble;
  }

  function addImage(imgData) {
    hideWelcome();

    // Create or find the latest bot message to attach images to
    let container;
    const bubble = ensureBotBubble();
    container = bubble.querySelector(".message-images");
    if (!container) {
      container = document.createElement("div");
      container.className = "message-images";
      bubble.appendChild(container);
    }

    const img = document.createElement("img");
    img.src = imgData.url;
    img.alt = imgData.alt || "Image";
    img.loading = "lazy";
    img.onerror = () => { img.style.display = "none"; };
    // Click to open full size
    img.onclick = () => window.open(imgData.url, "_blank");

    container.appendChild(img);
    scrollToBottom();
  }

  async function addDiagram(mermaidCode) {
    hideWelcome();

    const bubble = ensureBotBubble();

    const diagramDiv = document.createElement("div");
    diagramDiv.className = "diagram-container";

    // Render Mermaid diagram
    const id = `mermaid-${Date.now()}`;
    try {
      const { svg } = await mermaid.render(id, mermaidCode);
      diagramDiv.innerHTML = svg;
    } catch (err) {
      console.warn("Mermaid render failed:", err);
      diagramDiv.innerHTML = `<pre style="font-size:0.85rem; color:#636e72;">${escapeHtml(mermaidCode)}</pre>`;
    }

    bubble.appendChild(diagramDiv);

    scrollToBottom();
  }

  function addSvg(svgData) {
    hideWelcome();

    const bubble = ensureBotBubble();
    const pictureDiv = document.createElement("div");
    pictureDiv.className = "picture-container";

    if (svgData && typeof svgData.svg === "string" && svgData.svg.includes("<svg")) {
      pictureDiv.innerHTML = svgData.svg;
    } else {
      pictureDiv.innerHTML = `<pre style="font-size:0.85rem; color:#636e72;">${escapeHtml(String(svgData?.svg || ""))}</pre>`;
    }

    const svgEl = pictureDiv.querySelector("svg");
    if (svgEl) {
      svgEl.setAttribute("preserveAspectRatio", svgEl.getAttribute("preserveAspectRatio") || "xMidYMid meet");
    }

    bubble.appendChild(pictureDiv);
    scrollToBottom();
  }

  function addSound(soundData) {
    hideWelcome();

    const bubble = ensureBotBubble();
    const soundDiv = document.createElement("div");
    soundDiv.className = "sound-container";

    const label = document.createElement("div");
    label.className = "sound-title";
    label.textContent = soundData?.title || "Sound clip";
    soundDiv.appendChild(label);

    const audio = document.createElement("audio");
    audio.className = "sound-player";
    audio.controls = true;
    audio.preload = "metadata";
    audio.src = soundData?.url || "";
    soundDiv.appendChild(audio);

    audio.addEventListener("error", () => {
      if (soundDiv.querySelector(".sound-error")) return;
      const error = document.createElement("div");
      error.className = "sound-error";
      error.textContent = "This sound clip could not be loaded.";
      soundDiv.appendChild(error);
    });

    if (soundData?.credit) {
      const credit = document.createElement("div");
      credit.className = "sound-credit";
      credit.textContent = `Source: ${soundData.credit}`;
      soundDiv.appendChild(credit);
    }

    if (soundData?.page_url) {
      const link = document.createElement("a");
      link.className = "sound-link";
      link.href = soundData.page_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Open source page";
      soundDiv.appendChild(link);
    }

    bubble.appendChild(soundDiv);
    scrollToBottom();

    if (soundData?.autoplay !== false && audio.src) {
      audio.play().catch((err) => {
        console.warn("Sound autoplay blocked:", err);
      });
    }
  }

  function showStatus(text) {
    removeStatus();
    const el = document.createElement("div");
    el.className = "status-msg";
    el.id = "current-status";
    el.innerHTML = `${text}<span class="dots"></span>`;
    messagesEl.appendChild(el);
    scrollToBottom();
  }

  function removeStatus() {
    const el = document.getElementById("current-status");
    if (el) el.remove();
  }

  function showSource(source) {
    srcBadge.classList.remove("hidden", "local", "cloud");
    if (source === "local" || source === "cloud:local_fallback") {
      srcBadge.textContent = "⚡ Local";
      srcBadge.classList.add("local");
    } else {
      const provider = source.replace("cloud:", "");
      srcBadge.textContent = `☁️ ${provider}`;
      srcBadge.classList.add("cloud");
    }
    // Auto-hide after 5s
    setTimeout(() => srcBadge.classList.add("hidden"), 5000);
  }

  function scrollToBottom() {
    requestAnimationFrame(() => {
      chatArea.scrollTop = chatArea.scrollHeight;
    });
  }

  // Simple markdown rendering (bold, italic, line breaks)
  function renderMarkdown(text) {
    return escapeHtml(text)
      .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.*?)\*/g, "<em>$1</em>")
      .replace(/\n/g, "<br>");
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ---- Audio playback ----
  async function playAudio(base64Wav) {
    try {
      const bytes = base64ToBytes(base64Wav);
      const ctx = await ensureAudioContext();

      if (ctx) {
        try {
          const wavBuffer = bytes.buffer.slice(
            bytes.byteOffset,
            bytes.byteOffset + bytes.byteLength
          );
          const decoded = await ctx.decodeAudioData(wavBuffer);
          const source = ctx.createBufferSource();
          source.buffer = decoded;
          source.connect(ctx.destination);
          source.start(0);
          return;
        } catch (err) {
          console.warn("Web Audio playback failed, falling back to <audio>:", err);
        }
      }

      const blob = new Blob([bytes], { type: "audio/wav" });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.volume = 0.8;
      audio.play().catch((e) => console.warn("Audio play blocked:", e));
      audio.onended = () => URL.revokeObjectURL(url);
    } catch (e) {
      console.warn("Audio playback error:", e);
    }
  }

  // ---- Audio recording (mic) ----
  async function startRecording() {
    if (isRecording || recordingStartPromise) return;

    if (!navigator.mediaDevices?.getUserMedia) {
      showTemporaryStatus("This browser does not support microphone access.");
      return;
    }

    if (typeof MediaRecorder === "undefined") {
      showTemporaryStatus("This browser does not support voice recording.");
      return;
    }

    recordingStartPromise = (async () => {
    try {
      await ensureAudioContext({ resume: true });

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });

      if (!isMicHeld) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }

      mediaStream = stream;
      audioChunks = [];

      const mimeType = getSupportedMimeType();
      mediaRecorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunks.push(e.data);
      };

      mediaRecorder.onerror = (e) => {
        console.warn("MediaRecorder error:", e);
        cleanupRecording();
        showTemporaryStatus("Microphone recording failed. Please try again.");
      };

      mediaRecorder.onstop = async () => {
        const recorderMimeType = mediaRecorder?.mimeType || mimeType || "application/octet-stream";
        const chunks = audioChunks;
        cleanupRecording();

        if (chunks.length === 0) {
          showTemporaryStatus("I didn't hear anything. Try holding the mic a bit longer.");
          return;
        }

        showStatus("Sending your voice message...");

        try {
          const blob = new Blob(chunks, { type: recorderMimeType });
          const audioPayload = await blobToUploadPayload(blob);

          send({
            type: "audio",
            data: audioPayload.base64,
            sampleRate: audioPayload.sampleRate,
            mimeType: audioPayload.mimeType,
          });
        } catch (err) {
          console.error("Audio upload preparation failed:", err);
          showTemporaryStatus("I couldn't send that recording. Please try again.");
        }
      };

      mediaRecorder.start();
      isRecording = true;
      setMicVisualState(true);
      showStatus("Recording... release the mic button to send");
    } catch (err) {
      console.error("Mic access denied:", err);
      cleanupRecording();
      showTemporaryStatus("Please allow microphone access to use voice input.");
    } finally {
      recordingStartPromise = null;
    }
    })();

    return recordingStartPromise;
  }

  function stopRecording() {
    isMicHeld = false;

    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      try {
        mediaRecorder.requestData();
      } catch (err) {
        console.warn("requestData failed:", err);
      }
      mediaRecorder.stop();
    }
    setMicVisualState(false);
  }

  function getSupportedMimeType() {
    if (typeof MediaRecorder === "undefined") return "";
    const types = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
    for (const t of types) {
      if (MediaRecorder.isTypeSupported(t)) return t;
    }
    return "";
  }

  async function blobToUploadPayload(blob) {
    // Decode audio blob to PCM using Web Audio API, then package as WAV.
    const ctx = await ensureAudioContext();

    const arrayBuffer = await blob.arrayBuffer();
    if (!ctx) {
      return {
        base64: arrayBufferToBase64(arrayBuffer),
        sampleRate: 16000,
        mimeType: blob.type || "application/octet-stream",
      };
    }

    try {
      const audioBuffer = await ctx.decodeAudioData(arrayBuffer.slice(0));
      const wavBuffer = await audioBufferToWav(audioBuffer, 16000);
      return {
        base64: arrayBufferToBase64(wavBuffer),
        sampleRate: 16000,
        mimeType: "audio/wav",
      };
    } catch (err) {
      console.warn("Audio decode failed, sending original blob:", err);
      return {
        base64: arrayBufferToBase64(arrayBuffer),
        sampleRate: 16000,
        mimeType: blob.type || "application/octet-stream",
      };
    }
  }

  async function audioBufferToWav(audioBuffer, targetSampleRate) {
    const mono = mixToMono(audioBuffer);
    const float32 = audioBuffer.sampleRate === targetSampleRate
      ? mono
      : resampleFloat32(mono, audioBuffer.sampleRate, targetSampleRate);

    return encodeWav(float32, targetSampleRate);
  }

  function mixToMono(audioBuffer) {
    const channelCount = audioBuffer.numberOfChannels || 1;
    if (channelCount === 1) {
      return new Float32Array(audioBuffer.getChannelData(0));
    }

    const mono = new Float32Array(audioBuffer.length);
    for (let channel = 0; channel < channelCount; channel++) {
      const channelData = audioBuffer.getChannelData(channel);
      for (let i = 0; i < channelData.length; i++) {
        mono[i] += channelData[i] / channelCount;
      }
    }
    return mono;
  }

  function resampleFloat32(samples, sourceRate, targetRate) {
    if (sourceRate === targetRate) {
      return new Float32Array(samples);
    }

    const ratio = sourceRate / targetRate;
    const targetLength = Math.max(1, Math.round(samples.length / ratio));
    const output = new Float32Array(targetLength);

    for (let i = 0; i < targetLength; i++) {
      const sourceIndex = i * ratio;
      const leftIndex = Math.floor(sourceIndex);
      const rightIndex = Math.min(leftIndex + 1, samples.length - 1);
      const mix = sourceIndex - leftIndex;
      output[i] = samples[leftIndex] + (samples[rightIndex] - samples[leftIndex]) * mix;
    }

    return output;
  }

  function encodeWav(float32, sampleRate) {
    const bytesPerSample = 2;
    const dataLength = float32.length * bytesPerSample;
    const buffer = new ArrayBuffer(44 + dataLength);
    const view = new DataView(buffer);

    writeAscii(view, 0, "RIFF");
    view.setUint32(4, 36 + dataLength, true);
    writeAscii(view, 8, "WAVE");
    writeAscii(view, 12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * bytesPerSample, true);
    view.setUint16(32, bytesPerSample, true);
    view.setUint16(34, 16, true);
    writeAscii(view, 36, "data");
    view.setUint32(40, dataLength, true);

    let offset = 44;
    for (let i = 0; i < float32.length; i++) {
      const sample = Math.max(-1, Math.min(1, float32[i]));
      view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7FFF, true);
      offset += bytesPerSample;
    }

    return buffer;
  }

  function writeAscii(view, offset, text) {
    for (let i = 0; i < text.length; i++) {
      view.setUint8(offset + i, text.charCodeAt(i));
    }
  }

  function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let i = 0; i < bytes.length; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
  }

  function base64ToBytes(base64) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
  }

  async function ensureAudioContext({ resume = false } = {}) {
    const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextCtor) return null;

    if (!audioContext) {
      audioContext = new AudioContextCtor();
    }

    if (resume && audioContext.state === "suspended") {
      try {
        await audioContext.resume();
      } catch (err) {
        console.warn("AudioContext resume failed:", err);
      }
    }

    return audioContext;
  }

  function cleanupRecording() {
    if (mediaStream) {
      mediaStream.getTracks().forEach((t) => t.stop());
      mediaStream = null;
    }
    mediaRecorder = null;
    audioChunks = [];
    isRecording = false;
    setMicVisualState(false);
  }

  function setMicVisualState(recording) {
    isRecording = recording;
    micBtn.classList.toggle("recording", recording);
    micBtn.setAttribute("aria-pressed", recording ? "true" : "false");
  }

  function showTemporaryStatus(text, delayMs = 2500) {
    showStatus(text);
    window.setTimeout(() => {
      const currentStatus = document.getElementById("current-status");
      if (currentStatus && currentStatus.textContent.includes(text)) {
        removeStatus();
      }
    }, delayMs);
  }

  // ---- Camera / still image capture ----
  async function openCameraModal() {
    if (!cameraUiReady) {
      showTemporaryStatus("The picture tool is still loading. Please refresh the page.");
      return;
    }

    stopCameraStream();
    resetCameraCapture();
    cameraModal.classList.remove("hidden");
    cameraModal.setAttribute("aria-hidden", "false");
    cameraHelp.textContent = "Take one picture, then ask what is in it.";
    cameraCaptureBtn.disabled = false;
    cameraCaptureBtn.textContent = "Capture";

    if (!navigator.mediaDevices?.getUserMedia) {
      cameraHelp.textContent = "Camera access is not available here. Try opening KidsChat on localhost in Chrome or Edge and allow camera permission.";
      cameraCaptureBtn.disabled = true;
      cameraPrompt.focus();
      cameraPrompt.select();
      return;
    }

    try {
      cameraStream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: "user",
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      });
      cameraPreview.srcObject = cameraStream;
      await cameraPreview.play();
      cameraPrompt.focus();
      cameraPrompt.select();
    } catch (err) {
      console.error("Camera access failed:", err);
      cameraHelp.textContent = "I could not start the camera. Please allow camera access in your browser, then try again.";
      cameraCaptureBtn.disabled = true;
      cameraCaptureBtn.textContent = "Camera Blocked";
      cameraPrompt.focus();
      cameraPrompt.select();
    }
  }

  function stopCameraStream() {
    if (!cameraUiReady) return;
    if (!cameraStream) return;
    cameraStream.getTracks().forEach((track) => track.stop());
    cameraStream = null;
    cameraPreview.srcObject = null;
  }

  function resetCameraCapture() {
    if (!cameraUiReady) return;
    capturedImageDataUrl = "";
    cameraPreview.classList.remove("hidden");
    cameraStill.classList.add("hidden");
    cameraStill.removeAttribute("src");
    cameraHelp.textContent = "Take one picture, then ask what is in it.";
    cameraCaptureBtn.classList.remove("hidden");
    cameraCaptureBtn.disabled = false;
    cameraCaptureBtn.textContent = "Capture";
    cameraRetakeBtn.classList.add("hidden");
    cameraSendBtn.classList.add("hidden");
  }

  function closeCameraModal() {
    if (!cameraUiReady) return;
    stopCameraStream();
    resetCameraCapture();
    cameraModal.classList.add("hidden");
    cameraModal.setAttribute("aria-hidden", "true");
  }

  function captureCameraStill() {
    if (!cameraUiReady) return;
    if (!cameraPreview.videoWidth || !cameraPreview.videoHeight) {
      showTemporaryStatus("The camera is not ready yet. Please try again.");
      return;
    }

    const canvas = document.createElement("canvas");
    canvas.width = cameraPreview.videoWidth;
    canvas.height = cameraPreview.videoHeight;

    const ctx = canvas.getContext("2d");
    ctx.drawImage(cameraPreview, 0, 0, canvas.width, canvas.height);

    capturedImageDataUrl = canvas.toDataURL("image/jpeg", 0.9);
    cameraStill.src = capturedImageDataUrl;
    cameraStill.classList.remove("hidden");
    cameraPreview.classList.add("hidden");
    cameraCaptureBtn.classList.add("hidden");
    cameraRetakeBtn.classList.remove("hidden");
    cameraSendBtn.classList.remove("hidden");
    cameraHelp.textContent = "Looks good? Send it, or retake the picture.";
    stopCameraStream();
  }

  async function retakeCameraStill() {
    if (!cameraUiReady) return;
    try {
      await openCameraModal();
    } catch (err) {
      console.error("Camera retake failed:", err);
    }
  }

  function dataUrlToBase64(dataUrl) {
    const parts = String(dataUrl || "").split(",", 2);
    return parts.length === 2 ? parts[1] : "";
  }

  async function sendVisionMessage() {
    if (!cameraUiReady) {
      showTemporaryStatus("The picture tool is still loading. Please refresh the page.");
      return;
    }
    if (!capturedImageDataUrl) {
      showTemporaryStatus("Take a picture first.");
      return;
    }

    const prompt = cameraPrompt.value.trim() || "What do you see in this picture?";
    const base64 = dataUrlToBase64(capturedImageDataUrl);
    if (!base64) {
      showTemporaryStatus("I couldn't prepare that picture. Please try again.");
      return;
    }

    ensureAudioContext({ resume: true }).catch((err) => {
      console.warn("Audio unlock failed:", err);
    });
    addVisionMessage(capturedImageDataUrl, prompt);
    send({
      type: "vision",
      content: prompt,
      data: base64,
      mimeType: "image/jpeg",
    });
    closeCameraModal();
  }

  // ---- Event listeners ----

  // Text send
  function sendText() {
    const text = textInput.value.trim();
    if (!text) return;
    ensureAudioContext({ resume: true }).catch((err) => {
      console.warn("Audio unlock failed:", err);
    });
    addMessage("user", text);
    send({ type: "text", content: text });
    textInput.value = "";
  }

  sendBtn.addEventListener("click", sendText);
  textInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendText();
    }
  });

  // Mic — hold to record
  function handleMicPressStart(e) {
    e.preventDefault();
    isMicHeld = true;
    if (typeof micBtn.setPointerCapture === "function" && e.pointerId !== undefined) {
      try {
        micBtn.setPointerCapture(e.pointerId);
      } catch (err) {
        console.warn("Pointer capture failed:", err);
      }
    }
    startRecording();
  }

  function handleMicPressEnd(e) {
    e.preventDefault();
    stopRecording();
    if (typeof micBtn.releasePointerCapture === "function" && e.pointerId !== undefined) {
      try {
        micBtn.releasePointerCapture(e.pointerId);
      } catch (err) {
        console.warn("Pointer release failed:", err);
      }
    }
  }

  if (window.PointerEvent) {
    micBtn.addEventListener("pointerdown", handleMicPressStart);
    micBtn.addEventListener("pointerup", handleMicPressEnd);
    micBtn.addEventListener("pointercancel", handleMicPressEnd);
    micBtn.addEventListener("lostpointercapture", () => {
      if (isRecording) stopRecording();
      isMicHeld = false;
    });
  } else {
    micBtn.addEventListener("mousedown", handleMicPressStart);
    micBtn.addEventListener("mouseup", handleMicPressEnd);
    micBtn.addEventListener("mouseleave", () => {
      if (isRecording) stopRecording();
      isMicHeld = false;
    });
    micBtn.addEventListener("touchstart", handleMicPressStart);
    micBtn.addEventListener("touchend", handleMicPressEnd);
    micBtn.addEventListener("touchcancel", handleMicPressEnd);
  }

  micBtn.addEventListener("keydown", (e) => {
    if ((e.key === " " || e.key === "Enter") && !e.repeat) {
      handleMicPressStart(e);
    }
  });
  micBtn.addEventListener("keyup", (e) => {
    if (e.key === " " || e.key === "Enter") {
      handleMicPressEnd(e);
    }
  });
  micBtn.addEventListener("blur", () => {
    if (isRecording) stopRecording();
    isMicHeld = false;
  });
  micBtn.addEventListener("contextmenu", (e) => e.preventDefault());

  // Camera capture
  if (cameraUiReady) {
    cameraBtn.addEventListener("click", () => {
      openCameraModal().catch((err) => {
        console.error("Camera modal failed to open:", err);
        showTemporaryStatus("I couldn't open the camera just now.");
      });
    });

    cameraCloseBtn.addEventListener("click", closeCameraModal);
    cameraCaptureBtn.addEventListener("click", captureCameraStill);
    cameraRetakeBtn.addEventListener("click", () => {
      retakeCameraStill().catch((err) => {
        console.error("Camera retake failed:", err);
        showTemporaryStatus("I couldn't restart the camera just now.");
      });
    });
    cameraSendBtn.addEventListener("click", sendVisionMessage);
    cameraPrompt.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && capturedImageDataUrl) {
        e.preventDefault();
        sendVisionMessage();
      }
      if (e.key === "Escape") {
        e.preventDefault();
        closeCameraModal();
      }
    });
    cameraModal.addEventListener("click", (e) => {
      if (e.target === cameraModal) {
        closeCameraModal();
      }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !cameraModal.classList.contains("hidden")) {
        closeCameraModal();
      }
    });
  }

  // Suggestion chips
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const msg = chip.dataset.msg;
      addMessage("user", msg);
      send({ type: "text", content: msg });
    });
  });

  // ---- Init ----
  connect();
})();
