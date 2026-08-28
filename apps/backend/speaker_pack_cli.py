"""Entry point for the confab-speakers pack binary: WAV in, JSON turns out.

Built by scripts/build-speaker-pack.sh into a self-contained PyInstaller
bundle (torch + pyannote + a local HF model cache). The main app invokes it
with HF_HOME pointed at the pack's cache and HF_HUB_OFFLINE=1.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: confab-speakers <wav-path>", file=sys.stderr)
        raise SystemExit(2)
    from packages.diarization import SpeakerDiarizer

    turns = SpeakerDiarizer().diarize_file(sys.argv[1])
    json.dump([asdict(turn) for turn in turns], sys.stdout)


if __name__ == "__main__":
    main()
