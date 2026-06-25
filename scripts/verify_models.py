from pathlib import Path

from faster_whisper import WhisperModel
from sentence_transformers import SentenceTransformer
from pyannote.audio import Pipeline
import ollama


def divider():
    print("=" * 60)


# -------------------------
# Whisper
# -------------------------
divider()
print("Verifying Faster Whisper...")

try:
    whisper = WhisperModel(
        "medium",
        device="auto",
        compute_type="int8"
    )

    print("Loaded")
    print("Model :", "medium")
    print("Type  : Faster Whisper")

except Exception as e:
    print("Failed")
    print(e)


# -------------------------
# Pyannote
# -------------------------
divider()
print("Verifying Pyannote...")

try:
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1"
    )

    print("Loaded")
    print("Model :", "speaker-diarization-3.1")

except Exception as e:
    print("Failed")
    print(e)


# -------------------------
# Sentence Transformer
# -------------------------
divider()
print("Verifying Embedding Model...")

try:
    embedding = SentenceTransformer(
        "all-MiniLM-L6-v2"
    )

    print("Loaded")
    print("Model :", "all-MiniLM-L6-v2")

    dimension = len(
        embedding.encode("MeetingMind")
    )

    print("Embedding Dimension :", dimension)

except Exception as e:
    print("Failed")
    print(e)


# -------------------------
# Ollama
# -------------------------
divider()
print("Verifying Ollama...")

try:
    models = ollama.list()

    print("Installed Models")

    for model in models.models:
        print(
            f"- {model.model}"
        )

except Exception as e:
    print("Failed")
    print(e)

divider()
print("Verification Complete")