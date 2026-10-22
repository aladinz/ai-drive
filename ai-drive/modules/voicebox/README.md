# VoiceBox module

Local, OpenAI-compatible speech server (STT via faster-whisper, TTS via Piper).
Source: https://github.com/agjs/voicebox (v0.2.16, MIT). The upstream README is
kept as `UPSTREAM-README.md`.

The prebuilt images (`ghcr.io/agjs/voicebox`, `agjs/voicebox`) are not public,
so this module builds the image locally from the bundled source.

## Layout

| Path | Purpose |
|---|---|
| `Dockerfile`, `src\`, `scripts\`, `pyproject.toml` | Upstream source used as the Docker build context |
| `docker-run.bat` | Builds `voicebox-local` and runs it in a visible window on `127.0.0.1:8790` |
| `docker-start-detached.bat` | Same image, started in the background as container `voicebox` (idempotent) |
| `config.json` | Module configuration (endpoint and API paths) |
| `client\voicebox_client.py` | Python client: `transcribeAudio()`, `speakText()` |

## Run

Requires Docker Desktop. The first build downloads the speech models and takes a while.

    ai-drive\modules\voicebox\docker-run.bat

Or run it in the background (no window to keep open; stop with `docker stop voicebox`):

    ai-drive\modules\voicebox\docker-start-detached.bat

`Start-WebUI-LMStudio.bat` calls the detached script automatically. VoiceBox takes about
15-25 seconds to load models after starting.
Check it is up:

    curl http://localhost:8790/v1/models

## Configuration

`config.json` is the single source of truth for the endpoint:

    {
      "name": "voicebox",
      "endpoint": "http://localhost:8790",
      "stt": "/v1/audio/transcriptions",
      "tts": "/v1/audio/speech",
      "voice": "af_heart"
    }

`voice` is optional (default voice for `speakText`).

## Voice quality

`docker-run.bat` starts VoiceBox with the Kokoro engine
(`VOICEBOX_TTS_ENGINE=kokoro`, CPU-only). Voices: `af_*`/`bf_*` female,
`am_*`/`bm_*` male (`GET /v1/models` lists all). The WebUI has a voice dropdown
in the top bar (saved in the browser). Reply text is cleaned (code, links,
markdown, emoji removed) before speaking. If you switch back to the `piper`
engine, use Piper voice ids (e.g. `en_US-amy-medium`) instead.

If you change the endpoint, also change the published port in `docker-run.bat`.
The server is bound to loopback only; there is no cloud fallback.

## Python client

    import sys
    sys.path.insert(0, r"ai-drive\modules\voicebox\client")
    from voicebox_client import transcribeAudio, speakText

    text = transcribeAudio(wav_bytes)   # audio bytes -> str
    audio = speakText("Hello")          # str -> WAV bytes (or format="mp3")

The WebUI reaches VoiceBox through `WebUI\serve_webui.py`, which proxies
`/voicebox/v1/*` to the configured endpoint.
