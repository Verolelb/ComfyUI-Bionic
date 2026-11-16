import asyncio
import base64
import io
import json
import os
import threading
import wave

import numpy as np
from aiohttp import ClientConnectorError, ClientSession, ClientTimeout, web

import folder_paths
from server import PromptServer

routes = PromptServer.instance.routes

DEFAULT_SYSTEM_PROMPT = (
    "Tu es Bionic, l'assistant de création de prompts de ce ComfyUI. "
    "Tu discutes avec l'utilisateur, tu analyses les images et les notes vocales qu'il joint, "
    "et tu produis des prompts précis, prêts à être exécutés dans le graphe. "
    "Quand l'utilisateur demande un prompt, réponds avec le prompt final uniquement, sans préambule ni commentaire."
)

CONFIG_DEFAULTS = {
    "base_url": "http://127.0.0.1:1234/v1",
    "model": "",
    "temperature": 0.8,
    "max_tokens": 4096,
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "transcribe_model": "small",
    "transcribe_language": "fr",
}

_WHISPER_MODELS = {}
_WHISPER_LOCK = threading.Lock()


def _config_path():
    return os.path.join(folder_paths.get_user_directory(), "bionic_chat", "config.json")


def load_config():
    config = dict(CONFIG_DEFAULTS)
    try:
        with open(_config_path(), "r", encoding="utf-8") as handle:
            saved = json.load(handle)
    except (FileNotFoundError, ValueError):
        return config
    if isinstance(saved, dict):
        for key in CONFIG_DEFAULTS:
            if key in saved:
                config[key] = saved[key]
    return config


def save_config(patch):
    config = load_config()
    for key, default in CONFIG_DEFAULTS.items():
        if key not in patch:
            continue
        value = patch[key]
        if isinstance(default, float):
            config[key] = max(0.0, min(2.0, float(value)))
        elif isinstance(default, int):
            config[key] = max(1, int(value))
        else:
            config[key] = str(value)[:8000]
    config["base_url"] = config["base_url"].rstrip("/")
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
    return config


def _api_root(base_url):
    root = base_url.rstrip("/")
    return root[:-3] if root.endswith("/v1") else root


async def _fetch_models(session, base_url):
    try:
        async with session.get(_api_root(base_url) + "/api/v0/models") as response:
            if response.status == 200:
                data = await response.json()
                models = [
                    {
                        "id": entry.get("id"),
                        "type": entry.get("type") or "llm",
                        "state": entry.get("state"),
                    }
                    for entry in data.get("data", [])
                    if entry.get("id")
                ]
                if models:
                    return models
    except (ClientConnectorError, asyncio.TimeoutError, ValueError):
        pass
    async with session.get(base_url.rstrip("/") + "/models") as response:
        if response.status != 200:
            raise web.HTTPBadGateway(text="LM Studio a refusé la liste des modèles.")
        data = await response.json()
        return [
            {"id": entry.get("id"), "type": "llm", "state": None}
            for entry in data.get("data", [])
            if entry.get("id")
        ]


async def _resolve_model(session, base_url, requested):
    if requested:
        return requested
    models = await _fetch_models(session, base_url)
    for model in models:
        if model["state"] == "loaded" and model["type"] in ("llm", "vlm"):
            return model["id"]
    for model in models:
        if model["type"] in ("llm", "vlm"):
            return model["id"]
    raise web.HTTPBadGateway(text="Aucun modèle de chat n'est disponible dans LM Studio.")


def _error_message(text):
    try:
        data = json.loads(text)
    except ValueError:
        return text[:600]
    error = data.get("error")
    if isinstance(error, dict):
        return error.get("message") or text[:600]
    return str(error or text)[:600]


@routes.get("/bionic_chat/config")
async def bionic_get_config(request):
    config = load_config()
    models = []
    error = None
    try:
        async with ClientSession(timeout=ClientTimeout(total=8)) as session:
            models = await _fetch_models(session, config["base_url"])
    except Exception as exc:  # noqa: BLE001 - surfaced to the panel as a status line
        error = f"LM Studio injoignable ({exc})"
    models.sort(key=lambda model: (model["state"] != "loaded", model["id"]))
    return web.json_response({"config": config, "models": models, "error": error})


@routes.post("/bionic_chat/config")
async def bionic_save_config(request):
    return web.json_response({"config": save_config(await request.json())})


@routes.post("/bionic_chat/chat")
async def bionic_chat(request):
    payload = await request.json()
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise web.HTTPBadRequest(text="Messages manquants.")

    config = load_config()
    base_url = config["base_url"]
    session = ClientSession(timeout=ClientTimeout(total=None, sock_connect=15, sock_read=600))
    try:
        model = await _resolve_model(session, base_url, payload.get("model") or config["model"])
        system_prompt = config["system_prompt"].strip()
        body = {
            "model": model,
            "messages": ([{"role": "system", "content": system_prompt}] if system_prompt else []) + messages,
            "temperature": float(payload.get("temperature", config["temperature"])),
            "max_tokens": int(payload.get("max_tokens", config["max_tokens"])),
            "stream": True,
        }
        upstream = await session.post(base_url.rstrip("/") + "/chat/completions", json=body)
        if upstream.status != 200:
            detail = await upstream.text()
            upstream.release()
            return web.json_response({"error": _error_message(detail)}, status=502)

        response = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            }
        )
        await response.prepare(request)
        try:
            async for chunk in upstream.content.iter_any():
                await response.write(chunk)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            upstream.release()
        await response.write_eof()
        return response
    except ClientConnectorError:
        return web.json_response({"error": f"LM Studio injoignable sur {base_url}."}, status=502)
    finally:
        await session.close()


def _decode_wav(raw):
    with wave.open(io.BytesIO(raw), "rb") as handle:
        if handle.getsampwidth() != 2:
            raise ValueError("Seul le PCM 16 bits est accepté.")
        frames = handle.readframes(handle.getnframes())
        sample_rate = handle.getframerate()
        channels = handle.getnchannels()
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if sample_rate != 16000:
        target_length = max(1, int(round(audio.shape[0] * 16000 / sample_rate)))
        positions = np.linspace(0.0, audio.shape[0] - 1, target_length)
        audio = np.interp(positions, np.arange(audio.shape[0]), audio).astype(np.float32)
    return audio


def _get_whisper_model(size):
    with _WHISPER_LOCK:
        model = _WHISPER_MODELS.get(size)
        if model is None:
            from faster_whisper import WhisperModel

            model = WhisperModel(size, device="cpu", compute_type="int8")
            _WHISPER_MODELS[size] = model
        return model


def _transcribe_blocking(audio, size, language):
    model = _get_whisper_model(size)
    segments, _info = model.transcribe(
        audio,
        language=None if language in ("", "auto") else language,
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


@routes.post("/bionic_chat/transcribe")
async def bionic_transcribe(request):
    payload = await request.json()
    encoded = payload.get("audio") or ""
    try:
        raw = base64.b64decode(encoded.split(",", 1)[-1], validate=False)
    except ValueError:
        raise web.HTTPBadRequest(text="Audio invalide.")
    if not raw:
        raise web.HTTPBadRequest(text="Audio vide.")
    if len(raw) > 30 * 1024 * 1024:
        raise web.HTTPBadRequest(text="Audio trop long (30 Mo maximum).")

    try:
        audio = _decode_wav(raw)
    except (wave.Error, ValueError) as exc:
        raise web.HTTPBadRequest(text=f"Audio invalide : {exc}")

    config = load_config()
    size = str(payload.get("model") or config["transcribe_model"])
    language = str(payload.get("language") or config["transcribe_language"])

    loop = asyncio.get_running_loop()
    try:
        text = await loop.run_in_executor(None, _transcribe_blocking, audio, size, language)
    except ImportError:
        return web.json_response(
            {"error": "faster-whisper n'est pas installé dans le Python de ComfyUI."}, status=501
        )
    except Exception as exc:  # noqa: BLE001 - download/model errors must reach the panel
        return web.json_response({"error": f"Transcription impossible : {exc}"}, status=500)
    return web.json_response({"text": text})
