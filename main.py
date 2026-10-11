import os
import yaml
import logging
import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
import httpx
from httpx_socks import AsyncProxyTransport
from pydantic import BaseModel

# Load Configuration — env var overrides, no hardcoded paths
NEXUS_HOME  = os.environ.get("NEXUS_HOME", str(Path.home() / "NeXuS"))
CONFIG_PATH = os.environ.get(
    "NEXUS_AI_ROUTER_CONFIG",
    str(Path(__file__).parent / "config.yml"),
)
with open(CONFIG_PATH, "r") as f:
    config = yaml.safe_load(f)

# Logger Setup
_log_default = str(Path(NEXUS_HOME) / "logs" / "nexus-ai-router.log")
LOG_FILE = os.environ.get("NEXUS_AI_ROUTER_LOG") \
           or config.get("logging", {}).get("file") \
           or _log_default
Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("nexus-ai-router")
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(LOG_FILE)
formatter = logging.Formatter('%(asctime)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

def log_completion(model: str):
    logger.info(f"Completion processed | Model: {model}")

app = FastAPI(title="NeXuS AI Router")

# Models for OpenAI compatibility
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: Optional[str] = None
    messages: List[ChatMessage]
    stream: Optional[bool] = False
    temperature: Optional[float] = 0.7

async def get_client(is_local: bool):
    if is_local:
        return httpx.AsyncClient()
    else:
        proxy_url = config.get("proxy", {}).get("socks")
        transport = AsyncProxyTransport.from_url(proxy_url)
        return httpx.AsyncClient(transport=transport)

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    providers = config.get("providers", {})
    
    # Priority: Enabled local providers first, then enabled cloud providers
    ordered_providers = []
    # Local first
    for name, p in providers.items():
        if p.get("enabled") and p.get("is_local"):
            ordered_providers.append((name, p))
    # Cloud fallback
    for name, p in providers.items():
        if p.get("enabled") and not p.get("is_local"):
            ordered_providers.append((name, p))

    if not ordered_providers:
        raise HTTPException(status_code=503, detail="No enabled AI providers available.")

    last_error = None
    for name, provider in ordered_providers:
        try:
            async with await get_client(provider.get("is_local")) as client:
                payload = request.dict(exclude_none=True)
                # Override model if specified in config for the provider
                if "model" in provider:
                    payload["model"] = provider["model"]

                headers = {
                    "Authorization": f"Bearer {provider.get('key')}",
                    "Content-Type": "application/json"
                }
                
                response = await client.post(
                    f"{provider.get('endpoint').rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=60.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    # Add Provenance
                    data["provenance"] = {
                        "provider": name,
                        "endpoint": provider.get("endpoint"),
                        "local": provider.get("is_local"),
                        "timestamp": datetime.datetime.utcnow().isoformat()
                    }
                    log_completion(payload.get("model", "unknown"))
                    return data
                else:
                    last_error = f"Provider {name} returned {response.status_code}: {response.text}"
                    continue
        except Exception as e:
            last_error = f"Error with provider {name}: {str(e)}"
            continue

    raise HTTPException(status_code=502, detail=f"All providers failed. Last error: {last_error}")

@app.get("/health")
async def health():
    return {"status": "operational", "timestamp": datetime.datetime.utcnow().isoformat()}

@app.get("/providers")
async def list_providers():
    return {
        name: {"enabled": p.get("enabled"), "local": p.get("is_local"),
               "model": p.get("model")}
        for name, p in config.get("providers", {}).items()
    }

@app.get("/ui", response_class=HTMLResponse)
async def web_ui():
    providers = config.get("providers", {})
    model_opts = "\n".join(
        f'<option value="{p.get("model","")}">{name} — {p.get("model","")}</option>'
        for name, p in providers.items()
        if p.get("enabled") and p.get("model")
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NeXuS AI Router</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0d0d0d;color:#c9d1d9;font-family:monospace;display:flex;flex-direction:column;height:100vh}}
  header{{background:#161b22;border-bottom:1px solid #30363d;padding:12px 20px;display:flex;align-items:center;gap:12px}}
  header h1{{font-size:1rem;color:#58a6ff;letter-spacing:2px}}
  select,button,textarea{{background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;font-family:monospace}}
  select{{padding:6px 10px;font-size:.85rem}}
  #log{{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px}}
  .msg{{padding:10px 14px;border-radius:6px;max-width:80%;white-space:pre-wrap;line-height:1.5;font-size:.88rem}}
  .user{{background:#1f3a5f;align-self:flex-end;color:#cdd9e5}}
  .assistant{{background:#161b22;border:1px solid #30363d;align-self:flex-start;color:#adbac7}}
  .meta{{font-size:.7rem;color:#484f58;margin-top:4px}}
  footer{{border-top:1px solid #30363d;padding:12px;display:flex;gap:8px}}
  textarea{{flex:1;resize:none;padding:8px;font-size:.88rem;height:60px}}
  button{{padding:8px 18px;background:#238636;color:#fff;border:none;cursor:pointer;border-radius:4px;font-size:.85rem}}
  button:hover{{background:#2ea043}}
  button:disabled{{background:#333;cursor:not-allowed}}
</style>
</head>
<body>
<header>
  <h1>⬡ NEXUS AI ROUTER</h1>
  <select id="model">{model_opts}</select>
  <span id="status" style="font-size:.75rem;color:#484f58">ready</span>
</header>
<div id="log"></div>
<footer>
  <textarea id="prompt" placeholder="Send a message… (Ctrl+Enter to send)"></textarea>
  <button id="send" onclick="sendMsg()">Send</button>
</footer>
<script>
const log   = document.getElementById('log');
const input = document.getElementById('prompt');
const btn   = document.getElementById('send');
const stat  = document.getElementById('status');

function addMsg(role, text, meta) {{
  const d = document.createElement('div');
  d.className = 'msg ' + role;
  d.textContent = text;
  if (meta) {{
    const m = document.createElement('div');
    m.className = 'meta';
    m.textContent = meta;
    d.appendChild(m);
  }}
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
}}

async function sendMsg() {{
  const prompt = input.value.trim();
  if (!prompt) return;
  const model  = document.getElementById('model').value;
  input.value  = '';
  btn.disabled = true;
  stat.textContent = 'thinking…';
  addMsg('user', prompt);
  try {{
    const res = await fetch('/v1/chat/completions', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{
        model,
        messages: [{{role: 'user', content: prompt}}]
      }})
    }});
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
    const text = data.choices?.[0]?.message?.content ?? JSON.stringify(data);
    const prov = data.provenance;
    const meta = prov ? `via ${{prov.provider}} · ${{prov.endpoint ?? ''}}` : '';
    addMsg('assistant', text, meta);
    stat.textContent = 'ready';
  }} catch(e) {{
    addMsg('assistant', '⚠ ' + e.message);
    stat.textContent = 'error';
  }} finally {{
    btn.disabled = false;
    input.focus();
  }}
}}

input.addEventListener('keydown', e => {{
  if (e.ctrlKey && e.key === 'Enter') sendMsg();
}});
</script>
</body>
</html>"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config["server"]["host"], port=config["server"]["port"])
