# nexus-ai-router - Action Report

**Project:** /home/user/NeXuS/projects/nexus-ai-router
**Created:** 2026-10-04

---


## NeXuS AI Router — Merlin Integration + Web UI (2026-10-04 05:15)

**Status:** ✅ TESTED (Merlin reachable, ChatGPT response confirmed)

**What:** Added Merlin Pro as a puppeted API provider to the existing NeXuS AI Router, wired router into Bifrost as default provider, added web UI.

**Why:** Merlin Pro at 25/year gives access to GPT-4, Gemini, DeepSeek, DALL-E via their arcane API — no direct API keys needed. Router becomes multi-model with no added cost.

**How:**
- Reverse engineered Merlin API via DevTools: POST /arcane/api/v2/thread/unified
- Firebase key extracted from public JS bundle (not a secret)
- merlin_api.py: CLI + OpenAI-compat server on port 8811
- Firebase token refresh automatic — never expires
- Router config: merlin provider pointing to localhost:8811
- Bifrost: nexus-router added as default provider
- Web UI at http://127.0.0.1:8810/ui — dark theme, model selector, provenance display
- Fixed hardcoded paths in main.py per CLAUDE.md protocol

**Files:**
- ~/NeXuS/projects/nexus-ai-router/merlin_api.py
- ~/NeXuS/projects/nexus-ai-router/main.py (updated)
- ~/NeXuS/projects/nexus-ai-router/config.yml (updated)
- ~/NeXuS/bifrost-bridge/server/nexus_web_server.py (nexus-router added)

**Testing:** Merlin reachable through router, ChatGPT response confirmed end-to-end

**Dependencies:** Python 3, requests, FastAPI, uvicorn, Merlin Pro account

---


## Pre-compact snapshot (2026-10-04 08:40) (2026-10-04 08:40)

**Status:** 🔵 AUTO-COMPACT SNAPSHOT
**What:** Context saved automatically before Claude compacted the conversation.
**When:** 2026-10-04 08:40
**Project detected:** /home/user/NeXuS/projects/nexus-ai-router


---

