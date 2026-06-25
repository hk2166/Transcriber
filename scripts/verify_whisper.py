from faster_whisper import WhisperModel

print("Loading Whisper medium model...")

model = WhisperModel(
    "medium",
    device="auto",
    compute_type="int8"
)

print("Model loaded successfully!")