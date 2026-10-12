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

## Merlin API: Full Debug + Fix Session (2026-10-11 22:10)

**Status:** ✅ TESTED — `python3 merlin_api.py "say hi"` → `Hi!` confirmed end-to-end

**What:** Audited the live nexus-ai-router GitHub repo, identified every gap between the README and the actual code, then fixed the Merlin puppet layer through four iterative commits — each one informed by real DevTools captures from the user's browser session. Merlin was completely non-functional before this session (every call returned empty string or INTERNAL_SERVER_ERROR). It is now fully working.

---

### Why This Was Broken

The `merlin_api.py` file had accumulated four separate bugs, all of which had to be fixed together before anything could work:

1. **SSE parser read the wrong field path.** The code did `data.get("content", "")` where `data = ev.get("data", ev)` — so it was looking at `ev.data.content`. The actual Merlin event format puts the text in `ev.data.text` when `ev.data.type == "text"`. Every response came back as empty string because the content was always in the wrong place.

2. **`gravity_context` was `{}`.** Merlin's API requires a populated `gravity_context` object. Sending an empty dict caused an `INTERNAL_SERVER_ERROR` on every request before any content was even generated. This was a known issue from the prior session but the correct structure was unknown without a live capture.

3. **The entire request body structure was wrong.** The code sent `sessionId`, `device`, and `user` as top-level fields alongside `chatId`. The actual Merlin API puts all three of those *inside* `gravity_context`. The top level only contains `chatId`, `language`, `message`, `metadata`, `mode`, `model`, and `gravity_context`. This structural mismatch meant Merlin was receiving a malformed request on every call.

4. **The LibreWolf cookies path was hardcoded** to a specific machine-unique profile ID (`zqiwk7i6.default-release`). This would break silently on any other node since the profile directory name is randomly generated per installation. Cookies would fail to load and requests would fail Cloudflare's bot check.

---

### What Was Done — Commit by Commit

#### Commit 1: `e25c812` — Fix Merlin SSE parser, gravity_context, and LibreWolf path

This was the initial pass based on prior session notes and static analysis of the code.

**SSE parser (first attempt):** Prior notes said the SSE field path was `data.data.text`. The parser was rewritten to traverse `ev["data"]["data"]["text"]` with a fallback to `ev["data"]["content"]`. This was directionally right (nested path) but the wrong field name — `text` vs `content` at the inner level, and the nesting depth was off. Still not working yet but closer.

**gravity_context:** The `{}` was replaced with a `_load_gravity_context(cfg)` call that returned a default dict shaped like what the Merlin browser extension sends from the chat page:
```python
{"tabUrl": "https://www.getmerlin.in/chat", "tabTitle": "Merlin | #1 AI Assistant", "selectedText": "", "activeTab": True}
```
This was still wrong structurally (the real gravity_context is not URL/title-based) but it was better than empty and would not cause the same immediate 500 error.

**LibreWolf path:** Removed the hardcoded `zqiwk7i6.default-release` string. Replaced with `_find_librewolf_cookies()` which: (a) checks `$LIBREWOLF_COOKIES_DB` env var first, (b) globs `~/.librewolf/**/cookies.sqlite` and `~/.config/librewolf/**/*.default*/cookies.sqlite` to find the profile dynamically. Works on any node regardless of profile ID.

**Headers:** Added `x-merlin-version: web-merlin`, `x-request-timestamp` (ISO8601 with timezone), and proper `Accept: text/event-stream` headers to match what the real browser sends. These are required for Cloudflare to pass the request through.

**content-type detection:** The `content_type` variable was being read *after* the `with urllib.request.urlopen(...)` block closed, meaning `resp` was a closed object. Moved `resp.headers.get("Content-Type", "")` capture inside the `with` block where `resp` is still valid. Also added `raw.startswith("data:")` as a fallback trigger for SSE parsing since Merlin always returns SSE regardless of the Content-Type header value.

**README:** Removed four false claims: (1) dynamic health scoring with `priority + latency_ms + failure_count × 100` formula — the code does static ordering, not scoring; (2) per-provider latency tracking — not implemented; (3) "after 3 consecutive failures → excluded" — not implemented; (4) `x-provider`/`x-model` response headers — these are in the JSON body under `provenance`, not HTTP headers. Replaced with an honest status table marking those features as `🔴 Planned`. Added full Merlin setup section with step-by-step instructions for capturing `refresh_token` and `gravity_context` from LibreWolf DevTools.

**`--set-gravity` CLI flag:** Added `set_gravity(raw_json)` function and `--set-gravity JSON` CLI argument so captured DevTools values can be stored without re-running the full `--init` wizard. Also updated `--init` to prompt for `gravity_context` with instructions.

---

#### Commit 2: `a54da36` — Fix request body structure to match actual Merlin API

**Trigger:** User opened LibreWolf DevTools → Network → captured the real POST request body. This revealed the actual structure:

```json
{
  "attachments": [],
  "chatId": "84080ea1-...",
  "language": "AUTO",
  "message": {"childId": "...", "content": "...", "context": "", "id": "...", "parentId": "root"},
  "metadata": {"noTask": true, "isWebpageChat": false, "deepResearch": false, "proFinderMode": false, "merlinMagic": true},
  "mode": "UNIFIED_CHAT",
  "model": "gpt-6-luna",
  "gravity_context": {
    "sessionId": "84080ea1-...",
    "user": {"id": "2qCOj3AKSOez5OrWYI4EfO5HXCv1"},
    "device": {
      "ua": "Mozilla/5.0 (X11; Linux x86_64; rv:152.0)...",
      "browser": "web", "device_type": "desktop",
      "timezone": "Atlantic/Reykjavik", "locale": "en-US", "language": "en-US",
      "screen_width": 1600, "screen_height": 600,
      "viewport_width": 1600, "viewport_height": 600,
      "platform": "Linux x86_64"
    }
  }
}
```

**The structural revelation:** `gravity_context` is not a page-context blob (URL/title) — it is the combination of `sessionId` + `user` + `device` that the old code was sending at the top level. The entire `device` object, the `user` object, and the `sessionId` field are all *nested inside* `gravity_context`. The top-level request body is much simpler than the code was sending. Additionally, `gravity_context.sessionId` must equal `chatId` — they are the same UUID generated per-request.

**Changes made:**
- Replaced `_DEFAULT_GRAVITY` (URL/title blob) with `_DEFAULT_GRAVITY_DEVICE` — the device fingerprint sub-object populated with the actual values from the captured request (1600×600, rv:152.0, Atlantic/Reykjavik timezone)
- Replaced `_load_gravity_context(cfg)` with `_build_gravity_context(cfg, uid, session_id)` which assembles the correct nested structure at call time, injecting the dynamic `sessionId` (= `chatId`) and `user.id` per-request
- Removed `sessionId`, `device`, `user` from top-level body in both `chat()` and `generate_image()`
- `set_gravity()` updated to accept either the full `gravity_context` object or just the `device` sub-object — extracts `device` key if present, stores as `gravity_device` in config
- Stored the captured device fingerprint from the user's DevTools paste into `merlin.json` via `--set-gravity`

---

#### Commit 3: `ae9aee1` — Fix uid priority and default model

**Two small but critical issues found during verification:**

**uid priority:** The code used `cfg.get("merlin_id") or cfg.get("uid")`. The `merlin_id` field contains an internal Merlin UUID (`350d254a-...`). But the captured DevTools request showed `user.id: "2qCOj3AKSOez5OrWYI4EfO5HXCv1"` — which matches the `uid` field (Firebase UID), not `merlin_id`. Flipped the priority to `cfg.get("uid") or cfg.get("merlin_id")` so the Firebase UID is used first.

**default_model:** Config still had `gpt-4o` from the original setup. The captured request showed `"model": "gpt-6-luna"` — this is the actual model Merlin routes to by default in merlinMagic mode. Updated `merlin.json` and the code default to `gpt-6-luna`.

---

#### Commit 4: `50a94b2` — Fix SSE parser with actual observed event format

**Trigger:** Test call still returned empty string after all structural fixes. Built a raw debug script that captured the live SSE stream byte-by-byte and printed every non-progress event.

**What the live stream showed:**
```
{"content": "", "index": 1, "type": "text", "text": "Hi"}
{"content": "", "index": 1, "type": "text", "text": "!"}
{"content": " ", "eventType": "DONE"}
```

**The actual SSE format:**
- Text chunks: `ev.data.type == "text"` → content is in `ev.data.text`
- Done sentinel: `ev.data.eventType == "DONE"` → skip
- Progress events: `ev.data.type == "progress"` → skip
- The `ev.data.content` field is always empty string for content events (it appears to be a legacy/unused field)

**Previous attempts were all wrong:**
- Original code: `ev.data.content` — this field is always `""`
- First fix attempt: `ev.data.data.text` — this nesting level doesn't exist
- Correct path: `ev.data.text` when `ev.data.type == "text"`

The final parser is significantly simpler than all previous versions — just 4 lines of logic. Skip anything without `type == "text"`, collect `d["text"]`, skip DONE, join chunks.

**Confirmation:** `python3 merlin_api.py "say hi in one sentence"` → `Hi!` ✅

---

### Files Modified

| File | Changes |
|------|---------|
| `merlin_api.py` | SSE parser (4 rewrites → confirmed working), gravity_context structure, request body restructure, LibreWolf glob, headers, uid priority, --set-gravity flag |
| `README.md` | Honest status table, false claims removed, full Merlin setup + DevTools capture instructions |
| `~/.config/nexus/merlin.json` | `gravity_device` stored (11 fields from live capture), `default_model` → `gpt-6-luna` |

### Dependencies Confirmed Working

- Firebase token refresh: automatic via `refresh_token` in `merlin.json`
- LibreWolf cookies: auto-discovered via glob (profile `zqiwk7i6.default-release` found)
- `gravity_context`: built dynamically per-request from stored device fingerprint
- `merlinMagic: true` (auto mode): Merlin routes internally to best model — activated by `model=merlin-auto` or `model=auto`

### What Is Still Not Implemented (Honest)

- Dynamic health scoring (`priority + latency_ms + failure_count × 100`) — README now marks this as `🔴 Planned`
- Per-provider failure tracking / backoff after 3 failures — `🔴 Planned`
- Chimera task dispatch (text vs vision vs RAG routing) — `🔴 Planned`
- `x-provider` / `x-model` HTTP response headers — currently in JSON body under `provenance` only

---

