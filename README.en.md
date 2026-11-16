# ComfyUI-Bionic

**English** · [Français](README.md)

A Bionic-style chat (LM Studio) right inside ComfyUI, with audio input, vision input and a receiver node that takes the prompt and runs the workflow.

## Features

- Floating chat panel connected to the LM Studio local server (text and vision models).
- French or English interface, switchable in ⚙ (panel and node).
- Streaming answers, collapsible reasoning, model picker in the panel.
- Vision input: 🖼 button, `Ctrl+V` paste or drag and drop images.
- Audio input: 🎙 button, microphone recording and local transcription (faster-whisper).
- **Bionic Chat Prompt** node: receives the chat prompt and outputs it as a `STRING`.
- `⚡ Run` button: writes the prompt into the node, then runs the workflow, exactly like ComfyUI's Run button.
- Automatic workflow run as soon as the model finishes answering (on by default, can be turned off in ⚙).
- Automatic sending of the audio transcription when the microphone stops (on by default, can be turned off in ⚙).
- Internet access: the model can search the web and open pages to answer. Off by default, enabled with the 🌐 button in the panel (or in ⚙).

## Requirements

- ComfyUI (tested with version 0.45).
- [LM Studio](https://lmstudio.ai/) with the local server running (Developer tab → *Start server*, `http://127.0.0.1:1234`).
- At least one chat model loaded or downloaded in LM Studio.

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

1. Open the panel with `💬 Bionic` and pick an LM Studio model.
2. Type your prompt, attach images or dictate it with the microphone, then send. When the microphone stops, the transcription is sent automatically (if the option is on) and the model's answer is pushed into the workflow.
3. Add the **Bionic Chat Prompt** node (right click → Add Node → Bionic) and connect its `prompt` output to the `text` input of a CLIP Text Encode.
4. The answer's prompt is written into the node and the workflow is started automatically when streaming ends. The same send is still available by hand with `⚡ Run` under an answer, or `⚡ Run` in the input bar to send the typed text directly.

If no **Bionic Chat Prompt** node exists in the graph, it is created automatically on the first Run.

## Settings

The ⚙ button in the panel lets you change:

- the interface language (French or English);
- the LM Studio server URL;
- the system prompt;
- the temperature;
- automatic workflow run after the answer;
- automatic sending of the audio transcription after the microphone;
- Internet access (web search and URL opening), also controlled by the 🌐 button next to the microphone;
- the audio transcription model and language.

Settings are saved in `bionic_chat/config.json` inside ComfyUI's user directory.

## How it works

- `nodes.py`: the `BionicChatPrompt` node (`STRING` output).
- `bionic_server.py`: `/bionic_chat/config`, `/bionic_chat/chat` (streaming proxy to LM Studio) and `/bionic_chat/transcribe` (local Whisper) routes.
- `web/bionic_chat.js` and `web/bionic_chat.css`: chat panel, audio recording, attachments and workflow triggering.
- Web tools: `web_search` (Bing, no API key, DuckDuckGo fallback) and `open_url` (page reading), executed by the server in an LM Studio tool-calling loop (3 rounds, then a forced text answer). Local and private addresses are rejected.

## Limitations

- Transcription happens after recording stops (no real-time word-by-word transcription).
- Transcription runs on the CPU in `int8`.
- Conversation history is not kept between two page reloads.
