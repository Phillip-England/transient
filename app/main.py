from __future__ import annotations

import json
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from app.audio import FFmpegUnavailableError, ensure_ffmpeg, extract_slices, probe_duration, run_ffmpeg


DEFAULT_STRESS = 55
DRUM_KEYS = "awsedfgyujk"
DRUM_BANK_SIZE = len(DRUM_KEYS)
DRUM_BASE_MIDI = 12
SESSION_TTL_SECONDS = 60 * 60


@dataclass
class DrumSession:
    temp_dir: Path
    slice_paths: list[Path]
    archive_path: Path
    created_at: float


DRUM_SESSIONS: dict[str, DrumSession] = {}
DRUM_SESSION_LOCK = Lock()

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>transient</title>
    <style>
        :root {
            --paper: #10161a;
            --paper-dark: #0a0f12;
            --ink: #e9f1f3;
            --muted: #8e9ca3;
            --line: #2a3940;
            --line-strong: #42555e;
            --panel: #1a2328;
            --panel-strong: #202b31;
            --accent: #ff8a3d;
            --accent-deep: #ffb26d;
            --accent-soft: #413124;
            --wave: #d9e5e8;
            --wave-soft: rgba(217, 229, 232, 0.16);
            --transient: rgba(255, 138, 61, 0.22);
            --transient-strong: #ff8a3d;
            --meter-red: #ff5d5d;
            --meter-yellow: #ffd65a;
            --meter-green: #6de08a;
            --success: #75d08a;
            --danger: #ff6b5d;
            --display: #c8ff7a;
            --display-bg: #131b10;
            --shadow: 0 18px 40px rgba(0, 0, 0, 0.45);
            --radius-xl: 22px;
            --radius-lg: 16px;
            --radius-md: 12px;
        }

        * {
            box-sizing: border-box;
        }

        html {
            color-scheme: dark;
        }

        body {
            margin: 0;
            min-height: 100vh;
            font-family: "IBM Plex Sans", "Avenir Next", "Helvetica Neue", sans-serif;
            color: var(--ink);
            background:
                radial-gradient(circle at top, rgba(255, 138, 61, 0.08), transparent 28%),
                linear-gradient(180deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0)),
                var(--paper);
        }

        body::before {
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            background-image:
                linear-gradient(rgba(255, 255, 255, 0.025) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255, 255, 255, 0.018) 1px, transparent 1px);
            background-size: 20px 20px;
            opacity: 0.24;
        }

        .shell {
            width: min(1200px, calc(100vw - 2rem));
            margin: 0 auto;
            padding: 1.5rem 0 2.5rem;
        }

        .topbar,
        .workspace,
        .download-panel {
            border: 2px solid var(--line-strong);
            background: var(--panel);
            box-shadow: var(--shadow);
        }

        .topbar {
            padding: 1rem 1.2rem;
            border-radius: var(--radius-xl);
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            position: relative;
            background:
                linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(0, 0, 0, 0.16)),
                var(--panel);
        }

        .topbar::after {
            content: "";
            position: absolute;
            left: 14px;
            right: 14px;
            bottom: 10px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        }

        .eyebrow {
            margin: 0 0 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.16em;
            font-size: 0.72rem;
            color: var(--accent-deep);
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
        }

        h1 {
            margin: 0;
            font-size: clamp(1.9rem, 4vw, 2.9rem);
            line-height: 1;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            font-weight: 700;
        }

        .subtle {
            margin: 0;
            font-size: 0.9rem;
            color: var(--display);
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
            padding: 0.45rem 0.7rem;
            border-radius: 999px;
            background: var(--display-bg);
            border: 1px solid rgba(200, 255, 122, 0.15);
        }

        .workspace {
            margin-top: 1.25rem;
            padding: 1.25rem;
            border-radius: 22px;
            background:
                linear-gradient(180deg, rgba(255, 255, 255, 0.03), rgba(0, 0, 0, 0.12)),
                var(--panel);
        }

        .controls {
            display: grid;
            grid-template-columns: minmax(0, 1.2fr) minmax(300px, 0.8fr);
            gap: 1rem;
        }

        .control-card {
            padding: 1.2rem;
            border: 1px solid var(--line);
            border-radius: var(--radius-lg);
            background: var(--panel-strong);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
        }

        .section-title {
            margin: 0 0 0.65rem;
            font-size: 0.86rem;
            text-transform: uppercase;
            letter-spacing: 0.14em;
            color: var(--display);
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
        }

        .file-drop {
            position: relative;
            display: grid;
            gap: 0.65rem;
            align-content: center;
            min-height: 170px;
            padding: 1.4rem;
            border: 2px solid #33434a;
            border-radius: var(--radius-lg);
            background:
                linear-gradient(180deg, rgba(255, 255, 255, 0.02), rgba(0, 0, 0, 0.18)),
                #182126;
            transition: border-color 150ms ease, transform 150ms ease, background-color 150ms ease;
            box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.03);
        }

        .file-drop.dragging {
            border-color: var(--accent);
            transform: translateY(-1px);
            background: #1e2a30;
        }

        .file-drop input[type="file"] {
            position: absolute;
            inset: 0;
            opacity: 0;
            cursor: pointer;
        }

        .drop-title {
            margin: 0;
            font-size: 1.25rem;
            line-height: 1.1;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.02em;
        }

        .drop-subtitle,
        .hint {
            margin: 0;
            color: var(--muted);
            line-height: 1.55;
        }

        .pill-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
        }

        .pill {
            display: inline-flex;
            align-items: center;
            padding: 0.45rem 0.7rem;
            border-radius: 999px;
            background: #11181c;
            border: 1px solid #314148;
            font-size: 0.82rem;
            color: var(--display);
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
        }

        .stress-header {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 1rem;
        }

        .stress-value {
            font-size: clamp(2rem, 4vw, 3rem);
            line-height: 0.9;
            font-weight: 700;
            color: var(--display);
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
            padding: 0.45rem 0.6rem;
            border-radius: 10px;
            background: var(--display-bg);
            border: 1px solid rgba(200, 255, 122, 0.14);
        }

        .stress-copy {
            margin: 0.25rem 0 0.75rem;
            color: var(--muted);
            line-height: 1.4;
            font-size: 0.94rem;
        }

        input[type="range"] {
            width: 100%;
            appearance: none;
            height: 10px;
            border-radius: 999px;
            border: 1px solid var(--line-strong);
            background: linear-gradient(90deg, #0f1518, #25343b);
            outline: none;
        }

        input[type="range"]::-webkit-slider-thumb {
            appearance: none;
            width: 24px;
            height: 24px;
            border-radius: 6px;
            border: 2px solid #120d09;
            background: var(--accent);
            box-shadow: 0 0 0 1px rgba(255,255,255,0.05), 0 4px 12px rgba(0,0,0,0.45);
            cursor: pointer;
        }

        input[type="range"]::-moz-range-thumb {
            width: 24px;
            height: 24px;
            border-radius: 6px;
            border: 2px solid #120d09;
            background: var(--accent);
            box-shadow: 0 0 0 1px rgba(255,255,255,0.05), 0 4px 12px rgba(0,0,0,0.45);
            cursor: pointer;
        }

        .scale {
            display: flex;
            justify-content: space-between;
            margin-top: 0.65rem;
            font-size: 0.85rem;
            color: var(--muted);
        }

        .viz {
            display: grid;
            grid-template-columns: minmax(0, 1.5fr) minmax(280px, 0.8fr);
            gap: 1rem;
            margin-top: 1rem;
        }

        .viz-card,
        .metrics-card {
            padding: 1rem;
            border: 1px solid var(--line);
            border-radius: var(--radius-lg);
            background: var(--panel-strong);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
        }

        .audio-bar {
            display: flex;
            flex-wrap: wrap;
            justify-content: space-between;
            gap: 0.75rem;
            margin-bottom: 0.75rem;
            align-items: center;
        }

        .preview-tools {
            display: grid;
            gap: 0.55rem;
            width: min(100%, 440px);
        }

        .preview-tool-row {
            display: grid;
            grid-template-columns: auto 1fr auto;
            gap: 0.75rem;
            align-items: center;
        }

        .preview-tool-label {
            font-size: 0.74rem;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.12em;
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
        }

        .preview-tool-value {
            min-width: 4ch;
            text-align: right;
            font-size: 0.82rem;
            color: var(--accent-deep);
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
        }

        .selection-panel {
            margin-bottom: 1rem;
            padding: 0.9rem;
            border: 1px solid var(--line);
            border-radius: var(--radius-lg);
            background:
                linear-gradient(180deg, rgba(255,255,255,0.02), rgba(0,0,0,0.14)),
                #171f24;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
        }

        .selection-head {
            display: flex;
            flex-wrap: wrap;
            justify-content: space-between;
            gap: 0.75rem;
            align-items: baseline;
        }

        .selection-values {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-top: 0.75rem;
        }

        .selection-chip {
            min-width: 7.5rem;
            padding: 0.65rem 0.75rem;
            border-radius: 10px;
            background: #10171b;
            border: 1px solid #304148;
        }

        .selection-chip-label {
            margin: 0;
            font-size: 0.72rem;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.12em;
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
        }

        .selection-chip-meter {
            margin: 0 0 0.35rem;
            font-size: 0.88rem;
            color: var(--meter-green);
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
            font-weight: 700;
            letter-spacing: 0.02em;
        }

        .selection-chip-value {
            margin: 0.3rem 0 0;
            font-size: 1.15rem;
            color: var(--display);
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
        }

        .selection-actions {
            display: flex;
            flex-wrap: wrap;
            gap: 0.6rem;
            margin-top: 0.85rem;
        }

        .ghost {
            color: var(--accent-deep);
            background: #141d21;
            border: 1px solid #34454c;
        }

        .icon-button {
            width: 3rem;
            height: 3rem;
            display: inline-grid;
            place-items: center;
            padding: 0;
        }

        .icon-button svg {
            width: 1.2rem;
            height: 1.2rem;
            display: block;
            fill: currentColor;
        }

        .icon-button:focus-visible {
            outline: 2px solid var(--display);
            outline-offset: 2px;
        }

        audio {
            width: min(100%, 420px);
            filter: saturate(0.9) contrast(1.08) brightness(0.95);
        }

        .canvas-shell {
            position: relative;
            overflow: hidden;
            border-radius: 12px;
            border: 2px solid #314148;
            background:
                linear-gradient(180deg, rgba(255,255,255,0.015), rgba(0,0,0,0.24)),
                #0d1316;
            padding-top: 26px;
        }

        .wave-handle-layer {
            position: absolute;
            left: 0;
            right: 0;
            top: 0;
            height: 30px;
            pointer-events: none;
            z-index: 2;
        }

        .wave-selection-band {
            position: absolute;
            top: 13px;
            height: 7px;
            border-radius: 999px;
            background: rgba(255, 138, 61, 0.22);
            border: 1px solid rgba(255, 138, 61, 0.4);
        }

        .wave-handle {
            position: absolute;
            top: 2px;
            width: 14px;
            height: 24px;
            margin-left: -7px;
            border: 1px solid #1a120b;
            border-radius: 6px;
            background: linear-gradient(180deg, #ffb26d, #ff8a3d);
            box-shadow: 0 0 0 1px rgba(255,255,255,0.06), 0 6px 14px rgba(0, 0, 0, 0.35);
            cursor: ew-resize;
            pointer-events: auto;
        }

        .wave-handle:focus-visible {
            outline: 2px solid var(--display);
            outline-offset: 2px;
        }

        .wave-handle::before {
            content: "";
            position: absolute;
            left: 50%;
            top: 4px;
            width: 2px;
            height: 14px;
            transform: translateX(-50%);
            background: #49270f;
            box-shadow: -4px 0 0 rgba(73, 39, 15, 0.24), 4px 0 0 rgba(73, 39, 15, 0.24);
        }

        .wave-handle.start::after,
        .wave-handle.end::after {
            content: "";
            position: absolute;
            top: 24px;
            width: 1px;
            height: 180px;
            background: rgba(255, 138, 61, 0.35);
        }

        .wave-handle.start::after {
            left: 6px;
        }

        .wave-handle.end::after {
            left: 6px;
        }

        canvas {
            display: block;
            width: 100%;
            height: 180px;
        }

        .timeline {
            display: flex;
            justify-content: space-between;
            gap: 0.5rem;
            margin-top: 0.6rem;
            font-size: 0.86rem;
            color: var(--muted);
        }

        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.75rem;
        }

        .metric {
            padding: 0.9rem;
            border-radius: 10px;
            background: #131b20;
            border: 1px solid #304148;
        }

        .metric-label {
            margin: 0;
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.14em;
            color: var(--display);
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
        }

        .metric-value {
            margin: 0.45rem 0 0;
            font-size: 1.8rem;
            line-height: 1;
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
            color: var(--ink);
        }

        .metric-note {
            margin: 0.45rem 0 0;
            color: var(--muted);
            line-height: 1.5;
            font-size: 0.92rem;
        }

        .segments {
            margin-top: 1rem;
            display: grid;
            gap: 0.55rem;
            max-height: 240px;
            overflow: auto;
            padding-right: 0.2rem;
        }

        .segment {
            display: grid;
            grid-template-columns: auto 1fr auto;
            gap: 0.8rem;
            align-items: center;
            padding: 0.8rem 0.9rem;
            border-radius: 10px;
            background: #131b20;
            border: 1px solid #304148;
        }

        .segment-index {
            width: 2rem;
            height: 2rem;
            display: grid;
            place-items: center;
            border-radius: 8px;
            background: #302117;
            border: 1px solid #5e422b;
            color: var(--accent-deep);
            font-weight: 700;
            font-size: 0.9rem;
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
        }

        .segment-label {
            margin: 0;
            font-size: 0.98rem;
        }

        .segment-note {
            margin: 0.18rem 0 0;
            color: var(--muted);
            font-size: 0.88rem;
        }

        .empty-state {
            padding: 1.1rem;
            border-radius: 10px;
            background: #131b20;
            border: 2px dashed #324148;
            color: var(--muted);
            line-height: 1.6;
        }

        .download-panel {
            margin-top: 1rem;
            padding: 1rem;
            border-radius: var(--radius-lg);
            display: flex;
            flex-wrap: wrap;
            justify-content: space-between;
            align-items: center;
            gap: 1rem;
        }

        .status {
            min-height: 1.5rem;
            font-size: 0.98rem;
            color: var(--muted);
        }

        .status.error {
            color: var(--danger);
        }

        .status.success {
            color: var(--success);
        }

        .actions {
            display: flex;
            flex-wrap: wrap;
            gap: 0.75rem;
        }

        button {
            border: 0;
            border-radius: 8px;
            padding: 0.95rem 1.35rem;
            font: inherit;
            font-weight: 700;
            cursor: pointer;
            transition: transform 140ms ease, filter 140ms ease, opacity 140ms ease;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            font-size: 0.86rem;
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
        }

        button:hover:not(:disabled) {
            transform: translateY(-1px);
            filter: brightness(1.03);
        }

        button:disabled {
            opacity: 0.55;
            cursor: not-allowed;
        }

        .primary {
            color: #261103;
            background: linear-gradient(180deg, var(--accent-deep), var(--accent));
            box-shadow: 0 4px 14px rgba(255, 138, 61, 0.26);
        }

        .secondary {
            color: var(--ink);
            background: #141d21;
            border: 1px solid #34454c;
        }

        .ghost {
            color: var(--accent-deep);
            background: #141d21;
            border: 1px solid #34454c;
        }

        .legend {
            display: flex;
            flex-wrap: wrap;
            gap: 0.8rem;
            margin-top: 0.85rem;
            color: var(--muted);
            font-size: 0.9rem;
        }

        .legend-item {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
        }

        .swatch {
            width: 16px;
            height: 16px;
            border-radius: 4px;
            border: 1px solid rgba(255, 255, 255, 0.08);
        }

        .swatch.wave {
            background: var(--wave);
        }

        .swatch.transient {
            background: var(--transient-strong);
        }

        .swatch.selection {
            background: var(--accent-soft);
        }

        @media (max-width: 920px) {
            .controls,
            .viz {
                grid-template-columns: 1fr;
            }
        }

        @media (max-width: 640px) {
            .shell {
                width: min(100vw - 1rem, 100%);
                padding-top: 0.5rem;
            }

            .topbar,
            .workspace,
            .download-panel {
                border-radius: 22px;
            }

            .topbar,
            .workspace {
                padding: 1rem;
            }

            .topbar {
                align-items: flex-start;
                flex-direction: column;
            }

            canvas {
                height: 140px;
            }

            .metrics-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <main class="shell">
        <section class="topbar">
            <div>
                <p class="eyebrow">transient</p>
                <h1>Transient Slicer</h1>
            </div>
            <p class="subtle" id="stressMood">Balanced</p>
        </section>

        <section class="workspace">
            <section class="controls">
                <div class="control-card">
                    <p class="section-title">File</p>
                    <label class="file-drop" id="fileDrop">
                        <input id="audioFile" type="file" name="audio_file" accept="audio/*">
                        <p class="drop-title" id="fileTitle">Drop audio here or click to browse</p>
                        <p class="drop-subtitle" id="fileSubtitle">Select a file to preview and slice.</p>
                        <div class="pill-row">
                            <span class="pill" id="fileSizePill">No file selected</span>
                            <span class="pill" id="fileTypePill">Preview idle</span>
                        </div>
                    </label>
                </div>

                <div class="control-card">
                    <div class="stress-header">
                        <div>
                            <p class="section-title">Stress</p>
                            <p class="stress-copy" id="stressDescription">Balanced threshold and slice spacing.</p>
                        </div>
                        <div class="stress-value" id="stressValue">__DEFAULT_STRESS__</div>
                    </div>

                    <input id="stress" type="range" min="0" max="100" value="__DEFAULT_STRESS__">
                    <div class="scale">
                        <span>Loose</span>
                        <span>Balanced</span>
                        <span>Severe</span>
                    </div>
                </div>
            </section>

            <section class="viz">
                <div class="viz-card">
                    <div class="audio-bar">
                        <div>
                            <p class="section-title">Preview</p>
                        </div>
                        <div class="preview-tools">
                            <audio id="audioPlayer" controls preload="metadata"></audio>
                            <div class="preview-tool-row">
                                <span class="preview-tool-label">Zoom</span>
                                <input id="zoom" type="range" min="1" max="12" step="0.25" value="1">
                                <span class="preview-tool-value" id="zoomValue">1.0x</span>
                            </div>
                            <div class="preview-tool-row">
                                <span class="preview-tool-label">Pan</span>
                                <input id="pan" type="range" min="0" max="100" step="0.5" value="50">
                                <span class="preview-tool-value" id="panValue">Center</span>
                            </div>
                        </div>
                    </div>

                    <section class="selection-panel">
                        <div class="selection-head">
                            <p class="section-title">Section</p>
                            <p class="subtle" id="selectionFeedback">Full file selected</p>
                        </div>

                        <div class="selection-values">
                            <div class="selection-chip">
                                <p class="selection-chip-label">Start</p>
                                <p class="selection-chip-meter" id="selectionStartDbValue">--.- dB</p>
                                <p class="selection-chip-value" id="selectionStartValue">0.00s</p>
                            </div>
                            <div class="selection-chip">
                                <p class="selection-chip-label">End</p>
                                <p class="selection-chip-meter" id="selectionEndDbValue">--.- dB</p>
                                <p class="selection-chip-value" id="selectionEndValue">0.00s</p>
                            </div>
                            <div class="selection-chip">
                                <p class="selection-chip-label">Length</p>
                                <p class="selection-chip-value" id="selectionLengthValue">0.00s</p>
                            </div>
                        </div>

                        <div class="selection-actions">
                            <button class="ghost icon-button" id="setStartButton" type="button" aria-label="Set start to playhead" title="Set start to playhead">
                                <svg viewBox="0 0 24 24" aria-hidden="true">
                                    <path d="M5 4h2v16H5zM19 6v12l-9-6z"/>
                                </svg>
                            </button>
                            <button class="ghost icon-button" id="setEndButton" type="button" aria-label="Set end to playhead" title="Set end to playhead">
                                <svg viewBox="0 0 24 24" aria-hidden="true">
                                    <path d="M17 4h2v16h-2zM5 6l9 6-9 6z"/>
                                </svg>
                            </button>
                            <button class="ghost icon-button" id="playSelectionButton" type="button" aria-label="Play selection" title="Play selection">
                                <svg viewBox="0 0 24 24" aria-hidden="true">
                                    <path d="M8 5v14l11-7z"/>
                                </svg>
                            </button>
                            <button class="ghost icon-button" id="resetSelectionButton" type="button" aria-label="Use full file" title="Use full file">
                                <svg viewBox="0 0 24 24" aria-hidden="true">
                                    <path d="M4 7h2v10H4zM18 7h2v10h-2zM8 7h8v10H8z"/>
                                </svg>
                            </button>
                        </div>
                    </section>

                    <div class="canvas-shell">
                        <div class="wave-handle-layer" id="waveHandleLayer">
                            <div class="wave-selection-band" id="selectionBand"></div>
                            <button class="wave-handle start" id="selectionStartHandle" type="button" aria-label="Adjust selection start"></button>
                            <button class="wave-handle end" id="selectionEndHandle" type="button" aria-label="Adjust selection end"></button>
                        </div>
                        <canvas id="waveCanvas"></canvas>
                    </div>

                    <div class="timeline">
                        <span id="timeStart">0.00s</span>
                        <span id="timeCenter">Load a file to preview</span>
                        <span id="timeEnd">0.00s</span>
                    </div>

                    <div class="legend">
                        <span class="legend-item"><span class="swatch wave"></span> Waveform energy</span>
                        <span class="legend-item"><span class="swatch selection"></span> Selected section</span>
                        <span class="legend-item"><span class="swatch transient"></span> Slice regions</span>
                    </div>
                </div>

                <aside class="metrics-card">
                    <p class="section-title">Slices</p>

                    <div class="metrics-grid">
                        <section class="metric">
                            <p class="metric-label">File</p>
                            <p class="metric-value" id="durationMetric">0.00s</p>
                        </section>
                        <section class="metric">
                            <p class="metric-label">Section</p>
                            <p class="metric-value" id="selectionMetric">0.00s</p>
                        </section>
                        <section class="metric">
                            <p class="metric-label">Count</p>
                            <p class="metric-value" id="countMetric">0</p>
                        </section>
                        <section class="metric">
                            <p class="metric-label">Threshold</p>
                            <p class="metric-value" id="thresholdMetric">0.00x</p>
                        </section>
                    </div>

                    <div class="segments" id="segmentsList">
                        <div class="empty-state">
                            Upload audio to populate the transient list and waveform overlay.
                        </div>
                    </div>
                </aside>
            </section>
        </section>

        <section class="download-panel">
            <div>
                <div class="status" id="status">Select a file to begin.</div>
            </div>
            <div class="actions">
                <button class="secondary" id="resetButton" type="button">Clear Preview</button>
                <button class="secondary" id="drumModeButton" type="button" disabled>Test In Drum Mode</button>
                <button class="primary" id="processButton" type="button" disabled>Process And Download ZIP</button>
            </div>
        </section>
    </main>

    <script>
        const DEFAULT_STRESS = __DEFAULT_STRESS__;
        const WINDOW_SECONDS = 0.02;

        const state = {
            file: null,
            objectUrl: null,
            audioBuffer: null,
            monoSamples: null,
            waveformEnvelope: [],
            rmsValues: [],
            segments: [],
            averageRms: 0,
            duration: 0,
            zoom: 1,
            pan: 0.5,
            selectionStart: 0,
            selectionEnd: 0,
            handleDrag: null,
            activeHandle: null,
            animationFrame: null,
            busy: false,
        };

        const elements = {
            audioFile: document.getElementById("audioFile"),
            audioPlayer: document.getElementById("audioPlayer"),
            zoom: document.getElementById("zoom"),
            zoomValue: document.getElementById("zoomValue"),
            pan: document.getElementById("pan"),
            panValue: document.getElementById("panValue"),
            fileDrop: document.getElementById("fileDrop"),
            fileTitle: document.getElementById("fileTitle"),
            fileSubtitle: document.getElementById("fileSubtitle"),
            fileSizePill: document.getElementById("fileSizePill"),
            fileTypePill: document.getElementById("fileTypePill"),
            stress: document.getElementById("stress"),
            stressValue: document.getElementById("stressValue"),
            stressMood: document.getElementById("stressMood"),
            stressDescription: document.getElementById("stressDescription"),
            waveHandleLayer: document.getElementById("waveHandleLayer"),
            selectionBand: document.getElementById("selectionBand"),
            selectionStartHandle: document.getElementById("selectionStartHandle"),
            selectionEndHandle: document.getElementById("selectionEndHandle"),
            selectionFeedback: document.getElementById("selectionFeedback"),
            selectionStartDbValue: document.getElementById("selectionStartDbValue"),
            selectionEndDbValue: document.getElementById("selectionEndDbValue"),
            selectionStartValue: document.getElementById("selectionStartValue"),
            selectionEndValue: document.getElementById("selectionEndValue"),
            selectionLengthValue: document.getElementById("selectionLengthValue"),
            selectionMetric: document.getElementById("selectionMetric"),
            setStartButton: document.getElementById("setStartButton"),
            setEndButton: document.getElementById("setEndButton"),
            playSelectionButton: document.getElementById("playSelectionButton"),
            resetSelectionButton: document.getElementById("resetSelectionButton"),
            durationMetric: document.getElementById("durationMetric"),
            countMetric: document.getElementById("countMetric"),
            thresholdMetric: document.getElementById("thresholdMetric"),
            segmentsList: document.getElementById("segmentsList"),
            status: document.getElementById("status"),
            drumModeButton: document.getElementById("drumModeButton"),
            processButton: document.getElementById("processButton"),
            resetButton: document.getElementById("resetButton"),
            waveCanvas: document.getElementById("waveCanvas"),
            timeStart: document.getElementById("timeStart"),
            timeCenter: document.getElementById("timeCenter"),
            timeEnd: document.getElementById("timeEnd"),
        };

        const audioContext = new (window.AudioContext || window.webkitAudioContext)();

        function setStatus(message, tone = "") {
            elements.status.textContent = message;
            elements.status.className = tone ? "status " + tone : "status";
        }

        function formatSeconds(value) {
            if (!Number.isFinite(value)) {
                return "0.00s";
            }
            return value.toFixed(2) + "s";
        }

        function clamp(value, min, max) {
            return Math.min(max, Math.max(min, value));
        }

        function formatFileSize(bytes) {
            if (!bytes) {
                return "0 KB";
            }
            const units = ["B", "KB", "MB", "GB"];
            let size = bytes;
            let unitIndex = 0;
            while (size >= 1024 && unitIndex < units.length - 1) {
                size /= 1024;
                unitIndex += 1;
            }
            return size.toFixed(size >= 10 || unitIndex === 0 ? 0 : 1) + " " + units[unitIndex];
        }

        function describeStress(stress) {
            if (stress <= 25) {
                return {
                    mood: "Loose",
                    text: "Broader slices with more context.",
                };
            }
            if (stress <= 60) {
                return {
                    mood: "Balanced",
                    text: "Balanced threshold and slice spacing.",
                };
            }
            if (stress <= 85) {
                return {
                    mood: "Tight",
                    text: "Higher threshold with tighter isolation.",
                };
            }
            return {
                mood: "Severe",
                text: "Only the strongest peaks survive.",
            };
        }

        function updateStressUI() {
            const stress = Number(elements.stress.value);
            elements.stressValue.textContent = String(stress);
            const descriptor = describeStress(stress);
            elements.stressMood.textContent = descriptor.mood;
            elements.stressDescription.textContent = descriptor.text;
            if (state.rmsValues.length) {
                recomputeSegments();
            } else {
                elements.thresholdMetric.textContent = (1.05 + (stress / 100) * 1.65).toFixed(2) + "x";
            }
        }

        function averageChannels(audioBuffer) {
            const sampleCount = audioBuffer.length;
            const channelCount = audioBuffer.numberOfChannels;
            const mono = new Float32Array(sampleCount);
            for (let channel = 0; channel < channelCount; channel += 1) {
                const channelData = audioBuffer.getChannelData(channel);
                for (let i = 0; i < sampleCount; i += 1) {
                    mono[i] += channelData[i] / channelCount;
                }
            }
            return mono;
        }

        function computeRmsValues(samples, sampleRate, windowSeconds) {
            const windowSize = Math.max(1, Math.floor(sampleRate * windowSeconds));
            const rmsValues = [];
            for (let start = 0; start < samples.length; start += windowSize) {
                const end = Math.min(start + windowSize, samples.length);
                let sum = 0;
                for (let i = start; i < end; i += 1) {
                    const sample = samples[i];
                    sum += sample * sample;
                }
                const mean = end > start ? sum / (end - start) : 0;
                rmsValues.push(Math.sqrt(mean));
            }
            return rmsValues;
        }

        function computeEnvelope(samples, bucketCount) {
            const buckets = Math.max(32, bucketCount);
            const bucketSize = Math.max(1, Math.floor(samples.length / buckets));
            const envelope = [];
            for (let bucket = 0; bucket < buckets; bucket += 1) {
                const start = bucket * bucketSize;
                const end = Math.min(samples.length, start + bucketSize);
                let peak = 0;
                for (let i = start; i < end; i += 1) {
                    const value = Math.abs(samples[i]);
                    if (value > peak) {
                        peak = value;
                    }
                }
                envelope.push(peak);
            }
            return envelope;
        }

        function detectSegments(rmsValues, stress) {
            if (!rmsValues.length) {
                return {
                    averageRms: 0,
                    threshold: 0,
                    segments: [],
                };
            }

            const averageRms = rmsValues.reduce((sum, value) => sum + value, 0) / rmsValues.length;
            const thresholdMultiplier = 1.05 + (stress / 100) * 1.65;
            const threshold = averageRms * thresholdMultiplier;

            const totalDuration = rmsValues.length * WINDOW_SECONDS;
            const preRoll = Math.max(0.01, 0.12 - (stress / 100) * 0.06);
            const postRoll = 0.22 + (stress / 100) * 0.22;
            const minGap = 0.08 + (stress / 100) * 0.22;
            const maxLength = 0.45 + (stress / 100) * 0.55;

            const transientTimes = [];
            for (let i = 0; i < rmsValues.length; i += 1) {
                if (rmsValues[i] >= threshold) {
                    transientTimes.push(i * WINDOW_SECONDS);
                }
            }

            if (!transientTimes.length) {
                return {
                    averageRms,
                    threshold: thresholdMultiplier,
                    segments: [],
                };
            }

            const merged = [];
            for (const point of transientTimes) {
                if (!merged.length || point - merged[merged.length - 1] >= minGap) {
                    merged.push(point);
                }
            }

            const boundaries = [0];
            for (const point of merged) {
                boundaries.push(Math.max(0, point - preRoll));
            }
            boundaries.push(totalDuration);
            boundaries.sort((a, b) => a - b);

            const uniqueBoundaries = [];
            for (const boundary of boundaries) {
                if (!uniqueBoundaries.length || Math.abs(boundary - uniqueBoundaries[uniqueBoundaries.length - 1]) > 1e-9) {
                    uniqueBoundaries.push(boundary);
                }
            }

            const rawSegments = [];
            for (let i = 0; i < uniqueBoundaries.length - 1; i += 1) {
                const start = uniqueBoundaries[i];
                const end = uniqueBoundaries[i + 1];
                let adjustedEnd = Math.min(end, start + maxLength);
                if (adjustedEnd - start >= 0.03) {
                    adjustedEnd = Math.min(totalDuration, Math.max(adjustedEnd, start + postRoll));
                    rawSegments.push({ start, end: adjustedEnd });
                }
            }

            if (!rawSegments.length) {
                return {
                    averageRms,
                    threshold: thresholdMultiplier,
                    segments: [],
                };
            }

            const normalized = [rawSegments[0]];
            for (let i = 1; i < rawSegments.length; i += 1) {
                const current = rawSegments[i];
                const previous = normalized[normalized.length - 1];
                if (current.start <= previous.end) {
                    previous.end = Math.max(previous.end, current.end);
                } else {
                    normalized.push(current);
                }
            }

            return {
                averageRms,
                threshold: thresholdMultiplier,
                segments: normalized,
            };
        }

        function getSelectionDuration() {
            return Math.max(0, state.selectionEnd - state.selectionStart);
        }

        function formatDecibels(db) {
            if (!Number.isFinite(db)) {
                return "--.- dB";
            }
            return db.toFixed(1) + " dB";
        }

        function getDbColor(db) {
            if (!Number.isFinite(db)) {
                return "var(--muted)";
            }
            if (db >= -12) {
                return "var(--meter-red)";
            }
            if (db >= -24) {
                return "var(--meter-yellow)";
            }
            return "var(--meter-green)";
        }

        function getLocalDecibels(timeSeconds) {
            if (!state.monoSamples || !state.audioBuffer) {
                return Number.NaN;
            }

            const sampleRate = state.audioBuffer.sampleRate;
            const center = Math.floor(timeSeconds * sampleRate);
            const halfWindow = Math.max(32, Math.floor(sampleRate * 0.005));
            const start = clamp(center - halfWindow, 0, state.monoSamples.length - 1);
            const end = clamp(center + halfWindow, start + 1, state.monoSamples.length);

            let sum = 0;
            let count = 0;
            for (let index = start; index < end; index += 1) {
                const sample = state.monoSamples[index];
                sum += sample * sample;
                count += 1;
            }

            if (!count) {
                return Number.NaN;
            }

            const rms = Math.sqrt(sum / count);
            const safeRms = Math.max(rms, 1e-6);
            return 20 * Math.log10(safeRms);
        }

        function updateSelectionMeters() {
            const startDb = getLocalDecibels(state.selectionStart);
            const endDb = getLocalDecibels(state.selectionEnd);

            elements.selectionStartDbValue.textContent = formatDecibels(startDb);
            elements.selectionEndDbValue.textContent = formatDecibels(endDb);
            elements.selectionStartDbValue.style.color = getDbColor(startDb);
            elements.selectionEndDbValue.style.color = getDbColor(endDb);
        }

        function syncSelectionInputs() {
            elements.selectionStartValue.textContent = formatSeconds(state.selectionStart);
            elements.selectionEndValue.textContent = formatSeconds(state.selectionEnd);
            elements.selectionLengthValue.textContent = formatSeconds(getSelectionDuration());
            elements.selectionMetric.textContent = formatSeconds(getSelectionDuration());
            updateSelectionMeters();

            const isFull = state.selectionStart <= 0.001 && Math.abs(state.selectionEnd - state.duration) <= 0.001;
            elements.selectionFeedback.textContent = isFull
                ? "Full file selected"
                : formatSeconds(state.selectionStart) + " to " + formatSeconds(state.selectionEnd);
        }

        function updateWaveHandles() {
            if (!state.duration) {
                elements.selectionBand.style.left = "0px";
                elements.selectionBand.style.width = "0px";
                elements.selectionStartHandle.style.left = "0px";
                elements.selectionEndHandle.style.left = "0px";
                return;
            }

            const visible = getVisibleWindow();
            const layerWidth = elements.waveHandleLayer.clientWidth;
            const visibleDuration = Math.max(visible.duration, 0.001);
            const timeToX = (time) => ((time - visible.start) / visibleDuration) * layerWidth;
            const left = clamp(timeToX(clamp(state.selectionStart, visible.start, visible.end)), 0, layerWidth);
            const right = clamp(timeToX(clamp(state.selectionEnd, visible.start, visible.end)), 0, layerWidth);

            elements.selectionBand.style.left = left + "px";
            elements.selectionBand.style.width = Math.max(0, right - left) + "px";
            elements.selectionStartHandle.style.left = left + "px";
            elements.selectionEndHandle.style.left = right + "px";
        }

        function getVisibleWindow() {
            const duration = Math.max(state.duration, 0);
            if (!duration) {
                return { start: 0, end: 0, duration: 0 };
            }

            const visibleDuration = duration / Math.max(state.zoom, 1);
            if (visibleDuration >= duration) {
                return { start: 0, end: duration, duration };
            }

            const slack = duration - visibleDuration;
            const start = slack * state.pan;
            return {
                start,
                end: start + visibleDuration,
                duration: visibleDuration,
            };
        }

        function updateZoomUI() {
            state.zoom = Number(elements.zoom.value);
            state.pan = Number(elements.pan.value) / 100;
            elements.zoomValue.textContent = state.zoom.toFixed(1) + "x";

            if (state.zoom <= 1.01) {
                elements.pan.disabled = true;
                elements.panValue.textContent = "Full";
            } else {
                elements.pan.disabled = false;
                const visible = getVisibleWindow();
                elements.panValue.textContent = formatSeconds(visible.start) + "–" + formatSeconds(visible.end);
            }

            drawWaveform();
            if (!state.rmsValues.length) {
                elements.timeStart.textContent = "0.00s";
                elements.timeEnd.textContent = "0.00s";
                updateWaveHandles();
                return;
            }
            const visible = getVisibleWindow();
            elements.timeStart.textContent = formatSeconds(visible.start);
            elements.timeEnd.textContent = formatSeconds(visible.end);
            updateWaveHandles();
        }

        function setSelection(start, end, options = {}) {
            const duration = Math.max(state.duration, 0);
            if (!duration) {
                state.selectionStart = 0;
                state.selectionEnd = 0;
                syncSelectionInputs();
                return;
            }

            const minLength = Math.min(0.05, duration);
            let nextStart = clamp(Math.min(start, end), 0, duration);
            let nextEnd = clamp(Math.max(start, end), 0, duration);

            if (nextEnd - nextStart < minLength) {
                if (nextEnd >= duration) {
                    nextStart = Math.max(0, nextEnd - minLength);
                } else {
                    nextEnd = Math.min(duration, nextStart + minLength);
                }
            }

            state.selectionStart = nextStart;
            state.selectionEnd = nextEnd;

            if (state.zoom > 1.01 && options.followHandle) {
                const visibleDuration = duration / state.zoom;
                const maxStart = Math.max(0, duration - visibleDuration);
                const marginRatio = 0.08;
                const visible = getVisibleWindow();
                const edgeMargin = visibleDuration * marginRatio;
                const activeTime = options.handle === "end" ? state.selectionEnd : state.selectionStart;
                let nextVisibleStart = visible.start;

                if (activeTime < visible.start + edgeMargin) {
                    nextVisibleStart = clamp(activeTime - edgeMargin, 0, maxStart);
                } else if (activeTime > visible.end - edgeMargin) {
                    nextVisibleStart = clamp(activeTime + edgeMargin - visibleDuration, 0, maxStart);
                }

                if (nextVisibleStart !== visible.start) {
                    state.pan = maxStart > 0 ? nextVisibleStart / maxStart : 0.5;
                    elements.pan.value = String(state.pan * 100);
                }
            }

            syncSelectionInputs();
            updateWaveHandles();

            if (state.rmsValues.length) {
                recomputeSegments();
            } else {
                drawWaveform();
            }
        }

        function getSelectedRmsValues() {
            if (!state.rmsValues.length) {
                return [];
            }
            const startIndex = Math.max(0, Math.floor(state.selectionStart / WINDOW_SECONDS));
            const endIndex = Math.min(state.rmsValues.length, Math.ceil(state.selectionEnd / WINDOW_SECONDS));
            return state.rmsValues.slice(startIndex, Math.max(startIndex + 1, endIndex));
        }

        function renderSegments(segments) {
            if (!segments.length) {
                elements.segmentsList.innerHTML = '<div class="empty-state">No slices found in the selected section.</div>';
                return;
            }

            elements.segmentsList.innerHTML = segments.map((segment, index) => {
                const duration = Math.max(0, segment.end - segment.start);
                return `
                    <article class="segment">
                        <div class="segment-index">${index + 1}</div>
                        <div>
                            <p class="segment-label">${formatSeconds(segment.start)} to ${formatSeconds(segment.end)}</p>
                            <p class="segment-note">Slice length ${formatSeconds(duration)}</p>
                        </div>
                        <strong>${duration.toFixed(2)}s</strong>
                    </article>
                `;
            }).join("");
        }

        function resizeCanvas(canvas) {
            const ratio = window.devicePixelRatio || 1;
            const width = canvas.clientWidth;
            const height = canvas.clientHeight;
            const displayWidth = Math.max(1, Math.floor(width * ratio));
            const displayHeight = Math.max(1, Math.floor(height * ratio));
            if (canvas.width !== displayWidth || canvas.height !== displayHeight) {
                canvas.width = displayWidth;
                canvas.height = displayHeight;
            }
        }

        function drawWaveform() {
            const canvas = elements.waveCanvas;
            resizeCanvas(canvas);
            const context = canvas.getContext("2d");
            const width = canvas.width;
            const height = canvas.height;

            context.clearRect(0, 0, width, height);

            const gradient = context.createLinearGradient(0, 0, 0, height);
            gradient.addColorStop(0, "rgba(26, 34, 39, 0.98)");
            gradient.addColorStop(1, "rgba(11, 17, 20, 0.98)");
            context.fillStyle = gradient;
            context.fillRect(0, 0, width, height);

            const centerY = height / 2;
            context.strokeStyle = "rgba(255, 255, 255, 0.08)";
            context.lineWidth = 1;
            context.beginPath();
            context.moveTo(0, centerY);
            context.lineTo(width, centerY);
            context.stroke();

            if (!state.waveformEnvelope.length) {
                context.fillStyle = "rgba(233, 241, 243, 0.45)";
                context.font = `${Math.max(16, Math.round(height * 0.06))}px "Avenir Next"`;
                context.textAlign = "center";
                context.fillText("Load a file to draw the waveform preview", width / 2, centerY);
                return;
            }

            const visible = getVisibleWindow();
            const visibleDuration = Math.max(visible.duration, 0.001);
            const timeToX = (time) => ((time - visible.start) / visibleDuration) * width;
            const clampVisible = (time) => clamp(time, visible.start, visible.end);
            const selectionVisibleStart = clampVisible(state.selectionStart);
            const selectionVisibleEnd = clampVisible(state.selectionEnd);

            if (selectionVisibleEnd > selectionVisibleStart) {
                const selectionX = timeToX(selectionVisibleStart);
                const selectionWidth = Math.max(2, timeToX(selectionVisibleEnd) - selectionX);

                context.fillStyle = "rgba(255, 138, 61, 0.14)";
                context.fillRect(selectionX, 0, selectionWidth, height);
                context.strokeStyle = "rgba(255, 138, 61, 0.82)";
                context.lineWidth = 2;
                context.beginPath();
                context.moveTo(selectionX, 0);
                context.lineTo(selectionX, height);
                context.moveTo(selectionX + selectionWidth, 0);
                context.lineTo(selectionX + selectionWidth, height);
                context.stroke();
            }

            for (const segment of state.segments) {
                if (segment.end < visible.start || segment.start > visible.end) {
                    continue;
                }
                const x = timeToX(clampVisible(segment.start));
                const segmentWidth = Math.max(2, timeToX(clampVisible(segment.end)) - x);
                const transientGradient = context.createLinearGradient(0, 0, 0, height);
                transientGradient.addColorStop(0, "rgba(255, 138, 61, 0.08)");
                transientGradient.addColorStop(0.5, "rgba(255, 138, 61, 0.24)");
                transientGradient.addColorStop(1, "rgba(255, 138, 61, 0.08)");
                context.fillStyle = transientGradient;
                context.fillRect(x, 0, segmentWidth, height);

                context.strokeStyle = "rgba(255, 138, 61, 0.82)";
                context.lineWidth = 2;
                context.beginPath();
                context.moveTo(x, 0);
                context.lineTo(x, height);
                context.moveTo(x + segmentWidth, 0);
                context.lineTo(x + segmentWidth, height);
                context.stroke();
            }

            const startSample = Math.floor((visible.start / state.duration) * state.monoSamples.length);
            const endSample = Math.max(startSample + 1, Math.ceil((visible.end / state.duration) * state.monoSamples.length));
            const visibleSamples = state.monoSamples.slice(startSample, endSample);
            const visibleEnvelope = computeEnvelope(visibleSamples, Math.max(180, Math.floor(width / 3)));
            const barWidth = width / visibleEnvelope.length;
            context.fillStyle = "rgba(224, 235, 238, 0.92)";
            for (let i = 0; i < visibleEnvelope.length; i += 1) {
                const amplitude = visibleEnvelope[i];
                const barHeight = Math.max(2, amplitude * (height * 0.82));
                const x = i * barWidth;
                const y = centerY - barHeight / 2;
                context.fillRect(x, y, Math.max(1, barWidth - 1), barHeight);
            }

            const currentTime = elements.audioPlayer.currentTime || 0;
            if (currentTime >= visible.start && currentTime <= visible.end) {
                const playheadX = timeToX(currentTime);
                context.strokeStyle = "rgba(200, 255, 122, 0.95)";
                context.lineWidth = 3;
                context.beginPath();
                context.moveTo(playheadX, 0);
                context.lineTo(playheadX, height);
                context.stroke();

                context.fillStyle = "rgba(200, 255, 122, 0.95)";
                context.beginPath();
                context.moveTo(playheadX - 7, 0);
                context.lineTo(playheadX + 7, 0);
                context.lineTo(playheadX, 10);
                context.closePath();
                context.fill();
            }
        }

        function stopPlaybackRedraw() {
            if (state.animationFrame !== null) {
                cancelAnimationFrame(state.animationFrame);
                state.animationFrame = null;
            }
        }

        function startPlaybackRedraw() {
            stopPlaybackRedraw();

            const tick = () => {
                drawWaveform();
                if (!elements.audioPlayer.paused && !elements.audioPlayer.ended) {
                    state.animationFrame = requestAnimationFrame(tick);
                } else {
                    state.animationFrame = null;
                }
            };

            state.animationFrame = requestAnimationFrame(tick);
        }

        function recomputeSegments() {
            const stress = Number(elements.stress.value);
            const selectionRms = getSelectedRmsValues();
            const snapshot = detectSegments(selectionRms, stress);
            state.segments = snapshot.segments.map((segment) => ({
                start: segment.start + state.selectionStart,
                end: segment.end + state.selectionStart,
            }));
            state.averageRms = snapshot.averageRms;

            elements.durationMetric.textContent = formatSeconds(state.duration);
            elements.selectionMetric.textContent = formatSeconds(getSelectionDuration());
            elements.countMetric.textContent = String(snapshot.segments.length);
            elements.thresholdMetric.textContent = snapshot.threshold.toFixed(2) + "x";
            elements.timeCenter.textContent = snapshot.segments.length
                ? snapshot.segments.length + " slices in selection"
                : "No slices in selection";

            renderSegments(state.segments);
            updateZoomUI();
            drawWaveform();
        }

        function selectionFromPointerEvent(event) {
            const visible = getVisibleWindow();
            const rect = elements.waveCanvas.getBoundingClientRect();
            const ratio = window.devicePixelRatio || 1;
            const x = clamp((event.clientX - rect.left) * ratio, 0, elements.waveCanvas.width);
            return visible.start + (x / elements.waveCanvas.width) * visible.duration;
        }

        function stopHandleDrag() {
            state.handleDrag = null;
        }

        function handleWaveformPointerDown(event) {
            if (!state.duration) {
                return;
            }
            if (state.handleDrag) {
                return;
            }
            elements.audioPlayer.currentTime = selectionFromPointerEvent(event);
            drawWaveform();
        }

        function beginHandleDrag(which, event) {
            if (!state.duration) {
                return;
            }
            event.preventDefault();
            event.stopPropagation();
            state.handleDrag = which;
            state.activeHandle = which;
            if (which === "start") {
                elements.selectionStartHandle.focus();
            } else {
                elements.selectionEndHandle.focus();
            }
        }

        function handleHandlePointerMove(event) {
            if (!state.handleDrag) {
                return;
            }
            const time = selectionFromPointerEvent(event);
            if (state.handleDrag === "start") {
                setSelection(time, state.selectionEnd, { followHandle: true, handle: "start" });
            } else {
                setSelection(state.selectionStart, time, { followHandle: true, handle: "end" });
            }
        }

        function nudgeHandle(which, deltaSeconds) {
            if (!state.duration) {
                return;
            }
            if (which === "start") {
                setSelection(state.selectionStart + deltaSeconds, state.selectionEnd, { followHandle: true, handle: "start" });
            } else {
                setSelection(state.selectionStart, state.selectionEnd + deltaSeconds, { followHandle: true, handle: "end" });
            }
        }

        function handleHandleKeydown(which, event) {
            if (event.key === "ArrowLeft") {
                event.preventDefault();
                nudgeHandle(which, -0.01);
            } else if (event.key === "ArrowRight") {
                event.preventDefault();
                nudgeHandle(which, 0.01);
            }
        }

        function handleGlobalKeydown(event) {
            if (!state.activeHandle) {
                return;
            }

            const tagName = document.activeElement && document.activeElement.tagName
                ? document.activeElement.tagName.toLowerCase()
                : "";
            if (tagName === "input" || tagName === "textarea") {
                return;
            }

            if (event.key === "ArrowLeft") {
                event.preventDefault();
                nudgeHandle(state.activeHandle, -0.01);
            } else if (event.key === "ArrowRight") {
                event.preventDefault();
                nudgeHandle(state.activeHandle, 0.01);
            }
        }

        function playSelection() {
            if (!state.duration) {
                return;
            }
            elements.audioPlayer.currentTime = state.selectionStart;
            elements.audioPlayer.play().catch(() => {});
        }

        function resetPreview() {
            if (state.objectUrl) {
                URL.revokeObjectURL(state.objectUrl);
            }

            state.file = null;
            state.objectUrl = null;
            state.audioBuffer = null;
            state.monoSamples = null;
            state.waveformEnvelope = [];
            state.rmsValues = [];
            state.segments = [];
            state.averageRms = 0;
            state.duration = 0;
            state.zoom = 1;
            state.pan = 0.5;
            state.selectionStart = 0;
            state.selectionEnd = 0;
            state.handleDrag = null;
            state.activeHandle = null;
            stopPlaybackRedraw();
            state.busy = false;

            elements.audioFile.value = "";
            elements.audioPlayer.removeAttribute("src");
            elements.audioPlayer.load();
            elements.fileTitle.textContent = "Drop audio here or click to browse";
            elements.fileSubtitle.textContent = "Select a file to preview and slice.";
            elements.fileSizePill.textContent = "No file selected";
            elements.fileTypePill.textContent = "Preview idle";
            elements.zoom.value = "1";
            elements.pan.value = "50";
            elements.selectionStartDbValue.textContent = "--.- dB";
            elements.selectionEndDbValue.textContent = "--.- dB";
            elements.selectionStartDbValue.style.color = "var(--muted)";
            elements.selectionEndDbValue.style.color = "var(--muted)";
            elements.durationMetric.textContent = "0.00s";
            elements.selectionMetric.textContent = "0.00s";
            elements.countMetric.textContent = "0";
            elements.thresholdMetric.textContent = (1.05 + (Number(elements.stress.value) / 100) * 1.65).toFixed(2) + "x";
            elements.timeStart.textContent = "0.00s";
            elements.timeCenter.textContent = "Load a file to preview";
            elements.timeEnd.textContent = "0.00s";
            syncSelectionInputs();
            updateZoomUI();
            elements.processButton.disabled = true;
            elements.drumModeButton.disabled = true;
            elements.segmentsList.innerHTML = '<div class="empty-state">Upload a file to see slices.</div>';
            setStatus("Select a file to begin.");
            drawWaveform();
        }

        async function loadFile(file) {
            resetPreview();
            state.file = file;

            elements.fileTitle.textContent = file.name;
            elements.fileSubtitle.textContent = "Preview loaded locally.";
            elements.fileSizePill.textContent = formatFileSize(file.size);
            elements.fileTypePill.textContent = file.type || "Unknown MIME type";
            setStatus("Decoding audio for preview...");

            try {
                const arrayBuffer = await file.arrayBuffer();
                const audioBuffer = await audioContext.decodeAudioData(arrayBuffer.slice(0));
                const monoSamples = averageChannels(audioBuffer);

                state.audioBuffer = audioBuffer;
                state.monoSamples = monoSamples;
                state.duration = audioBuffer.duration;
                state.zoom = 1;
                state.pan = 0.5;
                state.selectionStart = 0;
                state.selectionEnd = audioBuffer.duration;
                state.rmsValues = computeRmsValues(monoSamples, audioBuffer.sampleRate, WINDOW_SECONDS);
                state.waveformEnvelope = computeEnvelope(monoSamples, 420);

                state.objectUrl = URL.createObjectURL(file);
                elements.audioPlayer.src = state.objectUrl;
                elements.processButton.disabled = false;
                elements.drumModeButton.disabled = false;
                elements.zoom.value = "1";
                elements.pan.value = "50";

                syncSelectionInputs();
                recomputeSegments();
                setStatus("Preview ready.", "success");
            } catch (error) {
                console.error(error);
                elements.fileTypePill.textContent = "Preview failed";
                elements.processButton.disabled = false;
                elements.drumModeButton.disabled = false;
                setStatus("Preview failed. You can still process the file.", "error");
                drawWaveform();
            }
        }

        async function processFile() {
            if (!state.file || state.busy) {
                return;
            }

            state.busy = true;
            elements.processButton.disabled = true;
            setStatus("Processing audio and packaging slices...");

            const formData = new FormData();
            formData.append("audio_file", state.file);
            formData.append("stress", elements.stress.value);
            if (state.duration > 0) {
                formData.append("start_time", state.selectionStart.toFixed(3));
                formData.append("end_time", state.selectionEnd.toFixed(3));
            }

            try {
                const response = await fetch("/process", {
                    method: "POST",
                    body: formData,
                });

                if (!response.ok) {
                    let detail = "Processing failed.";
                    try {
                        const payload = await response.json();
                        if (payload && payload.detail) {
                            detail = payload.detail;
                        }
                    } catch (jsonError) {
                        detail = await response.text() || detail;
                    }
                    throw new Error(detail);
                }

                const blob = await response.blob();
                const downloadUrl = URL.createObjectURL(blob);
                const link = document.createElement("a");
                link.href = downloadUrl;
                link.download = "transient_slices.zip";
                document.body.appendChild(link);
                link.click();
                link.remove();
                URL.revokeObjectURL(downloadUrl);

                setStatus("ZIP downloaded.", "success");
            } catch (error) {
                console.error(error);
                setStatus(error.message || "Processing failed.", "error");
            } finally {
                state.busy = false;
                elements.processButton.disabled = !state.file;
                elements.drumModeButton.disabled = !state.file;
            }
        }

        async function launchDrumMode() {
            if (!state.file || state.busy) {
                return;
            }

            state.busy = true;
            elements.processButton.disabled = true;
            elements.drumModeButton.disabled = true;
            setStatus("Building drum session...");

            const formData = new FormData();
            formData.append("audio_file", state.file);
            formData.append("stress", elements.stress.value);
            if (state.duration > 0) {
                formData.append("start_time", state.selectionStart.toFixed(3));
                formData.append("end_time", state.selectionEnd.toFixed(3));
            }

            try {
                const response = await fetch("/drum-mode/session", {
                    method: "POST",
                    body: formData,
                });

                if (!response.ok) {
                    let detail = "Drum mode failed.";
                    try {
                        const payload = await response.json();
                        if (payload && payload.detail) {
                            detail = payload.detail;
                        }
                    } catch (jsonError) {
                        detail = await response.text() || detail;
                    }
                    throw new Error(detail);
                }

                const payload = await response.json();
                if (!payload || !payload.redirect_url) {
                    throw new Error("Drum mode session did not return a redirect.");
                }

                window.location.href = payload.redirect_url;
            } catch (error) {
                console.error(error);
                setStatus(error.message || "Drum mode failed.", "error");
                state.busy = false;
                elements.processButton.disabled = !state.file;
                elements.drumModeButton.disabled = !state.file;
            }
        }

        elements.audioFile.addEventListener("change", (event) => {
            const [file] = event.target.files || [];
            if (file) {
                loadFile(file);
            }
        });

        ["dragenter", "dragover"].forEach((eventName) => {
            elements.fileDrop.addEventListener(eventName, (event) => {
                event.preventDefault();
                elements.fileDrop.classList.add("dragging");
            });
        });

        ["dragleave", "drop"].forEach((eventName) => {
            elements.fileDrop.addEventListener(eventName, (event) => {
                event.preventDefault();
                elements.fileDrop.classList.remove("dragging");
            });
        });

        elements.fileDrop.addEventListener("drop", (event) => {
            const file = event.dataTransfer && event.dataTransfer.files ? event.dataTransfer.files[0] : null;
            if (file) {
                elements.audioFile.files = event.dataTransfer.files;
                loadFile(file);
            }
        });

        elements.stress.addEventListener("input", updateStressUI);
        elements.zoom.addEventListener("input", updateZoomUI);
        elements.pan.addEventListener("input", updateZoomUI);
        elements.setStartButton.addEventListener("click", () => setSelection(elements.audioPlayer.currentTime || 0, state.selectionEnd));
        elements.setEndButton.addEventListener("click", () => setSelection(state.selectionStart, elements.audioPlayer.currentTime || state.selectionEnd));
        elements.resetSelectionButton.addEventListener("click", () => setSelection(0, state.duration));
        elements.playSelectionButton.addEventListener("click", playSelection);
        elements.drumModeButton.addEventListener("click", launchDrumMode);
        elements.processButton.addEventListener("click", processFile);
        elements.resetButton.addEventListener("click", resetPreview);
        elements.waveCanvas.addEventListener("pointerdown", handleWaveformPointerDown);
        elements.selectionStartHandle.addEventListener("pointerdown", (event) => beginHandleDrag("start", event));
        elements.selectionEndHandle.addEventListener("pointerdown", (event) => beginHandleDrag("end", event));
        elements.selectionStartHandle.addEventListener("focus", () => {
            state.activeHandle = "start";
        });
        elements.selectionEndHandle.addEventListener("focus", () => {
            state.activeHandle = "end";
        });
        elements.selectionStartHandle.addEventListener("keydown", (event) => handleHandleKeydown("start", event));
        elements.selectionEndHandle.addEventListener("keydown", (event) => handleHandleKeydown("end", event));
        window.addEventListener("pointermove", handleHandlePointerMove);
        window.addEventListener("pointerup", stopHandleDrag);
        elements.audioPlayer.addEventListener("timeupdate", () => {
            if (elements.audioPlayer.currentTime >= state.selectionEnd && !elements.audioPlayer.paused) {
                elements.audioPlayer.pause();
            }
            drawWaveform();
        });
        elements.audioPlayer.addEventListener("play", startPlaybackRedraw);
        elements.audioPlayer.addEventListener("pause", () => {
            stopPlaybackRedraw();
            drawWaveform();
        });
        elements.audioPlayer.addEventListener("ended", () => {
            stopPlaybackRedraw();
            drawWaveform();
        });
        elements.audioPlayer.addEventListener("seeked", drawWaveform);
        window.addEventListener("keydown", handleGlobalKeydown);
        window.addEventListener("resize", () => {
            drawWaveform();
            updateWaveHandles();
        });

        updateStressUI();
        drawWaveform();
    </script>
</body>
</html>
"""


def render_index_html(stress: int) -> str:
    return INDEX_HTML.replace("__DEFAULT_STRESS__", str(stress))


def note_name_from_index(index: int) -> str:
    notes = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    midi = DRUM_BASE_MIDI + index
    octave = (midi // 12) - 1
    return f"{notes[midi % 12]}{octave}"


def render_drum_mode_html(session_id: str, sample_count: int) -> str:
    samples = [
        {
            "index": index,
            "name": f"slice_{index + 1:03d}.wav",
            "note": note_name_from_index(index),
            "url": f"/drum-mode/session/{session_id}/sample/{index}",
        }
        for index in range(sample_count)
    ]
    session_json = json.dumps(
        {
            "sessionId": session_id,
            "samples": samples,
            "keys": list(DRUM_KEYS),
            "bankSize": DRUM_BANK_SIZE,
        }
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>transient drum mode</title>
    <style>
        :root {{
            --bg: #0b1013;
            --panel: #151d22;
            --panel-2: #1d272d;
            --line: #2b3940;
            --ink: #edf2f4;
            --muted: #83939b;
            --accent: #ff8a3d;
            --display: #c8ff7a;
            --danger: #ff6b5d;
        }}
        * {{ box-sizing: border-box; }}
        html {{ color-scheme: dark; }}
        body {{
            margin: 0;
            min-height: 100vh;
            font-family: "IBM Plex Sans", sans-serif;
            background:
                radial-gradient(circle at top, rgba(255,138,61,0.08), transparent 24%),
                var(--bg);
            color: var(--ink);
        }}
        .shell {{
            width: min(1400px, calc(100vw - 2rem));
            margin: 0 auto;
            padding: 1.25rem 0 2rem;
        }}
        .topbar, .bank-bar, .pad-wrap {{
            background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(0,0,0,0.16)), var(--panel);
            border: 1px solid var(--line);
            border-radius: 18px;
            box-shadow: 0 18px 40px rgba(0,0,0,0.4);
        }}
        .topbar {{
            display: flex;
            flex-wrap: wrap;
            justify-content: space-between;
            gap: 1rem;
            align-items: center;
            padding: 1rem 1.2rem;
        }}
        .eyebrow {{
            margin: 0 0 0.55rem;
            color: var(--accent);
            font-size: 0.74rem;
            text-transform: uppercase;
            letter-spacing: 0.16em;
            font-family: "IBM Plex Mono", monospace;
        }}
        h1 {{
            margin: 0;
            font-size: clamp(1.5rem, 4vw, 2.4rem);
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }}
        .display {{
            padding: 0.55rem 0.8rem;
            border-radius: 999px;
            background: #12190f;
            border: 1px solid rgba(200,255,122,0.18);
            color: var(--display);
            font-family: "IBM Plex Mono", monospace;
            font-size: 0.9rem;
        }}
        .bank-bar {{
            margin-top: 1rem;
            padding: 0.9rem 1rem;
            display: flex;
            flex-wrap: wrap;
            justify-content: space-between;
            gap: 1rem;
            align-items: center;
        }}
        .bank-meta {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.6rem;
            align-items: center;
        }}
        .chip {{
            padding: 0.45rem 0.7rem;
            border-radius: 999px;
            background: #10171b;
            border: 1px solid #314148;
            color: var(--display);
            font-family: "IBM Plex Mono", monospace;
            font-size: 0.82rem;
        }}
        .actions {{
            display: flex;
            gap: 0.65rem;
            flex-wrap: wrap;
        }}
        button, a.button {{
            appearance: none;
            text-decoration: none;
            color: inherit;
            border: 1px solid #34454c;
            background: #141d21;
            padding: 0.85rem 1rem;
            border-radius: 10px;
            cursor: pointer;
            font-family: "IBM Plex Mono", monospace;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-size: 0.8rem;
        }}
        .primary {{
            color: #261103;
            background: linear-gradient(180deg, #ffb26d, #ff8a3d);
            border-color: #7b461f;
        }}
        .pad-wrap {{
            margin-top: 1rem;
            padding: 1rem;
            overflow-x: auto;
        }}
        .pads {{
            display: flex;
            gap: 0.8rem;
            min-height: 210px;
            align-items: stretch;
            width: max-content;
            min-width: 100%;
        }}
        .pad {{
            width: 128px;
            min-width: 128px;
            padding: 0.9rem;
            border-radius: 16px;
            border: 1px solid #33434a;
            background:
                linear-gradient(180deg, rgba(255,255,255,0.04), rgba(0,0,0,0.22)),
                var(--panel-2);
            display: grid;
            gap: 0.55rem;
            align-content: space-between;
            user-select: none;
        }}
        .pad.active {{
            border-color: var(--accent);
            box-shadow: 0 0 0 1px rgba(255,138,61,0.18), 0 0 24px rgba(255,138,61,0.16);
            transform: translateY(-1px);
        }}
        .pad.offbank {{
            opacity: 0.38;
        }}
        .keycap {{
            width: 2rem;
            height: 2rem;
            display: grid;
            place-items: center;
            border-radius: 8px;
            background: #0e1417;
            border: 1px solid #36474f;
            color: var(--display);
            font-family: "IBM Plex Mono", monospace;
            font-size: 0.92rem;
        }}
        .note {{
            font-family: "IBM Plex Mono", monospace;
            color: var(--accent);
            font-size: 0.84rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }}
        .sample-name {{
            font-size: 0.9rem;
            line-height: 1.35;
            color: var(--ink);
            word-break: break-word;
        }}
        .slot {{
            color: var(--muted);
            font-size: 0.82rem;
            font-family: "IBM Plex Mono", monospace;
        }}
        .help {{
            margin-top: 1rem;
            color: var(--muted);
            font-size: 0.92rem;
            line-height: 1.55;
        }}
        .help strong {{ color: var(--ink); }}
        @media (max-width: 720px) {{
            .shell {{ width: min(100vw - 1rem, 100%); }}
            .pad {{ width: 112px; min-width: 112px; }}
        }}
    </style>
</head>
<body>
    <main class="shell">
        <section class="topbar">
            <div>
                <p class="eyebrow">transient drum mode</p>
                <h1>Slice Sampler</h1>
            </div>
            <div class="display" id="statusDisplay">Ready</div>
        </section>

        <section class="bank-bar">
            <div class="bank-meta">
                <span class="chip" id="bankChip">Bank C0</span>
                <span class="chip" id="rangeChip">Slices 1-11</span>
                <span class="chip" id="sampleChip">{sample_count} slices</span>
            </div>
            <div class="actions">
                <button id="bankDownButton" type="button">Bank Down (Z)</button>
                <button id="bankUpButton" type="button">Bank Up (X)</button>
                <a class="button primary" href="/drum-mode/session/{session_id}/download">Download ZIP</a>
                <a class="button" href="/">Back</a>
            </div>
        </section>

        <section class="pad-wrap">
            <div class="pads" id="pads"></div>
        </section>

        <p class="help">
            <strong>Keyboard:</strong> use <code>{DRUM_KEYS}</code> to trigger pads in the current bank.
            Press <code>z</code> to move down a bank and <code>x</code> to move up. Playback is monophonic,
            so each new hit stops the previous sample.
        </p>
    </main>

    <script>
        const DRUM_MODE = {session_json};
        const state = {{
            bank: 0,
            currentAudio: null,
            activePad: null,
        }};
        const elements = {{
            pads: document.getElementById("pads"),
            bankChip: document.getElementById("bankChip"),
            rangeChip: document.getElementById("rangeChip"),
            sampleChip: document.getElementById("sampleChip"),
            statusDisplay: document.getElementById("statusDisplay"),
            bankDownButton: document.getElementById("bankDownButton"),
            bankUpButton: document.getElementById("bankUpButton"),
        }};

        function updateStatus(message) {{
            elements.statusDisplay.textContent = message;
        }}

        function getBankCount() {{
            return Math.max(1, Math.ceil(DRUM_MODE.samples.length / DRUM_MODE.bankSize));
        }}

        function stopCurrentAudio() {{
            if (!state.currentAudio) {{
                return;
            }}
            state.currentAudio.pause();
            state.currentAudio.currentTime = 0;
            state.currentAudio = null;
            if (state.activePad) {{
                state.activePad.classList.remove("active");
                state.activePad = null;
            }}
        }}

        function playSample(sampleIndex) {{
            const sample = DRUM_MODE.samples[sampleIndex];
            if (!sample) {{
                return;
            }}

            stopCurrentAudio();
            const audio = new Audio(sample.url);
            const pad = document.querySelector(`[data-sample-index="${{sampleIndex}}"]`);
            if (pad) {{
                pad.classList.add("active");
                state.activePad = pad;
            }}
            state.currentAudio = audio;
            updateStatus(`Playing ${{sample.note}}`);
            audio.addEventListener("ended", () => {{
                if (state.currentAudio === audio) {{
                    stopCurrentAudio();
                    updateStatus("Ready");
                }}
            }});
            audio.play().catch(() => {{
                stopCurrentAudio();
                updateStatus("Playback blocked");
            }});
        }}

        function renderPads() {{
            const bankOffset = state.bank * DRUM_MODE.bankSize;
            const keys = DRUM_MODE.keys;
            elements.pads.innerHTML = DRUM_MODE.samples.map((sample, index) => {{
                const localIndex = index - bankOffset;
                const onBank = localIndex >= 0 && localIndex < keys.length;
                const keyLabel = onBank ? keys[localIndex].toUpperCase() : "·";
                return `
                    <button
                        class="pad${{onBank ? "" : " offbank"}}"
                        type="button"
                        data-sample-index="${{index}}"
                        ${{onBank ? "" : "tabindex='-1'"}}
                    >
                        <div class="keycap">${{keyLabel}}</div>
                        <div class="note">${{sample.note}}</div>
                        <div class="sample-name">${{sample.name}}</div>
                        <div class="slot">slot ${{index + 1}}</div>
                    </button>
                `;
            }}).join("");

            const start = bankOffset + 1;
            const end = Math.min(DRUM_MODE.samples.length, bankOffset + DRUM_MODE.bankSize);
            const firstNote = DRUM_MODE.samples[bankOffset] ? DRUM_MODE.samples[bankOffset].note : DRUM_MODE.samples[0].note;
            elements.bankChip.textContent = `Bank ${{firstNote}}`;
            elements.rangeChip.textContent = start <= end ? `Slices ${{start}}-${{end}}` : "No slices";

            elements.pads.querySelectorAll(".pad").forEach((pad) => {{
                pad.addEventListener("click", () => {{
                    const index = Number(pad.dataset.sampleIndex);
                    const bankStart = state.bank * DRUM_MODE.bankSize;
                    const bankEnd = bankStart + DRUM_MODE.bankSize;
                    if (index >= bankStart && index < bankEnd) {{
                        playSample(index);
                    }}
                }});
            }});
        }}

        function moveBank(delta) {{
            const next = Math.max(0, Math.min(getBankCount() - 1, state.bank + delta));
            if (next === state.bank) {{
                return;
            }}
            state.bank = next;
            stopCurrentAudio();
            renderPads();
            updateStatus(`Bank ${{state.bank + 1}} / ${{getBankCount()}}`);
        }}

        function handleKeydown(event) {{
            if (event.repeat) {{
                return;
            }}
            const key = event.key.toLowerCase();
            if (key === "z") {{
                event.preventDefault();
                moveBank(-1);
                return;
            }}
            if (key === "x") {{
                event.preventDefault();
                moveBank(1);
                return;
            }}

            const localIndex = DRUM_MODE.keys.indexOf(key);
            if (localIndex === -1) {{
                return;
            }}
            const sampleIndex = state.bank * DRUM_MODE.bankSize + localIndex;
            if (sampleIndex >= DRUM_MODE.samples.length) {{
                return;
            }}
            event.preventDefault();
            playSample(sampleIndex);
        }}

        elements.bankDownButton.addEventListener("click", () => moveBank(-1));
        elements.bankUpButton.addEventListener("click", () => moveBank(1));
        window.addEventListener("keydown", handleKeydown);
        renderPads();
    </script>
</body>
</html>"""


def _cleanup_expired_sessions() -> None:
    cutoff = time.time() - SESSION_TTL_SECONDS
    expired = [session_id for session_id, session in DRUM_SESSIONS.items() if session.created_at < cutoff]
    for session_id in expired:
        session = DRUM_SESSIONS.pop(session_id, None)
        if session:
            shutil.rmtree(session.temp_dir, ignore_errors=True)


async def generate_slices_bundle(
    audio_file: UploadFile,
    stress: int,
    start_time: float,
    end_time: float | None,
) -> tuple[Path, list[Path], Path]:
    if not 0 <= stress <= 100:
        raise HTTPException(status_code=400, detail="Stress must be between 0 and 100.")

    suffix = Path(audio_file.filename or "upload.wav").suffix or ".wav"
    temp_dir = Path(tempfile.mkdtemp(prefix="transient-"))

    try:
        ffmpeg_bin = ensure_ffmpeg()
        upload_path = temp_dir / f"source{suffix}"
        with upload_path.open("wb") as output_stream:
            shutil.copyfileobj(audio_file.file, output_stream)

        source_duration = probe_duration(upload_path, ffmpeg_bin)
        effective_end = source_duration if end_time is None else min(end_time, source_duration)
        effective_start = max(0.0, start_time)
        if effective_end <= effective_start:
            raise HTTPException(status_code=400, detail="Selected section must have a positive length.")

        target_source = upload_path
        if effective_start > 0.0 or effective_end < source_duration:
            target_source = temp_dir / f"selected{suffix}"
            run_ffmpeg(
                [
                    ffmpeg_bin,
                    "-y",
                    "-i",
                    str(upload_path),
                    "-ss",
                    f"{effective_start:.3f}",
                    "-to",
                    f"{effective_end:.3f}",
                    str(target_source),
                ]
            )

        slices_dir = temp_dir / "slices"
        slices_dir.mkdir(parents=True, exist_ok=True)
        slice_paths = extract_slices(target_source, slices_dir, stress, ffmpeg_bin)
        if not slice_paths:
            raise HTTPException(status_code=422, detail="No slices were generated.")

        archive_path = temp_dir / "transient_slices.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for slice_path in slice_paths:
                archive.write(slice_path, arcname=slice_path.name)

        return temp_dir, slice_paths, archive_path
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    finally:
        await audio_file.close()


app = FastAPI(title="transient")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(render_index_html(DEFAULT_STRESS))


@app.post("/process")
async def process_audio(
    background_tasks: BackgroundTasks,
    audio_file: UploadFile = File(...),
    stress: int = Form(...),
    start_time: float = Form(0.0),
    end_time: float | None = Form(None),
) -> FileResponse:
    try:
        temp_dir, _slice_paths, archive_path = await generate_slices_bundle(audio_file, stress, start_time, end_time)
    except FFmpegUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    background_tasks.add_task(shutil.rmtree, temp_dir, True)
    return FileResponse(
        path=archive_path,
        filename="transient_slices.zip",
        media_type="application/zip",
        background=background_tasks,
    )


def get_drum_session_or_404(session_id: str) -> DrumSession:
    with DRUM_SESSION_LOCK:
        _cleanup_expired_sessions()
        session = DRUM_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Drum session not found.")
    return session


@app.post("/drum-mode/session")
async def create_drum_mode_session(
    audio_file: UploadFile = File(...),
    stress: int = Form(...),
    start_time: float = Form(0.0),
    end_time: float | None = Form(None),
) -> dict[str, str]:
    try:
        temp_dir, slice_paths, archive_path = await generate_slices_bundle(audio_file, stress, start_time, end_time)
    except FFmpegUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    session_id = uuid4().hex
    with DRUM_SESSION_LOCK:
        _cleanup_expired_sessions()
        DRUM_SESSIONS[session_id] = DrumSession(
            temp_dir=temp_dir,
            slice_paths=slice_paths,
            archive_path=archive_path,
            created_at=time.time(),
        )

    return {"redirect_url": f"/drum-mode/session/{session_id}"}


@app.get("/drum-mode/session/{session_id}", response_class=HTMLResponse)
async def drum_mode_page(session_id: str) -> HTMLResponse:
    session = get_drum_session_or_404(session_id)
    return HTMLResponse(render_drum_mode_html(session_id, len(session.slice_paths)))


@app.get("/drum-mode/session/{session_id}/sample/{sample_index}")
async def drum_mode_sample(session_id: str, sample_index: int) -> FileResponse:
    session = get_drum_session_or_404(session_id)
    if not 0 <= sample_index < len(session.slice_paths):
        raise HTTPException(status_code=404, detail="Sample not found.")
    sample_path = session.slice_paths[sample_index]
    return FileResponse(path=sample_path, filename=sample_path.name, media_type="audio/wav")


@app.get("/drum-mode/session/{session_id}/download")
async def drum_mode_download(session_id: str) -> FileResponse:
    session = get_drum_session_or_404(session_id)
    return FileResponse(
        path=session.archive_path,
        filename="transient_slices.zip",
        media_type="application/zip",
    )
