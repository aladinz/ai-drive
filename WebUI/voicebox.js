(function () {
  const TRANSCRIPTION_URL = "/voicebox/v1/audio/transcriptions";
  const SPEECH_URL = "/voicebox/v1/audio/speech";

  async function readError(response) {
    const details = await response.text();
    return details || `VoiceBox request failed with HTTP ${response.status}`;
  }

  async function transcribeAudio(audioBlob) {
    if (!(audioBlob instanceof Blob) || audioBlob.size === 0) {
      throw new TypeError("Audio input must be a non-empty Blob.");
    }

    const form = new FormData();
    form.append("model", "stt");
    form.append("response_format", "json");
    form.append("file", audioBlob, "voice-input.webm");

    const response = await fetch(TRANSCRIPTION_URL, { method: "POST", body: form });
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    const payload = await response.json();
    const text = typeof payload?.text === "string" ? payload.text.trim() : "";
    if (!text) {
      throw new Error("VoiceBox returned no transcription text.");
    }
    return text;
  }

  async function speakText(text, voice) {
    if (typeof text !== "string" || !text.trim()) {
      throw new TypeError("Text to speak must not be empty.");
    }

    const body = { model: "tts", input: text.trim(), response_format: "wav" };
    if (voice) body.voice = voice;

    const response = await fetch(SPEECH_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    const audio = await response.blob();
    if (!audio.type.toLowerCase().startsWith("audio/")) {
      throw new Error(`VoiceBox returned an unexpected audio type: ${audio.type || "unknown"}`);
    }
    if (audio.size === 0) {
      throw new Error("VoiceBox returned empty audio.");
    }
    return prependWavSilence(audio, 1.0);
  }

  /**
   * Prepends a duration of lead-in buffer to a PCM WAV blob so that
   * Bluetooth headphones, monitor speakers, and DACs have time to wake up
   * and un-mute before the first spoken words begin.
   * Includes a sub-audible micro-waveform (-60dB at 30Hz) to reliably trigger
   * hardware silence suppression and noise gates that would ignore pure zeroes.
   */
  async function prependWavSilence(wavBlob, seconds = 1.0) {
    if (!wavBlob || wavBlob.size < 44 || seconds <= 0) {
      return wavBlob;
    }

    try {
      const buffer = await wavBlob.arrayBuffer();
      const view = new DataView(buffer);

      // Verify standard RIFF WAVE
      const riff = String.fromCharCode(view.getUint8(0), view.getUint8(1), view.getUint8(2), view.getUint8(3));
      const wave = String.fromCharCode(view.getUint8(8), view.getUint8(9), view.getUint8(10), view.getUint8(11));
      if (riff !== "RIFF" || wave !== "WAVE") {
        return wavBlob;
      }

      // Parse chunks to locate 'fmt ' and 'data'
      let offset = 12;
      let fmtFound = false;
      let numChannels = 1;
      let sampleRate = 24000;
      let bitsPerSample = 16;
      let blockAlign = 2;
      let dataOffset = -1;
      let dataSize = 0;

      while (offset + 8 <= buffer.byteLength) {
        const chunkId = String.fromCharCode(
          view.getUint8(offset),
          view.getUint8(offset + 1),
          view.getUint8(offset + 2),
          view.getUint8(offset + 3)
        );
        const chunkSize = view.getUint32(offset + 4, true);

        if (chunkId === "fmt ") {
          fmtFound = true;
          numChannels = view.getUint16(offset + 8 + 2, true);
          sampleRate = view.getUint32(offset + 8 + 4, true);
          blockAlign = view.getUint16(offset + 8 + 12, true);
          bitsPerSample = view.getUint16(offset + 8 + 14, true);
        } else if (chunkId === "data") {
          dataOffset = offset + 8;
          dataSize = chunkSize;
          break;
        }

        offset += 8 + chunkSize;
      }

      if (!fmtFound || dataOffset === -1) {
        return wavBlob;
      }

      const totalSamples = Math.round(sampleRate * seconds);
      const silenceBytes = totalSamples * blockAlign;

      const totalNewBytes = buffer.byteLength + silenceBytes;
      const newBuffer = new ArrayBuffer(totalNewBytes);
      const newBytes = new Uint8Array(newBuffer);
      const origBytes = new Uint8Array(buffer);

      // 1. Copy header up to start of data payload
      newBytes.set(origBytes.subarray(0, dataOffset), 0);

      // 2. Insert lead-in:
      // For 16-bit PCM, insert a 30Hz sine wave at peak amplitude 32 (~ -60dB).
      // This is imperceptible to human ears, but non-zero to hardware noise gates,
      // forcing Bluetooth/WASAPI endpoints to wake up and ramp up volume.
      const newView = new DataView(newBuffer);
      if (bitsPerSample === 16) {
        const freq = 30;
        for (let i = 0; i < totalSamples; i++) {
          const sampleVal = Math.round(32 * Math.sin(2 * Math.PI * freq * (i / sampleRate)));
          for (let ch = 0; ch < numChannels; ch++) {
            const bytePos = dataOffset + (i * numChannels + ch) * 2;
            newView.setInt16(bytePos, sampleVal, true);
          }
        }
      } else if (bitsPerSample === 8) {
        newBytes.fill(128, dataOffset, dataOffset + silenceBytes);
      } else {
        newBytes.fill(0, dataOffset, dataOffset + silenceBytes);
      }

      // 3. Copy original PCM data
      newBytes.set(origBytes.subarray(dataOffset), dataOffset + silenceBytes);

      // 4. Update RIFF chunk size and data chunk size in the new buffer
      const newRiffSize = (view.getUint32(4, true) + silenceBytes) >>> 0;
      newView.setUint32(4, newRiffSize, true);

      const newDataSize = (dataSize + silenceBytes) >>> 0;
      newView.setUint32(dataOffset - 4, newDataSize, true);

      return new Blob([newBuffer], { type: wavBlob.type || "audio/wav" });
    } catch {
      // Fallback cleanly to the original audio if parsing fails
      return wavBlob;
    }
  }

  window.VoiceBox = Object.freeze({ transcribeAudio, speakText });
})();
