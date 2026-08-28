# -*- mode: python ; coding: utf-8 -*-
# The optional speaker pack: torch + pyannote diarization as a standalone
# binary (see speaker_pack.py). Built by scripts/build-speaker-pack.sh.
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []
hiddenimports = []
for pkg in (
    "torch",
    "torchaudio",
    "pyannote.audio",
    "pyannote.core",
    "pyannote.database",
    "pyannote.pipeline",
    "asteroid_filterbanks",
    "einops",
    "soundfile",
):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        hiddenimports += collect_submodules(pkg)

a = Analysis(
    ["speaker_pack_cli.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "tkinter", "PIL", "IPython"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="confab-speakers",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="confab-speakers",
)
