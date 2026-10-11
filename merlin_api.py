#!/usr/bin/env python3
"""merlin_api.py — Merlin Pro API client for NeXuS AI Router

CLI:    python merlin_api.py --init
        python merlin_api.py "your prompt" [--model gemini-3.1-pro] [--deep] [--raw]
Server: python merlin_api.py --serve [--port 8811]
"""

import json
import os
import sys
import uuid
import time
import argparse
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── Config paths (no hardcoding) ───────────────────────────────────────────────
NEXUS_HOME   = os.environ.get("NEXUS_HOME", str(Path.home() / "NeXuS"))
CONFIG_FILE  = os.environ.get("MERLIN_CONFIG",
               f"{NEXUS_HOME}/.config/nexus/merlin.json")

MERLIN_CHAT_URL  = "https://www.getmerlin.in/arcane/api/v2/thread/unified"
FIREBASE_REFRESH = "https://securetoken.googleapis.com/v1/token"
FIREBASE_KEY     = "AIzaSyAvCgtQ4XbmlQGIynDT-v_M8eLaXrKmtiM"  # public project ID, not a secret

BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"

LIBREWOLF_COOKIES_DB = os.path.expanduser(
    "~/.config/librewolf/librewolf/zqiwk7i6.default-release/cookies.sqlite"
)

def _load_browser_cookies() -> dict:
    """Extract all Merlin cookies from LibreWolf — always re-copies for freshness."""
    import shutil, sqlite3 as _sq
    tmp = "/tmp/_merlin_cookies.sqlite"
    try:
        shutil.copy2(LIBREWOLF_COOKIES_DB, tmp)
        con = _sq.connect(tmp)
        cur = con.cursor()
        # grab ALL merlin-domain cookies (getmerlin.in + session.getmerlin.in)
        cur.execute("SELECT name, value FROM moz_cookies WHERE host LIKE '%merlin%'")
        cookies = {n: v for n, v in cur.fetchall()}
        con.close()
        return cookies
    except Exception:
        return {}

def _build_headers(token: str, extra_cookies: dict = None) -> dict:
    """Build browser-like headers that pass Cloudflare."""
    cookies = _load_browser_cookies()
    if extra_cookies:
        cookies.update(extra_cookies)
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    return {
        "Authorization":   f"Bearer {token}",
        "Content-Type":    "application/json",
        "Accept":          "application/json",
        "User-Agent":      BROWSER_UA,
        "Referer":         "https://www.getmerlin.in/chat",
        "Origin":          "https://www.getmerlin.in",
        "Cookie":          cookie_str,
    }

KNOWN_MODELS = [
    "gemini-3.1-pro",
    "gemini-3.1-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gpt-4.5",
    "gpt-4o",
    "gpt-4o-mini",
    "claude-3.7-sonnet",
    "claude-3.5-sonnet",
    "mistral-large",
    "llama-3.1-405b",
    "perplexity-sonar",
]

IMAGE_MODELS = ["dall-e-3", "dall-e-2", "dall-e"]

MERLIN_IMAGE_URL = "https://www.getmerlin.in/arcane/api/v2/thread/unified"

# ── Config ─────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    path = Path(CONFIG_FILE)
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)

def save_config(cfg: dict):
    path = Path(CONFIG_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)

# ── Auth ───────────────────────────────────────────────────────────────────────

def _refresh_token(refresh_token: str, firebase_key: str = FIREBASE_KEY) -> tuple[str, int]:
    url = f"{FIREBASE_REFRESH}?key={firebase_key}"
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=15) as resp:
        r = json.loads(resp.read())
    expires_at = int(time.time()) + int(r.get("expires_in", 3600))
    return r["id_token"], expires_at

def get_access_token(cfg: dict) -> str:
    now = int(time.time())
    # Use cached token if still valid (60s buffer)
    if cfg.get("access_token") and cfg.get("expires_at", 0) > now + 60:
        return cfg["access_token"]

    refresh = cfg.get("refresh_token") or os.environ.get("MERLIN_REFRESH_TOKEN")
    key     = cfg.get("firebase_key")   or os.environ.get("MERLIN_FIREBASE_KEY") or FIREBASE_KEY
    if not refresh:
        raise RuntimeError(
            "Missing refresh_token. Run: python merlin_api.py --init"
        )

    token, expires_at = _refresh_token(refresh, key)
    cfg["access_token"] = token
    cfg["expires_at"]   = expires_at
    save_config(cfg)
    return token

# ── SSE parser ────────────────────────────────────────────────────────────────

def _parse_sse(raw: str) -> dict:
    """Parse Merlin's SSE stream → dict with 'data.message.content' text."""
    chunks = []
    error  = None
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            ev = json.loads(payload)
        except Exception:
            continue
        # error event
        if ev.get("type") == "INTERNAL_SERVER_ERROR" or "error" in str(ev.get("message", "")).lower():
            error = ev.get("message", str(ev))
            continue
        # content chunk
        data = ev.get("data", ev)
        if isinstance(data, dict):
            content = data.get("content", "")
            if content and data.get("eventType") != "DONE":
                chunks.append(content)
    text = "".join(chunks).strip()
    if not text and error:
        raise RuntimeError(f"Merlin error: {error}")
    return {"data": {"message": {"content": text}}, "status": "ok"}

# ── Core chat ──────────────────────────────────────────────────────────────────

def chat(prompt: str, model: str = None, deep_research: bool = False,
         cfg: dict = None) -> dict:
    if cfg is None:
        cfg = load_config()

    token = get_access_token(cfg)
    # merlin_id is the Merlin UUID (different from Firebase uid — use this in request body)
    uid   = cfg.get("merlin_id") or cfg.get("uid") or os.environ.get("MERLIN_UID", "")
    model = model or cfg.get("default_model", "gemini-3.1-pro")

    chat_id  = str(uuid.uuid4())
    msg_id   = str(uuid.uuid4())
    child_id = str(uuid.uuid4())

    url = MERLIN_CHAT_URL + ("?deepresearch=1" if deep_research else "")

    auto_mode = (model in (None, "auto", "merlin-auto"))
    body = {
        "attachments":     [],
        "chatId":          chat_id,
        "sessionId":       chat_id,
        "gravity_context": {},
        "device": {
            "browser":         "web",
            "device_type":     "desktop",
            "language":        "en-US",
            "locale":          "en-US",
            "platform":        "Linux x86_64",
            "screen_height":   900,
            "screen_width":    1920,
            "timezone":        "UTC",
            "ua":              "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/109.0",
            "viewport_height": 900,
            "viewport_width":  1920,
        },
        "language": "AUTO",
        "user":     {"id": uid},
        "message": {
            "childId":  child_id,
            "content":  prompt,
            "context":  "",
            "id":       msg_id,
            "parentId": "root",
        },
        "metadata": {
            "deepResearch":  deep_research,
            "isWebpageChat": False,
            "merlinMagic":   auto_mode,   # true = Merlin picks best model automatically
            "noTask":        True,
            "proFinderMode": False,
        },
        "mode":  "UNIFIED_CHAT",
        "model": model if not auto_mode else cfg.get("default_model", "gemini-3.1-pro"),
    }

    data    = json.dumps(body).encode()
    headers = _build_headers(token)
    req     = urllib.request.Request(url, data=data, method="POST", headers=headers)

    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    # Endpoint returns SSE — parse events and collect content chunks
    content_type = ""
    if "text/event-stream" in str(getattr(resp, "headers", "")):
        return _parse_sse(raw)

    # Fallback: plain JSON
    try:
        return json.loads(raw)
    except Exception:
        return _parse_sse(raw)

def extract_text(response: dict) -> str:
    """Pull the assistant message text from Merlin's response."""
    if not isinstance(response, dict):
        return str(response)
    data = response.get("data", response)
    if isinstance(data, dict):
        msg = data.get("message", data.get("content", ""))
        if isinstance(msg, dict):
            return msg.get("content", json.dumps(data, indent=2))
        if isinstance(msg, str):
            return msg
    return json.dumps(response, indent=2)

# ── OpenAI-compat wrapper ──────────────────────────────────────────────────────

def chat_openai(messages: list, model: str = None, cfg: dict = None) -> dict:
    """Translate OpenAI messages list → Merlin → OpenAI response shape."""
    prompt = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in messages
    )
    raw  = chat(prompt, model=model, cfg=cfg)
    text = extract_text(raw)
    return {
        "id":      f"merlin-{uuid.uuid4().hex[:8]}",
        "object":  "chat.completion",
        "created": int(time.time()),
        "model":   model or "merlin-default",
        "choices": [{
            "index":   0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "provenance": {"provider": "merlin", "raw_status": raw.get("status")},
    }

# ── Image generation ──────────────────────────────────────────────────────────

def generate_image(prompt: str, model: str = "dall-e-3", size: str = "1024x1024",
                   n: int = 1, cfg: dict = None) -> dict:
    """Call Merlin with a DALL-E image model, return OpenAI /v1/images/generations shape."""
    if cfg is None:
        cfg = load_config()
    token = get_access_token(cfg)
    uid   = cfg.get("uid") or os.environ.get("MERLIN_UID", "")
    chat_id  = str(uuid.uuid4())
    msg_id   = str(uuid.uuid4())
    child_id = str(uuid.uuid4())

    body = {
        "attachments":     [],
        "chatId":          chat_id,
        "sessionId":       chat_id,
        "gravity_context": {},
        "device": {
            "browser": "web", "device_type": "desktop",
            "language": "en-US", "locale": "en-US",
            "platform": "Linux x86_64",
            "screen_height": 900, "screen_width": 1920,
            "timezone": "UTC",
            "ua": "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/109.0",
            "viewport_height": 900, "viewport_width": 1920,
        },
        "language": "AUTO",
        "user":     {"id": uid},
        "message": {
            "childId": child_id, "content": prompt,
            "context": "", "id": msg_id, "parentId": "root",
        },
        "metadata": {
            "deepResearch": False, "isWebpageChat": False,
            "merlinMagic": False, "noTask": True, "proFinderMode": False,
        },
        "mode":  "UNIFIED_CHAT",
        "model": model,
        "imageOptions": {"size": size, "n": n},
    }

    data    = json.dumps(body).encode()
    headers = _build_headers(token)
    req     = urllib.request.Request(MERLIN_IMAGE_URL, data=data, method="POST", headers=headers)

    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = json.loads(resp.read())

    # Extract image URL(s) from Merlin response
    images = []
    data_block = raw.get("data", raw)
    if isinstance(data_block, dict):
        content = data_block.get("message", {})
        if isinstance(content, dict):
            content = content.get("content", "")
        # Merlin returns markdown like ![img](url) or just a URL
        import re as _re
        urls = _re.findall(r'https?://\S+\.(?:png|jpg|jpeg|webp)', str(content))
        if not urls:
            urls = _re.findall(r'https?://\S+', str(content))
        images = [{"url": u} for u in urls[:n]]

    if not images:
        images = [{"url": "", "b64_json": None,
                   "revised_prompt": prompt,
                   "_raw": raw.get("data", {})}]

    return {
        "created": int(time.time()),
        "data": images,
    }

# ── HTTP server mode (OpenAI-compat endpoint) ─────────────────────────────────

class MerlinHandler(BaseHTTPRequestHandler):
    cfg = {}

    def log_message(self, fmt, *args):
        pass  # quiet

    def send_json(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"status": "ok", "provider": "merlin"})
        elif self.path == "/v1/models":
            all_models = KNOWN_MODELS + IMAGE_MODELS + ["merlin-auto"]
            self.send_json(200, {
                "object": "list",
                "data": [{"id": m, "object": "model"} for m in all_models],
            })
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length))

        if self.path in ("/v1/chat/completions", "/chat/completions"):
            try:
                result = chat_openai(
                    body.get("messages", []),
                    model=body.get("model"),
                    cfg=self.cfg,
                )
                self.send_json(200, result)
            except Exception as e:
                self.send_json(502, {"error": str(e)})

        elif self.path in ("/v1/images/generations", "/images/generations"):
            try:
                prompt = body.get("prompt", "")
                model  = body.get("model", "dall-e-3")
                size   = body.get("size", "1024x1024")
                n      = body.get("n", 1)
                result = generate_image(prompt, model=model, size=size, n=n, cfg=self.cfg)
                self.send_json(200, result)
            except Exception as e:
                self.send_json(502, {"error": str(e)})

        else:
            self.send_json(404, {"error": f"unknown path: {self.path}"})

def serve(port: int = 8811):
    cfg = load_config()
    MerlinHandler.cfg = cfg
    httpd = HTTPServer(("127.0.0.1", port), MerlinHandler)
    print(f"Merlin server  → http://127.0.0.1:{port}")
    print(f"  Chat         → POST /v1/chat/completions  (model: auto|gpt-4o|gemini-3.1-pro|...)")
    print(f"  Image        → POST /v1/images/generations (model: dall-e-3)")
    print(f"  Models       → GET  /v1/models")
    print(f"  Health       → GET  /health")
    print(f"  Auto mode    → set model='merlin-auto' or 'auto' (merlinMagic=true)")
    httpd.serve_forever()

# ── Setup wizard ───────────────────────────────────────────────────────────────

def init_config():
    cfg = load_config()
    print("=== Merlin API Setup ===")
    print(f"Config → {CONFIG_FILE}\n")
    cfg["refresh_token"] = input("Paste your Merlin refresh_token: ").strip()
    cfg["uid"]           = input("Paste your Merlin UID:           ").strip()
    cfg["default_model"] = input("Default model [gemini-3.1-pro]:  ").strip() \
                           or "gemini-3.1-pro"
    save_config(cfg)
    print(f"\nSaved. Firebase key auto-loaded.")
    print(f"Test: python merlin_api.py \"Hello Merlin\"")

# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Merlin Pro API — CLI and OpenAI-compat server"
    )
    parser.add_argument("prompt",    nargs="?",       help="Prompt to send")
    parser.add_argument("--model",   default=None,    help="Model name")
    parser.add_argument("--deep",    action="store_true", help="Deep research mode")
    parser.add_argument("--raw",     action="store_true", help="Print full JSON response")
    parser.add_argument("--init",    action="store_true", help="Run setup wizard")
    parser.add_argument("--models",  action="store_true", help="List known models")
    parser.add_argument("--serve",   action="store_true", help="Run OpenAI-compat server")
    parser.add_argument("--port",    type=int, default=8811, help="Server port (default 8811)")
    args = parser.parse_args()

    if args.init:
        init_config()
        return

    if args.models:
        for m in KNOWN_MODELS:
            print(m)
        return

    if args.serve:
        serve(args.port)
        return

    if not args.prompt:
        parser.print_help()
        sys.exit(1)

    try:
        result = chat(args.prompt, model=args.model, deep_research=args.deep)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        sys.exit(1)

    if args.raw:
        print(json.dumps(result, indent=2))
    else:
        print(extract_text(result))

if __name__ == "__main__":
    main()
