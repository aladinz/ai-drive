import io
import json
import os
import sys
import urllib.error
import urllib.request
import wave

try:
    import msvcrt
except ImportError:
    msvcrt = None

try:
    import numpy as np
    import sounddevice as sd
except ImportError:
    np = None
    sd = None

VOICEBOX_CLIENT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ai-drive", "modules", "voicebox", "client",
)
sys.path.insert(0, VOICEBOX_CLIENT_DIR)
from voicebox_client import speakText, transcribeAudio  # noqa: E402

CHAT_API_BASE = os.getenv("LMSTUDIO_API_BASE", "http://127.0.0.1:1234/v1").rstrip("/")
CHAT_MODEL = os.getenv("LMSTUDIO_MODEL", "mistral-7b-instruct-v0.3")
REQUEST_TIMEOUT_SECONDS = int(os.getenv("LMSTUDIO_TIMEOUT", "60"))
PUSH_TO_TALK_SECONDS = 6
SAMPLE_RATE = 16000
CHANNELS = 1
SYSTEM_PROMPT = "You are a calm, helpful assistant."
EXIT_COMMANDS = {"quit", "exit", "stop"}


def http_json(url, payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Local chat request failed with HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach local chat service at {url}: {exc.reason}") from exc


def call_local_chat(prompt):
    payload = {
        "model": CHAT_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    }
    data = http_json(f"{CHAT_API_BASE}/chat/completions", payload)
    try:
        reply = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise RuntimeError(f"Unexpected local chat response: {json.dumps(data, indent=2)}") from exc
    if not reply:
        raise RuntimeError("Local chat service returned an empty reply.")
    print(f"Assistant: {reply}")
    return reply


def record_audio_wav_bytes(seconds):
    if sd is None or np is None:
        raise RuntimeError(
            "Push-to-talk requires numpy and sounddevice in this Python environment."
        )

    frame_count = max(1, int(seconds * SAMPLE_RATE))
    print(f"Recording for {seconds} seconds...")
    audio = sd.rec(frame_count, samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32")
    sd.wait()

    pcm = np.int16(np.clip(audio, -1.0, 1.0) * 32767)
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(CHANNELS)
            wav_file.setsampwidth(2)
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(pcm.tobytes())
        return buffer.getvalue()


def push_to_talk_once():
    audio_bytes = record_audio_wav_bytes(PUSH_TO_TALK_SECONDS)
    transcript = transcribeAudio(audio_bytes, filename="voice-input.wav")
    print(f"You said: {transcript}")
    return transcript


def play_reply(text):
    audio_bytes = speakText(text)
    if sys.platform != "win32":
        raise RuntimeError("Audio playback in this command-line assistant requires Windows.")
    import winsound

    winsound.PlaySound(audio_bytes, winsound.SND_MEMORY)


def read_action_key():
    if msvcrt is None:
        choice = input("Action [t=text, v=push-to-talk, q=quit]: ").strip().lower()
        return choice[:1] if choice else ""

    print("Action: [T]ype  [V]oice push-to-talk  [Q]uit", end="", flush=True)
    key = msvcrt.getwch().lower()
    print(f" -> {key}")
    return key


def read_text_message():
    try:
        return input("You > ").strip()
    except EOFError:
        return ""


def validate_chat_backend():
    data = http_json(f"{CHAT_API_BASE}/models")
    models = [
        item.get("id", "")
        for item in data.get("data", [])
        if isinstance(item, dict) and item.get("id")
    ]
    if not models:
        raise RuntimeError("Local chat service returned no models.")
    if CHAT_MODEL not in models:
        raise RuntimeError(
            f"Configured chat model '{CHAT_MODEL}' is not loaded. "
            f"Available models: {', '.join(models)}"
        )


def main():
    try:
        validate_chat_backend()
    except RuntimeError as exc:
        print(f"Startup check failed: {exc}")
        return

    print("Local chat is ready. Voice input and replies use VoiceBox.")
    print("Use V for push-to-talk, T to type, or Q to quit.\n")

    while True:
        try:
            action = read_action_key()
            if action == "q":
                print("Exiting.")
                break
            if action == "t":
                user_text = read_text_message()
            elif action == "v":
                user_text = push_to_talk_once()
            else:
                print("Unknown action. Press T, V, or Q.\n")
                continue

            if not user_text:
                print("No input captured.\n")
                continue
            if user_text.lower() in EXIT_COMMANDS:
                print("Exiting.")
                break

            reply = call_local_chat(user_text)
            play_reply(reply)
            print()
        except KeyboardInterrupt:
            print("\nExiting.")
            break
        except RuntimeError as exc:
            print(f"Error: {exc}\n")


if __name__ == "__main__":
    main()
