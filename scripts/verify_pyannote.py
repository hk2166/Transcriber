from pyannote.audio import Pipeline

print("Loading speaker diarization model...")

pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1"
)

print("Pyannote model loaded successfully!")