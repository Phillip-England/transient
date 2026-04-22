# transient

transient is a FastAPI web application that accepts an uploaded audio file, analyzes short loudness windows against the file average, finds transient-heavy moments, slices the audio with FFmpeg, and returns a ZIP archive of the resulting clips.

## Requirements

- Python 3.11+
- `uv`

FFmpeg is checked automatically when the app starts processing audio. If it is missing, the app attempts a best-effort unattended install using a detected platform package manager such as Homebrew, `apt-get`, `dnf`, `pacman`, `winget`, or Chocolatey.

## Install

```bash
make install
```

This installs the `transient` CLI via `uv tool install --force .`.

## Run

```bash
uv sync
transient --reload
```

Open `http://127.0.0.1:8000`.

## How Stress Works

- `0` keeps cuts broader and more forgiving.
- `100` raises the loudness threshold and shortens the lookaround, which favors sharper, more isolated hits.

## Notes

- Uploaded files are transcoded to a mono 16 kHz WAV for analysis only.
- Output slices are exported as WAV files and bundled into `transient_slices.zip`.
- The transient detector compares 20 ms RMS windows against the average RMS of the analyzed file.
