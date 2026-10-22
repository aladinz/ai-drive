# Aladdin Local AI

A fully offline, portable AI assistant that runs from a USB drive. No cloud, no internet, no data leaving your machine. The entire stack — model server, web interface, chat history, personas, and memory — lives on the drive itself.

---

## Requirements

| Requirement | Notes |
|---|---|
| Windows 10/11 (64-bit) | The launcher is a `.bat` file; no Linux/macOS support |
| 8 GB RAM minimum | 16 GB recommended for smooth performance |
| Microsoft Edge or Google Chrome | Required for the File System Access API (persistent drive storage) |
| No installation needed | Everything runs directly from the drive |

---

## Drive Layout

```
E:\                              ← drive root (letter may vary)
├── Scripts\
│   ├── Start-AI.bat             ← LAUNCH THIS to start the app
├── Llamafile\
│   ├── llamafile-0.9.1.exe      ← local AI engine (self-contained)
│   └── run-engine.bat           ← engine wrapper (keeps window open on crash)
├── Models\
│   ├── qwen2.5-coder-7b-instruct-q4_k_m.gguf
│   └── Llama-3.1-8B-Lexi-Uncensored-V2-Q6_K.gguf
├── miniweb\
│   └── htdocs\
│       ├── index.html           ← web app shell
│       ├── app.js               ← all application logic
│       ├── style.css            ← dark purple design system
│       └── current_model.txt    ← written at startup, read by the UI
├── History\                     ← auto-created on first launch
│   ├── Memory\
│   │   └── memory.json          ← long-term memory items
│   ├── Chats\
│   │   └── chat-<id>.json       ← one file per conversation
│   ├── Config\
│   │   └── personas.json        ← custom personas
│   └── Logs\                    ← startup/runtime troubleshooting logs
├── Backups\
└── README.md                    ← this file
```

---

## How to Run

### Step 1 — Launch the app

Double-click:

```
E:\Scripts\Start-AI.bat
```

> The drive letter (`E:\`) is detected automatically using `%~d0`. The script works regardless of which drive letter Windows assigns.

---

### Step 2 — Select a model

A numbered menu appears in the terminal window:

```
============================================
   Aladdin Local AI  --  Model Selector
============================================

  [1]  Qwen 2.5 Coder 7B
  [2]  Llama 3.1 8B Lexi
   [3]  DarkIdol Llama 3.1 8B
    [4]  L3.1-RP-Hero-BigTalker 8B

      Press 1, 2, 3, or 4 to select:
```

| Model | Best for |
|---|---|
| **Qwen 2.5 Coder 7B** (Q4) | Code writing, debugging, technical questions |
| **Llama 3.1 8B Lexi** (Q6) | Creative writing, open-ended conversation, roleplay |
| **DarkIdol Llama 3.1 8B** (Q4_K_M) | Creative, direct, high-energy conversation |
| **L3.1-RP-Hero-BigTalker 8B** (Q4_k_m) | Roleplay-focused, expressive long-form dialogue |

---

### Step 3 — Wait for the engine

The launcher starts the **Aladdin AI Engine** window (llamafile model server) and then opens the dashboard.

- Qwen 2.5 Coder loads in roughly **60–120 seconds** from a USB drive
- Llama 3.1 8B Lexi loads in roughly **90–150 seconds** from a USB drive
- From an internal SSD, both models load significantly faster

---

### Step 4 — Use the app

Your browser opens automatically at:

```
http://127.0.0.1:8090/index.html
```

If it does not open, paste that URL into Edge or Chrome manually. Use the **Custom Aladdin UI** option in the launcher for live tools; the native llama.cpp UI does not execute web-search or stock-data tool calls.

---

### Step 5 — Connect portable storage (first time only)

Click the **floppy disk icon** (💾) in the top-right toolbar. A folder picker will appear — navigate to the drive root (e.g. `E:\`) and click **Select Folder**.

The browser will ask for read/write permission. Grant it.

The button will turn **green** when storage is connected. From this point:
- All chat history is auto-saved to `E:\History\Chats\`
- Memory items are saved to `E:\History\Memory\memory.json`
- Custom personas are saved to `E:\History\Config\personas.json`

On subsequent launches the browser automatically reconnects to the previously granted folder without prompting (one grant per browser profile per machine).

---

### Stopping the app

Close **either** terminal window. The AI engine stops when its window is closed.

---

## Features

### Voice Assistant (VoiceBox)

Replies are spoken with the Kokoro engine (natural-sounding, CPU-only). Pick a female or male voice
from the dropdown in the WebUI top bar (your choice is remembered); code, links, markdown and emoji
are removed before speaking. Voice replies are on by default; the 🔊/🔈 button toggles them.

| Voices | Ids |
|--------|-----|
| Female | `af_heart` (default), `af_bella`, `af_nicole`, `af_sarah`, `af_sky`, `bf_emma`, `bf_isabella` |
| Male | `am_adam`, `am_michael`, `am_puck`, `bm_george`, `bm_daniel` |

`af_`/`am_` are US accents, `bf_`/`bm_` are UK. `voice` in `config.json` sets the
default for the command-line assistant.

The WebUI and command-line assistant use the local VoiceBox speech server at
`http://localhost:8790`. VoiceBox handles speech-to-text and text-to-speech
through its OpenAI-compatible `/v1/audio/transcriptions` and
`/v1/audio/speech` endpoints. Voice audio is sent only to this local server;
there is no cloud speech fallback.

VoiceBox lives in the AI-Drive module `E:\ai-drive\modules\voicebox\` (registered in `E:\ai-drive\registry.json`). Its Python client is `client\voicebox_client.py` and exposes
`transcribeAudio()` and `speakText()`. The browser client is
`E:\WebUI\voicebox.js`; the WebUI server proxies its requests to the configured
VoiceBox URL to avoid browser cross-origin restrictions.

#### Launching the WebUI with LM Studio

1. Open **LM Studio**, load a model, and start its local server (port 1234).
2. Start **Docker Desktop**.
3. Run `E:\Scripts\Start-WebUI-LMStudio.bat`. It starts VoiceBox in the background
   (via `docker-start-detached.bat`), starts the WebUI server on port 8090 and opens
   `http://127.0.0.1:8090/index.html`.

The launcher does not check LM Studio. If Docker is not running, the WebUI still starts
but without voice. VoiceBox needs about 15-25 seconds to load, so wait a moment before the
first spoken reply. The WebUI uses the model named in `E:\WebUI\current_model_id.txt` if it is loaded.

#### Voice Assistant Setup

The VoiceBox image is not public, so it is built locally from source (done automatically on first start).
To start VoiceBox on its own, either run it in a visible window:

   E:\ai-drive\modules\voicebox\docker-run.bat

or in the background (stop with `docker stop voicebox`):

   E:\ai-drive\modules\voicebox\docker-start-detached.bat

The endpoint is configured in `E:\ai-drive\modules\voicebox\config.json`
(`endpoint`, `stt`, `tts`, optional `voice`). `docker-run.bat` starts the server with the Kokoro engine
(`VOICEBOX_TTS_ENGINE=kokoro`). Start VoiceBox before using voice features. The browser microphone requires
permission for the local WebUI address. The command-line assistant also needs
`numpy` and `sounddevice` for push-to-talk recording.

Run the command-line assistant from the drive root:

   cd /d E:\Voice-assistant
   python -u voice_chat.py

At runtime, `T` selects typed input, `V` records a six-second push-to-talk
clip, and `Q` quits. Voice replies are returned as WAV audio and played locally.

#### Command-line Chat Settings

The command-line assistant uses these optional environment variables for its
separate local chat backend:

| Variable | Default | Purpose |
|---|---|---|
| `LMSTUDIO_API_BASE` | `http://127.0.0.1:1234/v1` | Local chat API base URL |
| `LMSTUDIO_MODEL` | `mistral-7b-instruct-v0.3` | Chat model ID |
| `LMSTUDIO_TIMEOUT` | `60` | Chat request timeout in seconds |

### Chat
- Stream responses in real time
- Multiple simultaneous conversations (chat list in the sidebar)
- Pin important conversations to the top
- Auto-titles each chat from the first message
- Retry button if a response fails; auto-retries up to 3 times

### Personas
A **Persona** controls how the AI behaves via its system prompt.

Select the active persona from the **Persona:** dropdown in the top bar. The selection is saved per-chat.

**Built-in personas:**

| Persona | Behaviour |
|---|---|
| Default | Balanced, general-purpose assistant |
| Coder | Expert code assistant; concise, working code first |
| Companion | Warm, emotionally intelligent conversation partner |
| Analyst | Thoughtful reasoning, writing, research |
| DarkIdol | Bold, creative, direct assistant style |

**Custom personas:**

Click the **👤** button to open the Persona Manager. Enter a name and a system prompt, then click **Add persona**. Custom personas are saved to `E:\History\Config\personas.json` when portable storage is connected.

Built-in personas (**Default**, **Coder**, **Companion**, **Analyst**) are read-only in the UI. To change built-in prompts, edit the `BUILTIN_PERSONAS` array in `E:\miniweb\htdocs\app.js`.

> **Auto-selection:** When the model loads, the app automatically selects the best built-in persona for that model (Coder for Qwen, Companion for Lexi).

For the DarkIdol model, the app auto-selects the **DarkIdol** built-in persona and uses its default prompt.

### Long-term Memory
The AI can remember facts across all conversations.

**Chat commands:**
| Command | Effect |
|---|---|
| `Remember this: I prefer short answers` | Saves a memory item |
| `Show memory` | Displays all saved items |
| `Forget: short answers` | Removes items matching the phrase |
| `Forget all` | Clears all memory |

**Memory Manager (📖 button):** Full UI to add, delete individual items, or clear all. Memory items are injected into the system context of every request automatically.

Memory is saved to `E:\History\Memory\memory.json` when drive storage is connected.

### Chat History
All conversations are auto-saved to `E:\History\Chats\chat-<id>.json` whenever a message is sent. They are loaded back automatically on next launch.

The app also keeps a compact local browser backup of recent chats so your active session can be restored quickly after a page reload or temporary engine restart.

**Manual save/load (top-bar buttons):**
- **💾 Save** — export the current chat to a JSON file via a save dialog
- **📂 Load** — import a previously exported chat JSON file
- **↓ Export MD** — save the current chat as a Markdown file
- **🗑 Delete** — permanently delete the current chat

### File Attachments
Click **+** next to the input box to attach files for context. Supported formats include `.txt`, `.md`, `.js`, `.ts`, `.py`, `.json`, `.yaml`, `.html`, `.css`, `.pdf`, `.docx`, and more (max 1 MB text / 10 MB binary).

### Live Tools (Web Search & Stock Quotes)
When the chat goes through the WebUI server (`E:\WebUI\serve_webui.py`, port 8090, backed by LM Studio on port 1234), the model can call two tools defined in `E:\tools\aladdin_stock_tools.py`:

| Tool | Purpose |
|------|---------|
| `web_search(query)` | DuckDuckGo search (no API key): top 5 results with title, URL and snippet, 10 s timeout |
| `yahoo_finance(symbol, risk=0.015, account=0)` | yfinance quote as JSON: current price, previous close, day high/low, volume, average volume, 50/200-day averages, 52-week high/low, market cap, plus a computed breakout `setup` (see below). Invalid symbols return an error JSON. Quotes are cached per ticker for 10 s, so repeated calls in one turn make a single Yahoo request |

**Trade setup (computed in code, not by the LLM):** `yahoo_finance` adds a `setup` block. Entry = day high + $0.10 (requires volume ≥ 80% of average), stop = higher of `low × (1 − risk/2)` and price − 1.5×ATR (ATR defaults to high − low), target 1 = 52-week high, target 2 = lower of 52W high +8% and 2.5R, plus risk/reward. `status` is `VALID` (volume confirmed, R1 ≥ 1.0 and R2 ≥ 2.0), `WATCHLIST` (R:R passes but volume is light — entry only on a volume surge above the required level) or `NO_SETUP` (R:R too low).
- `risk` is the account risk fraction (default `0.015` = 1.5%); it also sets the stop buffer below the day's low (risk ÷ 2, so 1.5% → 0.75%). A value ≥ 1 is read as a percent (`2` → 2%).
- `account` (dollars, optional): when given, the setup adds `position_size_shares = account × risk ÷ (entry − stop)`, plus `risk_dollars` and `position_value`.

**Tool-name aliases:** if the model invents names, `serve_webui.py` rewrites them: `get_live_data`, `get_stock_data`, `fetch_price`, `calculate_triggers` and `setup` all run `yahoo_finance` (a missing symbol reuses the last ticker). The same applies when the model prints a tool call as plain text instead of calling it, even inside prose. Unknown names with a `symbol` or `query` argument go to `yahoo_finance` / `web_search`; other unknown names are ignored. `"null"`/empty arguments are dropped, and arguments a tool does not accept are ignored.

How it works: for non-streaming `POST /v1/chat/completions` requests whose last message mentions stocks, prices, news, search, etc., `serve_webui.py` adds the tool definitions, runs any tool calls the model makes (up to 3 rounds), feeds the results back, and returns the final answer. If the model repeats a call it already has results for, the server forces a plain-text answer. Other messages, streaming requests, or any failure in this path use the plain proxy. `app.js` is unchanged.

**Ticker shortcut:** a short message with a ticker and a trade word (entry, stop, target, trigger, setup, price, quote, volume, breakout), e.g. `NVDA entry trigger stop target with 1.5% risk`, is answered directly by the server from live data (about 10 s, under 1 s when cached) without asking the 8B model, which is unreliable at relaying tool output. The answer is a generic Markdown card built by `format_universal_card(symbol, quote, setup)` in `serve_webui.py`. It opens with three stoplights, each computed from the quote only, and each showing ⚪ N/A when its data is missing:

| Light | 🟢 | 🟡 | 🔴 |
|-------|----|----|----|
| Trend (price vs 20D/50D MA) | above both | above one | below both |
| 52-week position (% of range) | ≥ 80% | 50–80% | < 50% |
| Volume vs average | ≥ 80% | 50–80% | < 50% |

The card is a pure bullet list (no Markdown tables, one item per line, blank line between sections): **STOPLIGHTS** (trend, 52-week, volume), **PRICE ACTION** (price, day range, prev close, 20D/50D MA, 52-week range) and **SETUP** (status, entry, stop, target 1/2 with % gains, risk/share, reward, R:R ✅ PASS / ❌ FAIL, optional position size, note). The 20-day MA is computed from 2 months of price history (Yahoo only supplies the 50-day); if it is unavailable the 50-day is used for both. It works for any ticker and shows `N/A` for missing values. An `X% risk` in the message sets `risk`. `web_search` calls the model makes for such messages are rerouted to `yahoo_finance`.

**Setup** — install into the Python that runs the server (`E:\.venv-1`), then restart the server:
```
E:\.venv-1\Scripts\python.exe -m pip install duckduckgo-search yfinance pydantic
```
If `Tools disabled: ...` appears in the server console, a dependency is missing.

**Usage** — ask e.g. "What's the price and 52-week high of AAPL?" or "Search the web for ATRC news". Llama 3.1 8B sometimes ignores tools; naming the ticker or saying "search the web for…" helps.

Note: `aladdin_stock_tools.py` also follows the Open WebUI `Tools` format, so it can be imported into Open WebUI if you ever install it. The Aladdin portal itself is not Open WebUI and has no Admin panel.

---

## Troubleshooting

### Tools are not used / "Tools disabled" in the server console
Install `duckduckgo-search`, `yfinance` and `pydantic` into `E:\.venv-1` (see Live Tools), confirm `E:\tools\aladdin_stock_tools.py` exists, and restart `serve_webui.py`.

### No spoken reply
Check that the 🔊 button in the top bar is on (🔈 means off) and that `docker ps` lists
`voicebox`. A "Voice reply failed" message appears in the microphone status bar on errors.

### Chat error: "Conversation roles must alternate"
Fixed in the WebUI: failed replies are no longer sent back to the model. Press Ctrl+F5 to
load the latest script, or click **New Chat**.

### Voice input or replies cannot reach VoiceBox
Confirm VoiceBox is running at the configured local URL and that
`endpoint` in `E:\ai-drive\modules\voicebox\config.json` matches it. The WebUI
server displays VoiceBox connection errors in the microphone status bar.

### Command-line push-to-talk fails
Install recording dependencies in the same Python environment used to run the script:

   pip install numpy sounddevice

Then relaunch `E:\Voice-assistant\voice_chat.py`.

### The engine window closes immediately
The model file may be missing or the path is wrong. Check that `E:\Models\` contains both `.gguf` files. The **run-engine.bat** window stays open after a crash to show the error — read the message before pressing a key.

### "Connecting…" never changes in the browser
The engine may still be loading. Wait a full 2 minutes. If the status stays as "Offline" (red), close both windows and relaunch.

### Responses drop mid-stream
The app retries automatically up to 3 times. If it fails after 3 retries, a **Retry** button appears. This usually means the model ran out of memory (OOM) — try closing other applications to free RAM.

### Storage button stays grey (not green)
The browser did not receive permission for the folder. Click the 💾 button again and re-select the drive root. Make sure you are using Edge or Chrome — Firefox does not support the File System Access API.

### The app opens but history is empty on a new PC
Click the 💾 button and select the drive. History and memory are loaded from `E:\History\` (including `Chats`, `Memory`, and `Config`) immediately after you grant access.

### Chat history not persisting across reloads
First click the 💾 button and connect the drive root so chats save to `E:\History\Chats\`.

If chats still reset, clear old browser storage for this site once, reload, then reconnect portable storage and send one test message to recreate fresh local backup data.

### Custom persona disappeared after restart
Custom personas are loaded from `E:\History\Config\personas.json`. If only built-ins appear, the drive was not connected with write permission when the persona was created.

Click 💾, select the drive root again, then create the persona once more and verify `E:\History\Config\personas.json` exists.

---

## Technical Notes

- **llamafile 0.9.1** hosts the AI API (`/v1/chat/completions`) and its native web UI on the engine port (normally **8080**). The **Custom Aladdin UI** runs separately on port **8090** and sends chat requests through `serve_webui.py`, which executes tool calls. The native llama.cpp UI bypasses that tool handler, so tool requests may appear as JSON instead of running.
- `--no-mmap` forces the model into RAM rather than memory-mapping from disk, which is essential for USB drives and prevents random read errors.
- Engine launch fallback profiles improve stability on lower-RAM systems:
   - profile 1: `--no-mmap --ctx-size 2048`
   - profile 2: `--no-mmap --ctx-size 1024`
   - profile 3: `--ctx-size 1024` (mmap enabled)
- `max_tokens: 512` per reply keeps response generation fast and memory usage low.
- Drive handle persistence uses **IndexedDB** so the File System Access API permission only needs to be granted once per browser profile per machine.
- All storage operations use the **File System Access API** (`showDirectoryPicker`, `createWritable`). No server-side code writes to disk.
- The LM Studio portal path (`E:\WebUI\serve_webui.py`) serves the UI on port **8090**, proxies `/v1/*` to LM Studio (port 1234) and `/voicebox/v1/*` to VoiceBox, and runs the tool-calling loop described under Live Tools.
- The app restores from a compact local chat backup on startup, then syncs with drive-backed chat files.

---

## Backup

- Backup location: `C:\E-Backup`
- Verification status: `BackupExists = True`
- Models folder excluded from this backup: `C:\E-Backup\Models` is not present
