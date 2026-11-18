# ComfyUI-Bionic

**English** · [Français](README.md)

A Bionic-style chat right inside ComfyUI, connected to any local OpenAI-compatible server (LM Studio, Ollama, llama.cpp), with audio input, vision input, attached documents, a token counter and a receiver node that takes the prompt and runs the workflow.

## Features

- Floating chat panel connected to any local OpenAI-compatible server: LM Studio, Ollama, llama.cpp or a custom address.
- French or English interface, switchable in ⚙ (panel and node).
- Streaming answers, collapsible reasoning, model picker in the panel.
- Vision input: 🖼 button, `Ctrl+V` paste or drag and drop images.
- Documents: ＋ button to attach **PDF**, **DOCX** or text files (TXT, MD, CSV, JSON…), sent to the model as context.
- Audio input: 🎙 button, microphone recording and local transcription (faster-whisper).
- Token counter **cumulative over the whole conversation**, with the prompt / answer breakdown on hover.
- ⏹ button to stop the running answer or the workflow it started.
- ⏏ button to **unload the model** from memory, whatever the server (LM Studio, Ollama, llama.cpp), with an option to unload it automatically after every answer.
- **Bionic Chat Prompt** node: receives the chat prompt and outputs it as a `STRING`.
- `⚡ Run` button: writes the prompt into the node, then runs the workflow, exactly like ComfyUI's Run button.
- Automatic workflow run as soon as the model finishes answering (on by default, can be turned off in ⚙).
- Automatic sending of the audio transcription when the microphone stops (on by default, can be turned off in ⚙).
- Internet access: the model can search the web and open pages to answer. Off by default, enabled with the 🌐 button in the panel (or in ⚙).

## Requirements

- ComfyUI (tested with version 0.45).
- A local OpenAI-compatible server with at least one chat model loaded:
  - **LM Studio**: Developer tab → *Start server*, `http://127.0.0.1:1234/v1`;
  - **Ollama**: `ollama serve`, `http://127.0.0.1:11434/v1`;
  - **llama.cpp**: `llama-server -m model.gguf`, `http://127.0.0.1:9931/v1` (current default port; 8080 on older builds, `--port` to change it).

These three addresses are offered as presets in ⚙, and the field stays free-form.

## Installation

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/Verolelb/ComfyUI-Bionic.git
```

Install the transcription dependency into the Python used by ComfyUI:

```bash
# Windows portable install
../../../python_embeded/python.exe -m pip install -r ComfyUI-Bionic/requirements.txt

# standard install
pip install -r ComfyUI-Bionic/requirements.txt
```

Restart ComfyUI. The `💬 Bionic` button appears in the bottom right corner of the interface.

The Whisper `small` model (~480 MB) is downloaded automatically the first time you use the microphone. Model size and language are set in ⚙.

## Usage

1. Open the panel with `💬 Bionic`, pick your server in ⚙, then a model.
2. Type your prompt, attach images (🖼), documents (＋) or dictate it with the microphone, then send. When the microphone stops, the transcription is sent automatically (if the option is on) and the model's answer is pushed into the workflow.
3. Add the **Bionic Chat Prompt** node (right click → Add Node → Bionic) and connect its `prompt` output to the `text` input of a CLIP Text Encode.
4. The answer's prompt is written into the node and the workflow is started automatically when streaming ends. The same send is still available by hand with `⚡ Run` under an answer, or `⚡ Run` in the input bar to send the typed text directly.

If no **Bionic Chat Prompt** node exists in the graph, it is created automatically on the first Run.

The ⏹ button stops the running answer; used while nothing is generating, it interrupts the workflow that is currently running.

The ⏏ button (right of the model picker) frees the memory held by the loaded model.

## Token counter

- The displayed number is the **conversation total**: every prompt sent plus every answer generated, across all requests. It does not restart for each message.
- While generating it grows as an estimate (`≈ 837 tok`), then settles on the exact total once the server reports its `usage`.
- The tooltip gives the breakdown: "Conversation total — prompt: 645 · answers: 192 · 3 request(s)". It adds "estimate" when the server reported no `usage`.
- The ＋ button (new conversation) resets it.

## Unloading the model

The ⏏ button queries the configured server and picks the right method per backend:

| Server | Method used |
|---|---|
| LM Studio 0.4+ | `GET /api/v1/models` to find loaded instances, then `POST /api/v1/models/unload` |
| llama.cpp (router mode) | `POST /models/unload` |
| Ollama | `POST /api/generate` with `keep_alive: 0` |

The panel shows the backend and the unloaded model, then refreshes the model list. A server exposing none of these routes gets an explicit message (LM Studio 0.4+, Ollama, or llama.cpp in router mode are required).

## Settings

The ⚙ button in the panel lets you change:

- the interface language (French or English);
- the server address, with LM Studio / Ollama / llama.cpp presets or a custom address;
- the system prompt (up to 128,000 characters);
- the temperature;
- automatic workflow run after the answer;
- automatic sending of the audio transcription after the microphone;
- automatic unloading of the model after every answer (off by default);
- Internet access (web search and URL opening), also controlled by the 🌐 button next to the microphone;
- the audio transcription model and language.

Settings are saved in `bionic_chat/config.json` inside ComfyUI's user directory.

## How it works

- `nodes.py`: the `BionicChatPrompt` node (`STRING` output).
- `bionic_server.py`: `/bionic_chat/config`, `/bionic_chat/chat` (streaming proxy to the configured server), `/bionic_chat/transcribe` (local Whisper), `/bionic_chat/document` (PDF / DOCX / text extraction) and `/bionic_chat/unload` (model freeing) routes.
- `web/bionic_chat.js` and `web/bionic_chat.css`: chat panel, audio recording, attachments, cumulative counter and workflow triggering.
- Web tools: `web_search` (Bing, no API key, DuckDuckGo fallback) and `open_url` (page reading), executed by the server in a tool-calling loop (3 rounds, then a forced text answer). Local and private addresses are rejected.
- The counter reads the server's `usage` field (`stream_options: {include_usage: true}`); the server sums the tokens of every tool round (last round's context plus all answers). Without `usage`, an estimate is used.

## Limitations

- Transcription happens after recording stops (no real-time word-by-word transcription).
- Transcription runs on the CPU in `int8`.
- Conversation history is not kept between two page reloads (so the counter starts over).
- PDFs require `pypdf` or `PyPDF2`, DOCX requires `python-docx`: without them those two formats are refused (text files always work). Documents are limited to 3 per message and 60,000 characters each.
- The token counter depends on the `usage` reported by the server; otherwise it is an estimate (~3.8 characters per token).
- Unloading only works when the server exposes it: a `llama-server` started with a single model (no router mode) has no `/models/unload`.
- Web search goes through Bing (DuckDuckGo fallback) without an API key: results vary with the availability of those engines.
