from __future__ import annotations
import logging
import re
from typing import Iterator
import numpy as np
import onnxruntime as rt
from huggingface_hub import hf_hub_download
from kokoro_onnx import Kokoro
from voicebox.config import Settings

logger = logging.getLogger(__name__)

_SENTENCE_BOUNDARY_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9"“‘])')


def onnx_providers(device: str, available: list[str] | None = None) -> list[str]:
    """ONNX Runtime execution providers to try, in order.

    CPU is always kept as the last entry so a CUDA build that cannot reach a
    usable GPU degrades to CPU synthesis instead of failing to start.

    We select providers explicitly rather than relying on kokoro-onnx's own
    detection: it probes `importlib.util.find_spec("onnxruntime-gpu")`, which is
    a DISTRIBUTION name and never resolves as a module, so its GPU path is dead
    code. Its other hook, the ONNX_PROVIDER env var, replaces the list outright
    and therefore removes the CPU fallback.
    """
    cpu = "CPUExecutionProvider"

    if device != "cuda":
        return [cpu]

    installed = rt.get_available_providers() if available is None else available

    return ["CUDAExecutionProvider", cpu] if "CUDAExecutionProvider" in installed else [cpu]


def split_sentences(text: str) -> list[str]:
    parts: list[str] = []
    for paragraph in re.split(r"\n+", text):
        parts.extend(_SENTENCE_BOUNDARY_RE.split(paragraph.strip()))
    return [part.strip() for part in parts if part.strip()]


class TtsEngine:
    sample_rate = 24000

    def __init__(self, settings: Settings) -> None:
        self.default_voice = settings.default_voice
        try:
            # Download model and voices files from HuggingFace
            onnx_path = hf_hub_download(
                settings.tts_model, "model.onnx", revision=settings.tts_model_revision
            )
            voices_path = hf_hub_download(
                settings.tts_model, "voices.bin", revision=settings.tts_model_revision
            )
            providers = onnx_providers(settings.device)

            if providers == ["CPUExecutionProvider"]:
                # Kokoro's own constructor already defaults to CPU; leave the
                # stock path untouched so nothing changes for the CPU image.
                self.kokoro = Kokoro(onnx_path, voices_path)
            else:
                session = rt.InferenceSession(onnx_path, providers=providers)
                # What ONNX Runtime actually accepted, not what we asked for —
                # it silently drops a provider it cannot initialise, and that
                # difference is the whole question when a GPU build feels slow.
                logger.info("TTS: providers active=%s", session.get_providers())
                self.kokoro = Kokoro.from_session(session, voices_path)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load TTS model '{settings.tts_model}'. "
                f"If offline, ensure models are baked into the image / present in the HF cache. "
                f"Original error: {exc}"
            ) from exc

    def list_voice_ids(self) -> list[str]:
        return self.kokoro.get_voices()

    def sample_rate_for(self, voice: str | None = None) -> int:
        return self.sample_rate

    def synthesize_stream(
        self, text: str, voice: str | None = None, speed: float = 1.0
    ) -> Iterator[bytes]:
        sentences = split_sentences(text)
        if not sentences:
            raise ValueError("input text is empty")
        v = voice or self.default_voice
        for sentence in sentences:
            samples, _sr = self.kokoro.create(sentence, voice=v, speed=speed)
            pcm = np.clip(samples, -1.0, 1.0)
            pcm16 = (pcm * 32767.0).astype("<i2")
            yield pcm16.tobytes()
