# NeXuS AI Router

**Automagical self-healing LLM routing for the NeXuS sovereign stack.**

Routes AI requests to the best available provider automatically — local first, free cloud second, paid last. Self-heals on failure. No hardcoded keys. Bifrost-native.

> *"If blocked at one provider, auto-route to another."*

---

## Architecture — Chimera Dispatch

```
Request → Chimera Router
             ├── Text chat   → Fast local/free (Ollama → aichat → Pollinations → Groq)
             ├── Vision      → Multimodal capable (Gemini → GPT-4V → Claude)
             └── RAG/Memory  → Cheap summarizer (any fast model)
```

**Provider priority tiers:**

| Tier | Providers | Score |
|------|-----------|-------|
| Local | Ollama, aichat, Merlin (puppeted) | 10 |
| Free cloud | Pollinations, AI Horde | 20 |
| Paid cloud | Groq, Mistral, OpenAI, Anthropic | 50 |

Score = `priority + latency_ms + (failure_count × 100)` — lowest wins.

---

## Components

| File | Purpose |
|------|---------|
| `main.py` | FastAPI router — OpenAI-compat `/v1/chat/completions`, health tracking, failover |
| `merlin_api.py` | Merlin Pro puppet layer — CLI + OpenAI-compat server on port 8811 |
| `config.yml` | Provider config — endpoints, models, enable/disable |
| `requirements.txt` | Python deps |

---

## Quick Start

```bash
pip install -r requirements.txt
cp config.yml config.yml.local   # add your keys
python main.py                    # starts on port 8810
```

```bash
curl http://127.0.0.1:8810/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"hello"}]}'
```

---

## Merlin Pro Layer

Merlin Pro ($25/year) gives access to GPT-4, Gemini, DALL-E with no direct API keys. `merlin_api.py` puppets it as a local OpenAI-compat server on port 8811.

```bash
python merlin_api.py --init    # one-time setup (needs browser session token)
python merlin_api.py --serve   # start on port 8811
python merlin_api.py --models  # list available models
```

**Endpoints:** `/v1/chat/completions` (text), `/v1/images/generations` (DALL-E), `/v1/models`

**Auto mode:** set model to `merlin-auto` — Merlin's routing picks the best model for the task.

---

## Bifrost Integration

The router is a Bifrost provider at `https://localhost:8443`:

```
Client → Bifrost (8443) → nexus-router (8810) → best provider
```

Bifrost injects API keys server-side. No credentials ever reach the browser.

---

## Health & Failover

- Tracks success/failure/latency per provider continuously
- After 3 consecutive failures → provider excluded from routing
- Self-heals: failed providers re-enter rotation after backoff
- Every response includes `x-provider` and `x-model` headers

---

## Configuration

```yaml
# config.yml
server:
  host: "127.0.0.1"
  port: 8810

providers:
  ollama:
    endpoint: "http://localhost:11434/v1"
    model: "llama3"
    enabled: true
    is_local: true

  merlin:
    endpoint: "http://127.0.0.1:8811/v1"
    model: "gpt-6-luna"
    enabled: true
    is_local: true
```

All secrets live in `~/.config/nexus/secrets/nexus.env` — never in config files or code.

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
