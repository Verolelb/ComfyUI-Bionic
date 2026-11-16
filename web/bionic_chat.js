import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_TYPE = "BionicChatPrompt";
const MAX_IMAGES = 6;
const MAX_IMAGE_SIDE = 1280;

const state = {
  config: null,
  models: [],
  messages: [],
  attachments: [],
  busy: false,
  abort: null,
  loaded: false,
  targetNodeId: null,
  recording: false,
  recorder: null,
  recStream: null,
  recChunks: [],
  recTimer: null,
  recStart: 0,
  ui: null,
  els: null,
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function setStatus(text) {
  if (state.els) state.els.status.textContent = text || "";
}

function toast(severity, summary) {
  const manager = app.extensionManager;
  if (manager && manager.toast && typeof manager.toast.add === "function") {
    manager.toast.add({ severity, summary, life: 4000 });
    return;
  }
  setStatus(summary);
}

function loadStylesheet() {
  if (document.getElementById("bionic-chat-style")) return;
  const link = document.createElement("link");
  link.id = "bionic-chat-style";
  link.rel = "stylesheet";
  link.href = new URL("./bionic_chat.css", import.meta.url).href;
  document.head.appendChild(link);
}

function buildPanel() {
  if (document.getElementById("bionic-chat-root")) {
    state.els = collectElements();
    return;
  }

  const root = el("div");
  root.id = "bionic-chat-root";

  const launcher = el("button", null, "💬 Bionic");
  launcher.id = "bionic-launcher";
  launcher.type = "button";
  launcher.title = "Ouvrir le chat Bionic";

  const panel = el("section");
  panel.id = "bionic-panel";
  panel.className = "bionic-hidden";
  panel.innerHTML = `
    <header class="bionic-header">
      <span class="bionic-title">Bionic<span>.</span></span>
      <div class="bionic-header-btns">
        <button type="button" class="bionic-icon-btn" id="bionic-settings-btn" title="Réglages">⚙</button>
        <button type="button" class="bionic-icon-btn" id="bionic-new" title="Nouvelle conversation">＋</button>
        <button type="button" class="bionic-icon-btn" id="bionic-close" title="Fermer">✕</button>
      </div>
    </header>
    <div class="bionic-model-row">
      <select id="bionic-model" title="Modèle LM Studio"></select>
    </div>
    <div id="bionic-messages"></div>
    <div id="bionic-attachments"></div>
    <div class="bionic-status" id="bionic-status"></div>
    <div class="bionic-composer">
      <textarea id="bionic-input" rows="2" placeholder="Écris ton prompt… (Entrée = envoyer, Maj+Entrée = nouvelle ligne)"></textarea>
      <div class="bionic-tools">
        <button type="button" class="bionic-icon-btn" id="bionic-mic" title="Entrée audio (Voxtral/Whisper local)">🎙</button>
        <button type="button" class="bionic-icon-btn" id="bionic-attach" title="Joindre une image">🖼</button>
        <input type="file" id="bionic-file" accept="image/*" multiple hidden>
        <span class="bionic-rec-time" id="bionic-rec-time"></span>
        <span class="bionic-spacer"></span>
        <button type="button" class="bionic-btn bionic-run" id="bionic-run" title="Envoyer le texte dans la node Bionic Chat Prompt et lancer le workflow">⚡ Run</button>
        <button type="button" class="bionic-btn bionic-send" id="bionic-send">Envoyer</button>
      </div>
    </div>
    <div id="bionic-settings" class="bionic-hidden">
      <div class="bionic-settings-title">Réglages</div>
      <label>Serveur LM Studio (OpenAI compatible)
        <input id="bionic-cfg-url" type="text" spellcheck="false">
      </label>
      <label>Prompt système
        <textarea id="bionic-cfg-system" spellcheck="false"></textarea>
      </label>
      <label>Température
        <input id="bionic-cfg-temp" type="number" min="0" max="2" step="0.05">
      </label>
      <label>Modèle de transcription audio
        <select id="bionic-cfg-whisper">
          <option value="tiny">tiny (rapide, ~75 Mo)</option>
          <option value="base">base (~145 Mo)</option>
          <option value="small">small (recommandé, ~480 Mo)</option>
          <option value="medium">medium (~1,5 Go)</option>
          <option value="large-v3">large-v3 (~3 Go)</option>
        </select>
      </label>
      <label>Langue de la transcription
        <select id="bionic-cfg-language">
          <option value="fr">Français</option>
          <option value="en">Anglais</option>
          <option value="auto">Détection automatique</option>
          <option value="es">Espagnol</option>
          <option value="de">Allemand</option>
          <option value="it">Italien</option>
        </select>
      </label>
      <div class="bionic-settings-actions">
        <button type="button" class="bionic-btn bionic-send" id="bionic-cfg-save">Enregistrer</button>
        <button type="button" class="bionic-btn" id="bionic-cfg-close">Fermer</button>
      </div>
    </div>
  `;

  root.append(launcher, panel);
  document.body.appendChild(root);
  state.els = collectElements();
  bindEvents();
}

function collectElements() {
  const byId = (id) => document.getElementById(id);
  return {
    root: byId("bionic-chat-root"),
    launcher: byId("bionic-launcher"),
    panel: byId("bionic-panel"),
    messages: byId("bionic-messages"),
    attachments: byId("bionic-attachments"),
    status: byId("bionic-status"),
    input: byId("bionic-input"),
    model: byId("bionic-model"),
    settings: byId("bionic-settings"),
    mic: byId("bionic-mic"),
    recTime: byId("bionic-rec-time"),
    file: byId("bionic-file"),
    send: byId("bionic-send"),
  };
}

function bindEvents() {
  const els = state.els;
  els.launcher.addEventListener("click", openPanel);
  document.getElementById("bionic-close").addEventListener("click", closePanel);
  document.getElementById("bionic-settings-btn").addEventListener("click", openSettings);
  document.getElementById("bionic-cfg-close").addEventListener("click", () => {
    els.settings.classList.add("bionic-hidden");
  });
  document.getElementById("bionic-cfg-save").addEventListener("click", saveSettings);
  document.getElementById("bionic-new").addEventListener("click", newConversation);
  document.getElementById("bionic-attach").addEventListener("click", () => els.file.click());
  els.file.addEventListener("change", () => {
    addImageFiles(els.file.files);
    els.file.value = "";
  });

  els.mic.addEventListener("click", toggleRecording);
  document.getElementById("bionic-run").addEventListener("click", () => runPrompt(els.input.value));
  els.send.addEventListener("click", () => {
    if (state.busy) {
      stopStreaming();
      return;
    }
    sendMessage();
  });

  els.model.addEventListener("change", () => {
    if (!state.config) return;
    state.config.model = els.model.value;
    saveConfig({ model: els.model.value });
  });

  els.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!state.busy) sendMessage();
    }
  });
  els.input.addEventListener("input", autoGrowInput);
  els.input.addEventListener("paste", handlePaste);
  els.panel.addEventListener("paste", handlePaste);

  els.panel.addEventListener("dragover", (event) => {
    event.preventDefault();
    els.panel.classList.add("bionic-drop");
  });
  els.panel.addEventListener("dragleave", () => els.panel.classList.remove("bionic-drop"));
  els.panel.addEventListener("drop", (event) => {
    event.preventDefault();
    els.panel.classList.remove("bionic-drop");
    addImageFiles(event.dataTransfer?.files);
  });
}

function openPanel() {
  state.els.panel.classList.remove("bionic-hidden");
  updateTargetLabel();
  if (!state.loaded) loadConfig();
  setTimeout(() => state.els.input.focus(), 50);
}

function closePanel() {
  state.els.panel.classList.add("bionic-hidden");
}

function openSettings() {
  state.els.settings.classList.remove("bionic-hidden");
  fillSettings();
}

function autoGrowInput() {
  const input = state.els.input;
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
}

async function loadConfig() {
  try {
    const response = await api.fetchApi("/bionic_chat/config");
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    state.config = data.config;
    state.models = data.models || [];
    state.loaded = true;
    if (!state.config.model && state.models.length) {
      state.config.model = state.models[0].id;
    }
    renderModels();
    fillSettings();
    setStatus(
      data.error
        ? `${data.error} — démarre le serveur LM Studio (Developer → Start server).`
        : `${state.models.length} modèle(s) LM Studio`
    );
  } catch (error) {
    setStatus(`LM Studio injoignable : ${error.message || error}`);
  }
}

async function saveConfig(patch) {
  try {
    const response = await api.fetchApi("/bionic_chat/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    state.config = data.config;
    return true;
  } catch (error) {
    toast("error", `Réglages non enregistrés : ${error.message || error}`);
    return false;
  }
}

function fillSettings() {
  if (!state.config || !document.getElementById("bionic-cfg-url")) return;
  document.getElementById("bionic-cfg-url").value = state.config.base_url || "";
  document.getElementById("bionic-cfg-system").value = state.config.system_prompt || "";
  document.getElementById("bionic-cfg-temp").value = state.config.temperature;
  document.getElementById("bionic-cfg-whisper").value = state.config.transcribe_model;
  document.getElementById("bionic-cfg-language").value = state.config.transcribe_language;
}

async function saveSettings() {
  const patch = {
    base_url: document.getElementById("bionic-cfg-url").value.trim(),
    system_prompt: document.getElementById("bionic-cfg-system").value,
    temperature: Number(document.getElementById("bionic-cfg-temp").value),
    transcribe_model: document.getElementById("bionic-cfg-whisper").value,
    transcribe_language: document.getElementById("bionic-cfg-language").value,
  };
  if (await saveConfig(patch)) {
    state.els.settings.classList.add("bionic-hidden");
    await loadConfig();
    toast("success", "Réglages enregistrés");
  }
}

function renderModels() {
  const select = state.els.model;
  select.innerHTML = "";
  if (!state.models.length) {
    select.appendChild(el("option", null, "Aucun modèle LM Studio"));
    select.disabled = true;
    return;
  }
  select.disabled = false;
  for (const model of state.models) {
    if (!["llm", "vlm"].includes(model.type)) continue;
    const option = el("option", null, `${model.id}${model.type === "vlm" ? " (vision)" : ""}`);
    option.value = model.id;
    select.appendChild(option);
  }
  if (state.config?.model) select.value = state.config.model;
}

function newConversation() {
  stopStreaming();
  state.messages = [];
  state.attachments = [];
  renderAttachments();
  renderMessages();
  state.els.input.value = "";
  autoGrowInput();
  setStatus("Nouvelle conversation");
}

function scrollToBottom() {
  const box = state.els.messages;
  box.scrollTop = box.scrollHeight;
}

function imageStrip(images) {
  const strip = el("div", "bionic-message-images");
  for (const image of images) {
    const img = el("img");
    img.src = image;
    img.alt = "pièce jointe";
    strip.appendChild(img);
  }
  return strip;
}

function messageElement(message) {
  const wrap = el("div", `bionic-msg ${message.role}${message.error ? " error" : ""}`);
  const bubble = el("div", "bionic-bubble");
  if (message.images && message.images.length) bubble.appendChild(imageStrip(message.images));

  let reasoning = null;
  if (message.reasoning) {
    reasoning = el("details", "bionic-reasoning");
    reasoning.appendChild(el("summary", null, "Raisonnement"));
    reasoning.appendChild(el("div", null, message.reasoning));
    bubble.appendChild(reasoning);
  }

  const text = el("div", "bionic-text");
  text.textContent = message.content || "";
  if (message.role === "assistant" && state.busy && !message.content) {
    text.classList.add("bionic-typing");
  }
  bubble.appendChild(text);
  wrap.appendChild(bubble);

  let actions = null;
  if (message.role === "assistant" && message.content) {
    actions = el("div", "bionic-message-actions");
    const runButton = el("button", "bionic-link", "⚡ Run");
    runButton.type = "button";
    runButton.addEventListener("click", () => runPrompt(message.content));
    const copyButton = el("button", "bionic-link", "Copier");
    copyButton.type = "button";
    copyButton.addEventListener("click", async () => {
      await navigator.clipboard.writeText(message.content);
      copyButton.textContent = "Copié";
      setTimeout(() => (copyButton.textContent = "Copier"), 1200);
    });
    actions.append(runButton, copyButton);
    if (state.busy) runButton.disabled = true;
    wrap.appendChild(actions);
  }

  return { wrap, text, reasoning, actions };
}

function renderMessages() {
  const box = state.els.messages;
  box.innerHTML = "";
  state.ui = null;
  if (!state.messages.length) {
    const hint = el(
      "div",
      "bionic-empty",
      "Décris ta scène, joins une image ou utilise le micro. Le bouton ⚡ Run envoie le prompt dans la node Bionic Chat Prompt et lance le workflow."
    );
    box.appendChild(hint);
    return;
  }
  for (const message of state.messages) {
    const refs = messageElement(message);
    box.appendChild(refs.wrap);
    state.ui = refs;
  }
  scrollToBottom();
}

function renderAttachments() {
  const box = state.els.attachments;
  box.innerHTML = "";
  state.attachments.forEach((image, index) => {
    const thumb = el("div", "bionic-thumb");
    const img = el("img");
    img.src = image;
    img.alt = "pièce jointe";
    const remove = el("button", null, "×");
    remove.type = "button";
    remove.title = "Retirer";
    remove.addEventListener("click", () => {
      state.attachments.splice(index, 1);
      renderAttachments();
    });
    thumb.append(img, remove);
    box.appendChild(thumb);
  });
}

function toApiMessages() {
  return state.messages
    .filter((message) => message.content || (message.images && message.images.length))
    .map((message) => {
      if (!message.images || !message.images.length) {
        return { role: message.role, content: message.content || "" };
      }
      return {
        role: message.role,
        content: [
          { type: "text", text: message.content || "" },
          ...message.images.map((url) => ({ type: "image_url", image_url: { url } })),
        ],
      };
    });
}

async function sendMessage() {
  if (state.busy) return;
  const text = state.els.input.value.trim();
  if (!text && !state.attachments.length) return;

  state.messages.push({ role: "user", content: text, images: state.attachments.slice() });
  state.attachments = [];
  state.els.input.value = "";
  autoGrowInput();
  renderAttachments();

  const assistant = { role: "assistant", content: "", reasoning: "" };
  state.messages.push(assistant);
  state.busy = true;
  setBusyUi(true);
  renderMessages();
  state.ui = null;

  await streamChat(assistant);

  state.busy = false;
  setBusyUi(false);
  renderMessages();
}

function setBusyUi(busy) {
  const els = state.els;
  els.send.textContent = busy ? "Stop" : "Envoyer";
  els.send.classList.toggle("bionic-run", busy);
  els.send.classList.toggle("bionic-send", !busy);
  els.mic.disabled = busy;
  els.input.placeholder = busy
    ? "Bionic répond…"
    : "Écris ton prompt… (Entrée = envoyer, Maj+Entrée = nouvelle ligne)";
}

function stopStreaming() {
  if (state.abort) state.abort.abort();
}

async function streamChat(assistant) {
  if (!state.config) await loadConfig();
  if (!state.config) {
    assistant.error = true;
    assistant.content = "LM Studio est injoignable. Démarre son serveur local (port 1234).";
    return;
  }

  const controller = new AbortController();
  state.abort = controller;
  let rendered = null;

  try {
    const response = await api.fetchApi("/bionic_chat/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: state.els.model.value || state.config.model,
        messages: toApiMessages(),
        temperature: state.config.temperature,
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      let detail = response.statusText;
      try {
        detail = (await response.json()).error || detail;
      } catch {
        /* keep status text */
      }
      throw new Error(detail);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer = (buffer + decoder.decode(value, { stream: true })).replace(/\r\n/g, "\n");

      let split;
      while ((split = buffer.indexOf("\n\n")) >= 0) {
        const chunk = buffer.slice(0, split);
        buffer = buffer.slice(split + 2);
        if (handleSseChunk(chunk, assistant)) {
          reader.cancel().catch(() => {});
          return;
        }
        rendered = renderStreaming(assistant);
      }
    }
    if (buffer.trim()) handleSseChunk(buffer, assistant);
  } catch (error) {
    if (error.name !== "AbortError") {
      assistant.error = true;
      assistant.content = assistant.content || `Erreur : ${error.message || error}`;
    }
  } finally {
    state.abort = null;
    if (rendered) scrollToBottom();
  }
}

function handleSseChunk(chunk, assistant) {
  for (const rawLine of chunk.split("\n")) {
    const line = rawLine.trim();
    if (!line.startsWith("data:")) continue;
    const data = line.slice(5).trim();
    if (data === "[DONE]") return true;
    let parsed;
    try {
      parsed = JSON.parse(data);
    } catch {
      continue;
    }
    const delta = parsed.choices?.[0]?.delta || {};
    if (delta.reasoning_content) assistant.reasoning += delta.reasoning_content;
    if (delta.content) assistant.content += delta.content;
  }
  return false;
}

function renderStreaming(assistant) {
  if (!state.ui || state.ui.wrap.parentElement !== state.els.messages) {
    renderMessages();
    state.ui = null;
    const last = state.messages[state.messages.length - 1];
    const wrap = state.els.messages.lastElementChild;
    if (!wrap) return null;
    const text = wrap.querySelector(".bionic-text");
    if (text) state.ui = { wrap, text, reasoning: null, actions: null };
    if (last !== assistant) return state.ui;
  }
  if (!state.ui) return null;
  state.ui.text.textContent = assistant.content || "";
  state.ui.text.classList.toggle("bionic-typing", !assistant.content && !assistant.reasoning);
  if (assistant.reasoning && !state.ui.reasoning) {
    const details = el("details", "bionic-reasoning");
    details.appendChild(el("summary", null, "Raisonnement"));
    details.appendChild(el("div", null, assistant.reasoning));
    state.ui.wrap.querySelector(".bionic-bubble").prepend(details);
    state.ui.reasoning = details;
  } else if (state.ui.reasoning) {
    state.ui.reasoning.lastElementChild.textContent = assistant.reasoning;
  }
  scrollToBottom();
  return state.ui;
}

function getReceiverNode() {
  const canvas = app.canvas;
  let selected = [];
  if (canvas?.selectedItems) {
    selected = [...canvas.selectedItems];
  } else if (canvas?.selected_nodes) {
    selected = Object.values(canvas.selected_nodes);
  }
  const selectedReceiver = selected.find((node) => node?.type === NODE_TYPE);
  if (selectedReceiver) return selectedReceiver;
  const nodes = app.graph?._nodes || app.graph?.nodes || [];
  return nodes.find((node) => node.type === NODE_TYPE) || null;
}

function createReceiverNode() {
  const LiteGraph = window.LiteGraph;
  if (!LiteGraph?.createNode) return null;
  const node = LiteGraph.createNode(NODE_TYPE);
  if (!node) return null;
  app.graph.add(node);
  const mouse = app.canvas?.graph_mouse;
  node.pos = mouse && Number.isFinite(mouse[0]) ? [mouse[0], mouse[1]] : [200, 200];
  if (node.setSize) node.setSize([340, 200]);
  node.setDirtyCanvas?.(true, true);
  app.graph.setDirtyCanvas?.(true, true);
  return node;
}

function updateTargetLabel() {
  const node = getReceiverNode();
  state.targetNodeId = node?.id ?? null;
  if (node) {
    setStatus(`Cible : ${node.title || "Bionic Chat Prompt"} (#${node.id})`);
  } else {
    setStatus("Aucune node Bionic Chat Prompt dans le graphe — elle sera créée au premier Run.");
  }
}

async function runPrompt(rawText) {
  const text = (rawText || "").trim();
  if (!text) {
    toast("warning", "Aucun texte à envoyer dans la node.");
    return;
  }
  let node = getReceiverNode();
  if (!node) node = createReceiverNode();
  if (!node) {
    toast("error", "Impossible de créer la node Bionic Chat Prompt.");
    return;
  }
  const widget = node.widgets?.find((entry) => entry.name === "prompt");
  if (!widget) {
    toast("error", "La node Bionic Chat Prompt n'a pas d'entrée prompt.");
    return;
  }
  widget.value = text;
  node.setDirtyCanvas?.(true, true);
  app.graph.setDirtyCanvas?.(true, true);
  updateTargetLabel();

  try {
    await app.queuePrompt(0, 1);
    toast("success", `Prompt envoyé dans #${node.id} — workflow lancé`);
  } catch (error) {
    toast("error", `Lancement impossible : ${error?.message || error}`);
  }
}

async function addImageFiles(fileList) {
  const files = [...(fileList || [])].filter((file) => file.type.startsWith("image/"));
  for (const file of files) {
    if (state.attachments.length >= MAX_IMAGES) {
      toast("warning", `${MAX_IMAGES} images maximum par message.`);
      break;
    }
    try {
      state.attachments.push(await fileToDataUrl(file));
    } catch (error) {
      toast("error", `Image illisible : ${error.message || error}`);
    }
  }
  renderAttachments();
}

function handlePaste(event) {
  const items = event.clipboardData?.items;
  if (!items) return;
  const files = [];
  for (const item of items) {
    if (item.type.startsWith("image/")) {
      const file = item.getAsFile();
      if (file) files.push(file);
    }
  }
  if (files.length) {
    event.preventDefault();
    addImageFiles(files);
  }
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("lecture impossible"));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("format non supporté"));
      img.onload = () => {
        const scale = Math.min(1, MAX_IMAGE_SIDE / Math.max(img.width, img.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(img.width * scale));
        canvas.height = Math.max(1, Math.round(img.height * scale));
        const context = canvas.getContext("2d");
        context.drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL("image/jpeg", 0.88));
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

async function toggleRecording() {
  if (state.recording) {
    state.recorder?.stop();
    return;
  }
  try {
    state.recStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
  } catch (error) {
    toast("error", `Micro indisponible : ${error.message || error}`);
    return;
  }

  const recorder = new MediaRecorder(state.recStream);
  state.recorder = recorder;
  state.recChunks = [];
  recorder.ondataavailable = (event) => {
    if (event.data.size) state.recChunks.push(event.data);
  };
  recorder.onstop = async () => {
    state.recStream?.getTracks().forEach((track) => track.stop());
    state.recStream = null;
    clearInterval(state.recTimer);
    state.recording = false;
    state.els.mic.classList.remove("bionic-active");
    state.els.recTime.textContent = "";
    const blob = new Blob(state.recChunks, { type: recorder.mimeType || "audio/webm" });
    state.recChunks = [];
    if (blob.size > 1200) await transcribeBlob(blob);
  };

  recorder.start();
  state.recording = true;
  state.recStart = Date.now();
  state.els.mic.classList.add("bionic-active");
  state.recTimer = setInterval(() => {
    const seconds = Math.floor((Date.now() - state.recStart) / 1000);
    state.els.recTime.textContent = `● ${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  }, 200);
  setStatus("Enregistrement… clique sur 🎙 pour arrêter");
}

async function transcribeBlob(blob) {
  setStatus("Transcription en cours…");
  try {
    const arrayBuffer = await blob.arrayBuffer();
    const audioContext = new AudioContext();
    const decoded = await audioContext.decodeAudioData(arrayBuffer);
    await audioContext.close();

    const sampleRate = 16000;
    const offline = new OfflineAudioContext(1, Math.max(1, Math.ceil(decoded.duration * sampleRate)), sampleRate);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    const rendered = await offline.startRendering();
    const wav = encodeWav(rendered.getChannelData(0), sampleRate);

    const response = await api.fetchApi("/bionic_chat/transcribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        audio: base64FromArrayBuffer(wav),
        model: state.config?.transcribe_model,
        language: state.config?.transcribe_language,
      }),
    });
    let data = {};
    try {
      data = await response.json();
    } catch {
      /* empty body */
    }
    if (!response.ok) throw new Error(data.error || response.statusText);
    const text = (data.text || "").trim();
    if (!text) {
      setStatus("Rien n'a été transcrit.");
      return;
    }
    const input = state.els.input;
    input.value = input.value ? `${input.value} ${text}` : text;
    autoGrowInput();
    input.focus();
    setStatus("Transcription ajoutée");
  } catch (error) {
    toast("error", `Transcription impossible : ${error.message || error}`);
    setStatus("Transcription impossible");
  }
}

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeString = (offset, value) => {
    for (let i = 0; i < value.length; i += 1) view.setUint8(offset + i, value.charCodeAt(i));
  };
  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    offset += 2;
  }
  return buffer;
}

function base64FromArrayBuffer(arrayBuffer) {
  const bytes = new Uint8Array(arrayBuffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

app.registerExtension({
  name: "Bionic.Chat",
  async setup() {
    loadStylesheet();
    buildPanel();
    state.els.panel.classList.add("bionic-hidden");
    renderMessages();
  },
});
