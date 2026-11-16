import asyncio
import base64
import html
import io
import ipaddress
import json
import os
import re
import threading
import wave
from urllib.parse import parse_qs, urljoin, urlparse

import numpy as np
from aiohttp import ClientConnectorError, ClientSession, ClientTimeout, web
from aiohttp.client_exceptions import ClientConnectionResetError

import folder_paths
from server import PromptServer

routes = PromptServer.instance.routes

DEFAULT_SYSTEM_PROMPT = (
    "Tu es Bionic, l'assistant de création de prompts de ce ComfyUI. "
    "RÈGLE ABSOLUE : quand l'utilisateur demande une image, un prompt ou une scène, tu ne poses AUCUNE question de clarification. "
    "Tu fais des choix raisonnables et tu réponds UNIQUEMENT avec le prompt final, en texte brut, "
    "sans préambule, sans question, sans commentaire."
)

LEGACY_SYSTEM_PROMPT = (
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
    "auto_run": True,
    "auto_send_audio": True,
    "web_enabled": False,
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
    if str(config["system_prompt"]).strip() == LEGACY_SYSTEM_PROMPT.strip():
        config["system_prompt"] = DEFAULT_SYSTEM_PROMPT
    return config


def save_config(patch):
    config = load_config()
    for key, default in CONFIG_DEFAULTS.items():
        if key not in patch:
            continue
        value = patch[key]
        if isinstance(default, bool):
            config[key] = bool(value)
        elif isinstance(default, float):
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


WEB_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Cherche des pages web récentes et renvoie les titres et URL des résultats.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Requête de recherche"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": "Ouvre une page web et renvoie son texte lisible.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "URL http ou https"}},
                "required": ["url"],
            },
        },
    },
]

WEB_SYSTEM_HINT = (
    "Accès Internet activé : utilise l'outil web_search pour chercher des informations récentes "
    "et open_url pour lire une page précise. Fais au plus deux recherches, puis réponds directement "
    "avec les informations trouvées et cite les URL des sources utilisées."
)

_BING_SEARCH_URL = "https://www.bing.com/search"
_DDG_SEARCH_URL = "https://html.duckduckgo.com/html/"
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_SEARCH_HEADERS = {"User-Agent": _BROWSER_UA, "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"}
_MAX_PAGE_BYTES = 2 * 1024 * 1024
_MAX_PAGE_CHARS = 8000
_MAX_SEARCH_RESULTS = 6
_MAX_TOOL_ROUNDS = 3


def _strip_html(text):
    return html.unescape(re.sub(r"(?s)<[^>]+>", "", text)).strip()


def _decode_duckduckgo_link(href):
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return target
    return href


def _decode_bing_link(href):
    href = html.unescape(href)
    if "bing.com/ck/a" in href:
        target = parse_qs(urlparse(href).query).get("u", [""])[0]
        if target.startswith("a1"):
            data = target[2:]
            data += "=" * (-len(data) % 4)
            try:
                return base64.urlsafe_b64decode(data).decode("utf-8", "replace")
            except (ValueError, UnicodeDecodeError):
                return href
    return href


def _parse_bing(page):
    results = []
    for block in page.split('class="b_algo"')[1:]:
        match = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not match:
            continue
        url = _decode_bing_link(match.group(1))
        title = _strip_html(match.group(2))
        if not title or not url.startswith("http"):
            continue
        snippet_match = re.search(r'<p[^>]*>(.*?)</p>', block, re.S)
        snippet = _strip_html(snippet_match.group(1))[:300] if snippet_match else ""
        entry = f"{len(results) + 1}. {title}\n{url}"
        if snippet:
            entry += f"\n{snippet}"
        results.append(entry)
        if len(results) >= _MAX_SEARCH_RESULTS:
            break
    return results


def _parse_duckduckgo(page):
    links = re.findall(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S)
    snippets = re.findall(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', page, re.S)
    results = []
    for index, (href, title) in enumerate(links[:_MAX_SEARCH_RESULTS]):
        url = _decode_duckduckgo_link(html.unescape(href))
        clean_title = _strip_html(title)
        if not clean_title or not url.startswith("http"):
            continue
        snippet = _strip_html(snippets[index])[:300] if index < len(snippets) else ""
        entry = f"{len(results) + 1}. {clean_title}\n{url}"
        if snippet:
            entry += f"\n{snippet}"
        results.append(entry)
    return results


async def _fetch_search_page(session, url, query):
    async with session.get(url, params={"q": query}, headers=_SEARCH_HEADERS) as response:
        if response.status != 200:
            return ""
        return await response.text()


async def _web_search(query, seen=None):
    query = query.strip()
    if not query:
        return "Requête vide."
    if seen is not None:
        key = query.lower()
        if key in seen:
            return "Cette recherche a déjà été effectuée ; utilise les résultats précédents."
        seen.add(key)
    async with ClientSession(timeout=ClientTimeout(total=25)) as session:
        results = _parse_bing(await _fetch_search_page(session, _BING_SEARCH_URL, query))
        if not results:
            results = _parse_duckduckgo(await _fetch_search_page(session, _DDG_SEARCH_URL, query))
    if not results:
        return "Aucun résultat trouvé (les moteurs de recherche ont peut-être bloqué la requête)."
    return f"Résultats de recherche pour « {query} » :\n\n" + "\n\n".join(results)


async def _assert_public_host(host):
    infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise ValueError("hôte introuvable")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ValueError("adresse locale ou privée")


def _html_to_text(raw, content_type):
    charset = "utf-8"
    match = re.search(r"charset=([\w.-]+)", content_type, re.I)
    if match:
        charset = match.group(1)
    text = raw.decode(charset, "replace")
    text = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h[1-6])>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


async def _open_url(url):
    target = url.strip()
    if not target:
        return "URL vide."
    raw = b""
    content_type = ""
    for _ in range(4):
        parsed = urlparse(target)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return "URL invalide (http ou https attendu)."
        try:
            await _assert_public_host(parsed.hostname)
        except (ValueError, OSError):
            return "Cette adresse est refusée (hôte local ou privé)."
        async with ClientSession(timeout=ClientTimeout(total=25)) as session:
            async with session.get(target, headers={"User-Agent": _BROWSER_UA}, allow_redirects=False) as response:
                if response.status in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        return "Redirection invalide."
                    target = urljoin(target, location)
                    continue
                if response.status >= 400:
                    return f"La page a renvoyé HTTP {response.status}."
                content_type = response.headers.get("Content-Type", "")
                raw = await response.content.read(_MAX_PAGE_BYTES)
        break
    else:
        return "Trop de redirections."

    if "html" not in content_type and not content_type.startswith("text/"):
        return f"Contenu non textuel ignoré ({content_type or 'type inconnu'})."
    text = _html_to_text(raw, content_type)
    if not text:
        return "La page ne contient pas de texte lisible."
    if len(text) > _MAX_PAGE_CHARS:
        text = text[:_MAX_PAGE_CHARS] + "\n\n[page tronquée]"
    return f"Contenu de {target} :\n\n{text}"


async def _run_tool(name, arguments, seen):
    try:
        if name == "web_search":
            return await _web_search(str(arguments.get("query") or ""), seen)
        if name == "open_url":
            return await _open_url(str(arguments.get("url") or ""))
    except (ClientConnectorError, asyncio.TimeoutError, OSError) as exc:
        return f"Échec de la requête web : {exc}"
    return f"Outil inconnu : {name}"


def _tool_label(name, arguments):
    if name == "web_search":
        return f"🔎 Recherche web : {str(arguments.get('query') or '')[:80]}"
    if name == "open_url":
        return f"🌐 Ouverture : {str(arguments.get('url') or '')[:100]}"
    return None


async def _write_event(response, payload):
    await response.write(b"data: " + json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n\n")


async def _stream_round(session, base_url, model, messages, config, tools, response, tool_choice="auto"):
    body = {
        "model": model,
        "messages": messages,
        "temperature": float(config["temperature"]),
        "max_tokens": int(config["max_tokens"]),
        "stream": True,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = tool_choice
    url = base_url.rstrip("/") + "/chat/completions"
    upstream = await session.post(url, json=body)
    if tools and upstream.status in (400, 422):
        await upstream.text()
        upstream.release()
        body.pop("tools", None)
        body.pop("tool_choice", None)
        upstream = await session.post(url, json=body)
    if upstream.status != 200:
        detail = await upstream.text()
        upstream.release()
        raise web.HTTPBadGateway(text=_error_message(detail))

    content_parts = []
    calls = {}
    try:
        async for raw_line in upstream.content:
            line = raw_line.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            choice = (chunk.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            piece = delta.get("content")
            if piece:
                content_parts.append(piece)
                await _write_event(response, {"choices": [{"delta": {"content": piece}}]})
            reasoning = delta.get("reasoning_content")
            if reasoning:
                await _write_event(response, {"choices": [{"delta": {"reasoning_content": reasoning}}]})
            for tool_call in delta.get("tool_calls") or []:
                index = tool_call.get("index", 0)
                entry = calls.setdefault(
                    index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                )
                if tool_call.get("id"):
                    entry["id"] = tool_call["id"]
                function = tool_call.get("function") or {}
                entry["function"]["name"] += function.get("name") or ""
                entry["function"]["arguments"] += function.get("arguments") or ""
    finally:
        upstream.release()
    return "".join(content_parts), [calls[key] for key in sorted(calls)]


async def _run_agent(session, base_url, model, messages, config, web_enabled, response):
    tools = WEB_TOOLS if web_enabled else None
    seen = set()
    for _ in range(_MAX_TOOL_ROUNDS):
        content, calls = await _stream_round(session, base_url, model, messages, config, tools, response)
        if not calls:
            return
        messages.append({"role": "assistant", "content": content, "tool_calls": calls})
        for call in calls:
            function = call.get("function") or {}
            name = function.get("name") or ""
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except ValueError:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            label = _tool_label(name, arguments)
            if label:
                await _write_event(response, {"bionic_event": "tool", "label": label})
            result = await _run_tool(name, arguments, seen)
            messages.append(
                {"role": "tool", "tool_call_id": call.get("id") or f"call_{len(messages)}", "content": result}
            )
    messages.append(
        {"role": "user", "content": "Réponds maintenant en texte, sans appeler d'outil."}
    )
    await _stream_round(session, base_url, model, messages, config, tools, response, tool_choice="none")


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
    web_enabled = bool(config["web_enabled"])
    session = ClientSession(timeout=ClientTimeout(total=None, sock_connect=15, sock_read=600))
    try:
        model = await _resolve_model(session, base_url, payload.get("model") or config["model"])
        system_prompt = config["system_prompt"].strip()
        if web_enabled:
            system_prompt = (system_prompt + "\n\n" + WEB_SYSTEM_HINT).strip()
        conversation = ([{"role": "system", "content": system_prompt}] if system_prompt else []) + messages

        response = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            }
        )
        await response.prepare(request)
        try:
            await _run_agent(session, base_url, model, conversation, config, web_enabled, response)
            await response.write(b"data: [DONE]\n\n")
            await response.write_eof()
        except web.HTTPBadGateway as exc:
            try:
                await _write_event(response, {"error": exc.text})
                await response.write(b"data: [DONE]\n\n")
                await response.write_eof()
            except (ClientConnectionResetError, ConnectionResetError):
                pass
        except (ClientConnectionResetError, ConnectionResetError, asyncio.CancelledError):
            pass
        except Exception as exc:  # noqa: BLE001 - streaming errors must reach the panel
            try:
                await _write_event(response, {"error": str(exc)})
                await response.write(b"data: [DONE]\n\n")
                await response.write_eof()
            except (ClientConnectionResetError, ConnectionResetError):
                pass
        return response
    except web.HTTPBadGateway as exc:
        return web.json_response({"error": exc.text}, status=502)
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
