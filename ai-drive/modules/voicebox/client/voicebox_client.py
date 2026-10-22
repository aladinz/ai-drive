import json
import math
import os
import re
import secrets
import struct
import urllib.error
import urllib.request

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json"
)
REQUEST_TIMEOUT_SECONDS = 120


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Could not read VoiceBox configuration at {CONFIG_PATH}: {exc}") from exc

    if not isinstance(config, dict):
        raise RuntimeError(f"VoiceBox configuration must be a JSON object: {CONFIG_PATH}")

    values = {}
    for key in ("endpoint", "stt", "tts"):
        value = config.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f'VoiceBox config key "{key}" must be a non-empty string.')
        values[key] = value.strip()
    values["endpoint"] = values["endpoint"].rstrip("/")
    voice = config.get("voice")
    values["voice"] = voice.strip() if isinstance(voice, str) and voice.strip() else None
    return values


_CONFIG = load_config()
VOICEBOX_BASE_URL = _CONFIG["endpoint"]
STT_PATH = _CONFIG["stt"]
TTS_PATH = _CONFIG["tts"]
DEFAULT_VOICE = _CONFIG["voice"]
VOICEBOX_ENDPOINTS = {STT_PATH, TTS_PATH}


_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]")


def cleanSpeechText(text):
    """Strip markdown, links, code and emoji so replies are spoken naturally."""
    text = re.sub(r"```[\s\S]*?```", " ", text or "")
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"^\s{0,3}(#{1,6}|>|[-*+]|\d+[.)])\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*\|?[\s:|-]{3,}\|?\s*$", " ", text, flags=re.M)
    text = text.replace("|", ", ")
    text = re.sub(r"[*_~#]+", "", text)
    text = _EMOJI.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def proxyVoiceboxRequest(endpoint, body, content_type):
    if endpoint not in VOICEBOX_ENDPOINTS:
        raise ValueError(f"Unsupported VoiceBox endpoint: {endpoint}")

    request = urllib.request.Request(
        f"{VOICEBOX_BASE_URL}{endpoint}",
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return (
                response.status,
                response.headers.get("Content-Type", "application/octet-stream"),
                response.read(),
            )
    except urllib.error.HTTPError as exc:
        return (
            exc.code,
            exc.headers.get("Content-Type", "application/json; charset=utf-8"),
            exc.read(),
        )
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach VoiceBox at {VOICEBOX_BASE_URL}: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise RuntimeError(
            f"VoiceBox request timed out after {REQUEST_TIMEOUT_SECONDS} seconds."
        ) from exc


def _request_voicebox(endpoint, body, content_type):
    status, response_type, response_body = proxyVoiceboxRequest(endpoint, body, content_type)
    if status < 200 or status >= 300:
        details = response_body.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"VoiceBox request failed with HTTP {status}"
            + (f": {details}" if details else "")
        )
    return response_type, response_body


def transcribeAudio(audio_bytes, filename="audio.wav", content_type="audio/wav"):
    if not audio_bytes:
        raise ValueError("Audio input must not be empty.")

    boundary = f"----VoiceBoxBoundary{secrets.token_hex(16)}"
    safe_filename = os.path.basename(filename).replace('"', "_")
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\nstt\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"response_format\"\r\n\r\njson\r\n".encode(),
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{safe_filename}\"\r\nContent-Type: {content_type}\r\n\r\n"
        ).encode(),
        audio_bytes,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    response_type, response_body = _request_voicebox(
        STT_PATH,
        b"".join(parts),
        f"multipart/form-data; boundary={boundary}",
    )

    if "json" not in response_type.lower():
        raise RuntimeError(f"VoiceBox returned an unexpected transcription type: {response_type}")
    try:
        payload = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("VoiceBox returned invalid transcription JSON.") from exc
    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("VoiceBox returned no transcription text.")
    return text.strip()


def speakText(text, response_format="wav", voice=None):
    text = cleanSpeechText(text) if isinstance(text, str) else text
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Text to speak must not be empty.")
    if response_format not in {"mp3", "wav"}:
        raise ValueError("VoiceBox audio format must be 'mp3' or 'wav'.")

    body = {
        "model": "tts",
        "input": text.strip(),
        "response_format": response_format,
    }
    voice = voice or DEFAULT_VOICE
    if voice:
        body["voice"] = voice
    payload = json.dumps(body).encode("utf-8")
    response_type, audio_bytes = _request_voicebox(
        TTS_PATH,
        payload,
        "application/json",
    )
    if not response_type.lower().startswith("audio/"):
        raise RuntimeError(f"VoiceBox returned an unexpected audio type: {response_type}")
    if not audio_bytes:
        raise RuntimeError("VoiceBox returned empty audio.")
    if response_format == "wav":
        audio_bytes = _prepend_wav_silence(audio_bytes, 1.0)
    return audio_bytes


def _prepend_wav_silence(wav_bytes: bytes, seconds: float = 1.0) -> bytes:
    """Prepend leading buffer to WAV bytes to give audio devices/Bluetooth time to wake up and un-mute."""
    if len(wav_bytes) < 44 or seconds <= 0:
        return wav_bytes
    if not (wav_bytes.startswith(b"RIFF") and wav_bytes[8:12] == b"WAVE"):
        return wav_bytes

    offset = 12
    fmt_found = False
    channels = 1
    sample_rate = 24000
    bits_per_sample = 16
    block_align = 2
    data_offset = -1
    data_size = 0

    while offset + 8 <= len(wav_bytes):
        chunk_id = wav_bytes[offset : offset + 4]
        chunk_size = struct.unpack("<I", wav_bytes[offset + 4 : offset + 8])[0]
        if chunk_id == b"fmt ":
            fmt_found = True
            channels, sample_rate = struct.unpack("<HI", wav_bytes[offset + 10 : offset + 16])
            block_align, bits_per_sample = struct.unpack("<HH", wav_bytes[offset + 20 : offset + 24])
        elif chunk_id == b"data":
            data_offset = offset + 8
            data_size = chunk_size
            break
        offset += 8 + chunk_size

    if not fmt_found or data_offset == -1:
        return wav_bytes

    total_samples = int(round(sample_rate * seconds))
    silence_bytes_len = total_samples * blockAlign if 'blockAlign' in locals() else total_samples * block_align

    if bits_per_sample == 16:
        pcm = bytearray()
        for i in range(total_samples):
            val = int(round(32 * math.sin(2 * math.pi * 30 * (i / sample_rate))))
            pcm.extend(struct.pack("<h", val) * channels)
        silence = bytes(pcm)
    elif bits_per_sample == 8:
        silence = b"\x80" * silence_bytes_len
    else:
        silence = b"\x00" * silence_bytes_len

    new_riff_size = struct.unpack("<I", wav_bytes[4:8])[0] + len(silence)
    new_data_size = data_size + len(silence)

    new_wav = (
        wav_bytes[:4]
        + struct.pack("<I", new_riff_size)
        + wav_bytes[8 : data_offset - 4]
        + struct.pack("<I", new_data_size)
        + silence
        + wav_bytes[data_offset:]
    )
    return new_wav
