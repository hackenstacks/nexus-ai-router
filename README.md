# NeXuS AI Router

**Self-healing LLM routing for the NeXuS sovereign stack.**

Routes AI requests to the best available provider automatically — local first, free cloud second, paid last. Falls back on failure. No hardcoded keys. Bifrost-native.

> *"If blocked at one provider, route to another."*

---

## Status

| Component | State |
|-----------|-------|
| Provider failover (static ordering) | ✅ Working |
| Merlin Pro puppet layer (port 8811) | ✅ Working |
| SSE response parsing | ✅ Fixed (data.data.text path) |
| gravity_context injection | ✅ Fixed (configurable + default) |
| Dynamic health scoring | 🔴 Planned — currently static local→cloud order |
| Per-provider latency tracking | 🔴 Planned |
| Chimera task dispatch (text/vision/RAG) | 🔴 Planned |

---

## Architecture

```
Request → main.py (port 8810)
             ├── Local first:  Ollama → Merlin (port 8811)
             └── Cloud fallback: Pollinations → Groq → Mistral → OpenAI
```

**Provider priority (current — static):**

| Tier | Providers | How |
|------|-----------|-----|
| Local | Ollama, Merlin (puppeted) | `is_local: true` in config |
| Cloud | Pollinations, Groq, Mistral, OpenAI, Anthropic | `is_local: false` |

Local providers are tried first, in config order. Cloud providers follow. First success wins.

---

## Components

| File | Purpose |
|------|---------|
| `main.py` | FastAPI router — OpenAI-compat `/v1/chat/completions`, ordered failover |
| `merlin_api.py` | Merlin Pro puppet — CLI + OpenAI-compat server on port 8811 |
| `config.yml` | Provider config — endpoints, models, enable/disable |
| `requirements.txt` | Python deps |

---

## Quick Start

```bash
pip install -r requirements.txt
cp config.yml config.yml.local   # edit with your keys
python main.py                    # starts on port 8810
```

```bash
curl http://127.0.0.1:8810/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"hello"}]}'
```

Every response includes a `provenance` block in the JSON body:
```json
"provenance": {"provider": "ollama", "endpoint": "...", "local": true}
```

---

## Merlin Pro Layer

Merlin Pro ($25/year) gives access to GPT-4, Gemini, DALL-E with no direct API keys.
`merlin_api.py` puppets the Merlin web API as a local OpenAI-compat server on port 8811.

### Setup

```bash
python merlin_api.py --init    # one-time setup wizard
python merlin_api.py --serve   # start on port 8811
python merlin_api.py --models  # list known models
```

**`--init` prompts for:**
- `refresh_token` — from LibreWolf DevTools (see below)
- `uid` — your Merlin user ID
- `default_model` — e.g. `gemini-3.1-pro`
- `gravity_context` — browser context blob (see below)

Config stored at `~/.config/nexus/merlin.json` (or `$MERLIN_CONFIG`).

### Capturing refresh_token and gravity_context

Merlin uses Firebase auth. The refresh_token and gravity_context must be captured
once from a real browser session:

1. Open LibreWolf → `https://www.getmerlin.in/chat`
2. Open DevTools → **Network** tab
3. Send any message in the chat
4. Find the `POST unified` request
5. **Request Headers** → copy `Authorization: Bearer <token>` — this is the **id_token**
6. **Request Body** → copy the `refresh_token` field and the `gravity_context` object
7. **Request Body** → copy the `user.id` field — this is your `uid`

Store gravity_context without re-running `--init`:
```bash
python merlin_api.py --set-gravity '{"tabUrl":"https://www.getmerlin.in/chat","tabTitle":"Merlin","selectedText":"","activeTab":true}'
```

If `gravity_context` is not configured, a safe default matching the Merlin chat page
is used automatically. An empty `{}` causes `INTERNAL_SERVER_ERROR` from Merlin's API.

### Endpoints (port 8811)

```
POST /v1/chat/completions    text chat (model: auto|gpt-4o|gemini-3.1-pro|...)
POST /v1/images/generations  image gen (model: dall-e-3)
GET  /v1/models              list available models
GET  /health                 health check
```

**Auto mode:** set `model` to `merlin-auto` — Merlin's own routing picks the best model.

### Known models

```
gemini-3.1-pro, gemini-3.1-flash, gemini-2.5-pro, gemini-2.5-flash
gpt-4.5, gpt-4o, gpt-4o-mini
claude-3.7-sonnet, claude-3.5-sonnet
mistral-large, llama-3.1-405b, perplexity-sonar
dall-e-3, dall-e-2
```

### LibreWolf cookies (optional)

Merlin's Cloudflare checks pass more reliably with browser cookies attached.
Set the path via env var — profile ID is machine-specific:

```bash
export LIBREWOLF_COOKIES_DB="$HOME/.config/librewolf/librewolf/<profile>/cookies.sqlite"
```

If unset, `merlin_api.py` globs for the cookies db automatically.

---

## Bifrost Integration

The router is a Bifrost provider at `https://localhost:8443`:

```
Client → Bifrost (8443) → nexus-router (8810) → best provider
```

Bifrost injects API keys server-side. No credentials ever reach the browser.

---

## Configuration

```yaml
# config.yml
server:
  host: "127.0.0.1"
  port: 8810

proxy:
  socks: "socks5://172.21.0.1:1080"   # used for cloud providers only

providers:
  ollama:
    endpoint: "http://localhost:11434/v1"
    model: "llama3"
    enabled: true
    is_local: true

  merlin:
    endpoint: "http://127.0.0.1:8811/v1"
    model: "gemini-3.1-pro"
    enabled: true
    is_local: true

  groq:
    endpoint: "https://api.groq.com/openai/v1"
    key: "gsk_REPLACE_ME"
    model: "llama3-70b-8192"
    enabled: false
    is_local: false
```

All secrets live in `~/.config/nexus/secrets/nexus.env` — never in config files or code.
Provider keys in `config.yml` are placeholders only; Bifrost injects the real values.

---

## NeXuS Stack

```
nexus-ai-router  ←── you are here
      ↑
Bifrost Bridge (https://localhost:8443)
      ↑
All NeXuS apps (chargen, ai-hud, MNEMOSYNE, etc.)
```

- **Peewee** — local sovereign model (Qwen3.5-4B fine-tune), Tier 1
- **Merlin** — puppeted GPT/Gemini/DALL-E access, Tier 1
- **Pollinations** — 120+ free cloud models via Bifrost, Tier 2
- **Groq/Mistral** — paid fallback, Tier 3

---

## License

Apache 2.0

**Author:** hackenstacks@protonmail.com
**Contact:** hackenstacks@protonmail.com
**Part of:** [NeXuS](https://hackenstacks.github.io/nexus/) — Sane · Simple · Secure · Stealthy · Beautiful
