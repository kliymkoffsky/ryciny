"""Signal helpers, the same as Dsp.kt in the app."""

from __future__ import annotations

import io
import wave

import numpy as np

_TAPS = None


def _taps() -> np.ndarray:
    global _TAPS
    if _TAPS is None:
        n = 63
        cutoff = 7_200.0 / 48_000.0
        m = np.arange(n) - (n - 1) / 2.0
        sinc = np.where(m == 0, 2 * cutoff, np.sin(2 * np.pi * cutoff * m) / (np.pi * np.where(m == 0, 1, m)))
        window = 0.42 - 0.5 * np.cos(2 * np.pi * np.arange(n) / (n - 1)) + 0.08 * np.cos(4 * np.pi * np.arange(n) / (n - 1))
        h = sinc * window
        _TAPS = (h / h.sum()).astype(np.float32)
    return _TAPS


def decimate48to16(x: np.ndarray) -> np.ndarray:
    return np.convolve(x, _taps(), mode="same")[::3].astype(np.float32)


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0


def bark_pitch(x: np.ndarray, rate: int = 16_000) -> float:
    """Median fundamental of the loud frames by autocorrelation in 120–1500 Hz: a rough guide to the dog's size."""
    frame = 640
    frames = [x[i * frame:(i + 1) * frame] for i in range(len(x) // frame)]
    if not frames:
        return 0.0
    energies = [rms(f) for f in frames]
    loud = max(energies)
    min_lag, max_lag = rate // 1500, rate // 120
    pitches = []
    for f, e in zip(frames, energies):
        if e <= loud * 0.4:
            continue
        e0 = float(np.dot(f, f))
        if e0 <= 0:
            continue
        best, lag = 0.0, 0
        for lg in range(min_lag, max_lag + 1):
            r = float(np.dot(f[:-lg], f[lg:])) / e0
            if r > best:
                best, lag = r, lg
        if best > 0.35 and lag > 0:
            pitches.append(rate / lag)
    return float(sorted(pitches)[len(pitches) // 2]) if pitches else 0.0


def size_of(pitch: float) -> str:
    if pitch <= 0:
        return "?"
    if pitch < 380:
        return "duży"
    if pitch < 650:
        return "średni"
    return "mały"


def cosine(a, b) -> float:
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    return 0.0 if na == 0 or nb == 0 else float(np.dot(a, b) / (na * nb))


def mp3_bytes(x: np.ndarray, rate: int = 48_000) -> bytes:
    """A detection's recording: MP3 (plays everywhere, about 40 kB for 9 s); WAV if MP3 cannot be written here."""
    peak = max(float(np.max(np.abs(x))) if len(x) else 0.0, 1e-4)
    y = np.clip(x * min(0.9 / peak, 8.0), -1, 1).astype(np.float32)
    try:
        import soundfile as sf

        buf = io.BytesIO()
        sf.write(buf, y, rate, format="MP3", subtype="MPEG_LAYER_III", compression_level=0.25)
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return wav_bytes(x, rate)


def clip_ext(data: bytes) -> str:
    return ".wav" if data[:4] == b"RIFF" else ".mp3"


def wav_bytes(x: np.ndarray, rate: int, normalize: bool = True) -> bytes:
    """16-bit WAV; barks are made louder for listening, the microphone test is kept as recorded."""
    peak = max(float(np.max(np.abs(x))) if len(x) else 0.0, 1e-4)
    gain = min(0.9 / peak, 8.0) if normalize else 1.0
    pcm = (np.clip(x * gain, -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()
