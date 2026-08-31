"""Benchmark Whisper-small vs Parakeet-v3 on this machine (RTF + transcript)."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import soundfile as sf

FIXTURE = Path("tests/e2e/fixtures/two_speaker_meeting.wav")


def load_audio() -> tuple[np.ndarray, float]:
    audio, sr = sf.read(FIXTURE, dtype="float32")
    if audio.ndim > 1:
        audio = audio[:, 0]
    if sr != 16000:
        raise SystemExit(f"fixture is {sr} Hz, expected 16000")
    return np.ascontiguousarray(audio), len(audio) / sr


def bench(name, build, run, audio, dur):
    t0 = time.monotonic()
    obj = build()
    load_s = time.monotonic() - t0
    # warm + timed
    run(obj, audio)
    t1 = time.monotonic()
    text = run(obj, audio)
    infer_s = time.monotonic() - t1
    print(f"\n=== {name} ===")
    print(f"load:  {load_s:5.1f}s")
    print(f"infer: {infer_s:5.2f}s on {dur:.1f}s audio  →  RTF {infer_s/dur:.3f}  ({dur/infer_s:.1f}x realtime)")
    print(f"text:  {text[:300]}")


def main():
    audio, dur = load_audio()
    print(f"fixture: {dur:.1f}s of audio")

    from packages.transcription.transcriber import WhisperTranscriber

    bench(
        "Whisper-small (int8, CPU)",
        lambda: WhisperTranscriber(model_size="small"),
        lambda m, a: (m.transcribe(a) or type("", (), {"text": ""})()).text,
        audio,
        dur,
    )

    import onnx_asr

    bench(
        "Parakeet-v3 (int8, onnx-asr)",
        lambda: onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", quantization="int8"),
        lambda m, a: m.recognize(a, sample_rate=16000) or "",
        audio,
        dur,
    )


if __name__ == "__main__":
    main()
