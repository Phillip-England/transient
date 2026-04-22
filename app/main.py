from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from app.audio import FFmpegUnavailableError, ensure_ffmpeg, extract_slices, probe_duration, run_ffmpeg


DEFAULT_STRESS = 55

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>transient</title>
    <style>
        :root {
            --paper: #e7ecef;
            --paper-dark: #d4dde2;
            --ink: #162126;
            --muted: #55666f;
            --line: #b8c8cf;
            --line-strong: #7e959f;
            --panel: #f8fbfb;
            --panel-strong: #eef4f5;
            --accent: #1f6f78;
            --accent-deep: #154b57;
            --accent-soft: #cfe2e4;
            --wave: #1a252b;
            --wave-soft: rgba(26, 37, 43, 0.16);
            --transient: rgba(31, 111, 120, 0.2);
            --transient-strong: #1f6f78;
            --success: #2d6a4f;
            --shadow: 0 8px 0 rgba(126, 149, 159, 0.24);
            --radius-xl: 18px;
            --radius-lg: 12px;
            --radius-md: 10px;
        }

        * {
            box-sizing: border-box;
        }

        html {
            color-scheme: light;
        }

        body {
            margin: 0;
            min-height: 100vh;
            font-family: "Avenir Next", "Helvetica Neue", "Segoe UI", sans-serif;
            color: var(--ink);
            background:
                linear-gradient(180deg, rgba(255, 255, 255, 0.38), rgba(255, 255, 255, 0.08)),
                var(--paper);
        }

        body::before {
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            background-image:
                linear-gradient(rgba(86, 109, 117, 0.045) 1px, transparent 1px),
                linear-gradient(90deg, rgba(86, 109, 117, 0.035) 1px, transparent 1px);
            background-size: 24px 24px;
            opacity: 0.5;
        }

        .shell {
            width: min(1200px, calc(100vw - 2rem));
            margin: 0 auto;
            padding: 2rem 0 3rem;
        }

        .topbar,
        .workspace,
        .download-panel {
            border: 2px solid var(--line-strong);
            background: var(--panel);
            box-shadow: var(--shadow);
        }

        .topbar {
            padding: 1rem 1.25rem;
            border-radius: var(--radius-xl);
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            position: relative;
        }

        .topbar::after {
            content: "";
            position: absolute;
            left: 14px;
            right: 14px;
            bottom: 10px;
            border-bottom: 1px dashed var(--line);
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
            font-size: clamp(1.8rem, 4vw, 2.8rem);
            line-height: 1;
            letter-spacing: -0.02em;
            text-transform: uppercase;
        }

        .subtle {
            margin: 0;
            font-size: 0.9rem;
            color: var(--muted);
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
        }

        .workspace {
            margin-top: 1.25rem;
            padding: 1.25rem;
            border-radius: 18px;
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
        }

        .section-title {
            margin: 0 0 0.65rem;
            font-size: 0.86rem;
            text-transform: uppercase;
            letter-spacing: 0.14em;
            color: var(--accent-deep);
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
        }

        .file-drop {
            position: relative;
            display: grid;
            gap: 0.65rem;
            align-content: center;
            min-height: 170px;
            padding: 1.4rem;
            border: 2px dashed var(--line-strong);
            border-radius: var(--radius-lg);
            background: #f3f8f8;
            transition: border-color 150ms ease, transform 150ms ease, background-color 150ms ease;
        }

        .file-drop.dragging {
            border-color: var(--accent);
            transform: translateY(-1px) rotate(-0.2deg);
            background: #e4eff1;
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
            background: #dde9eb;
            border: 1px solid #bfd1d6;
            font-size: 0.82rem;
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
            color: var(--accent-deep);
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
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
            height: 12px;
            border-radius: 999px;
            border: 1px solid var(--line-strong);
            background: linear-gradient(90deg, #d6e1e4, #c7d9de);
            outline: none;
        }

        input[type="range"]::-webkit-slider-thumb {
            appearance: none;
            width: 28px;
            height: 28px;
            border-radius: 8px;
            border: 2px solid #f4fbfb;
            background: var(--accent);
            box-shadow: 2px 2px 0 rgba(21, 75, 87, 0.35);
            cursor: pointer;
        }

        input[type="range"]::-moz-range-thumb {
            width: 28px;
            height: 28px;
            border-radius: 8px;
            border: 2px solid #f4fbfb;
            background: var(--accent);
            box-shadow: 2px 2px 0 rgba(21, 75, 87, 0.35);
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
        }

        .audio-bar {
            display: flex;
            flex-wrap: wrap;
            justify-content: space-between;
            gap: 0.75rem;
            margin-bottom: 0.9rem;
        }

        .selection-panel {
            margin-bottom: 1rem;
            padding: 0.9rem;
            border: 1px solid var(--line);
            border-radius: var(--radius-lg);
            background: #f6fafb;
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
            background: #fbfdfd;
            border: 1px solid #d2e0e4;
        }

        .selection-chip-label {
            margin: 0;
            font-size: 0.72rem;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.12em;
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
        }

        .selection-chip-value {
            margin: 0.3rem 0 0;
            font-size: 1.15rem;
            color: var(--accent-deep);
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
        }

        .selection-ranges {
            position: relative;
            margin-top: 0.9rem;
            padding: 1rem 0 0.2rem;
        }

        .selection-track {
            position: absolute;
            left: 0;
            right: 0;
            top: 1.45rem;
            height: 12px;
            border-radius: 999px;
            border: 1px solid var(--line-strong);
            background: linear-gradient(90deg, #d6e1e4, #c7d9de);
            overflow: hidden;
        }

        .selection-fill {
            position: absolute;
            top: 0;
            bottom: 0;
            background: linear-gradient(90deg, rgba(31, 111, 120, 0.3), rgba(31, 111, 120, 0.45));
            border-left: 2px solid var(--accent);
            border-right: 2px solid var(--accent);
        }

        .selection-ranges input[type="range"] {
            position: relative;
            margin: 0;
            background: transparent;
        }

        .selection-ranges input[type="range"]::-webkit-slider-runnable-track {
            height: 12px;
            background: transparent;
        }

        .selection-ranges input[type="range"]::-moz-range-track {
            height: 12px;
            background: transparent;
        }

        .selection-actions {
            display: flex;
            flex-wrap: wrap;
            gap: 0.6rem;
            margin-top: 0.85rem;
        }

        .ghost {
            color: var(--accent-deep);
            background: #e4eff1;
            border: 1px solid #c3d5d9;
        }

        audio {
            width: min(100%, 420px);
            filter: saturate(0.7) contrast(1.05);
        }

        .canvas-shell {
            position: relative;
            overflow: hidden;
            border-radius: 12px;
            border: 2px solid #c5d6dc;
            background: #edf4f5;
        }

        canvas {
            display: block;
            width: 100%;
            height: 320px;
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
            background: #fbfdfd;
            border: 1px solid #d2e0e4;
        }

        .metric-label {
            margin: 0;
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.14em;
            color: var(--accent-deep);
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
        }

        .metric-value {
            margin: 0.45rem 0 0;
            font-size: 1.8rem;
            line-height: 1;
            font-family: "IBM Plex Mono", "SFMono-Regular", "Menlo", monospace;
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
            background: #fbfdfd;
            border: 1px solid #d2e0e4;
        }

        .segment-index {
            width: 2rem;
            height: 2rem;
            display: grid;
            place-items: center;
            border-radius: 8px;
            background: var(--accent-soft);
            border: 1px solid #b8d1d6;
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
            background: #f1f7f8;
            border: 2px dashed #bfd0d6;
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
            color: #8a1f13;
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
            border-radius: 10px;
            padding: 0.95rem 1.35rem;
            font: inherit;
            font-weight: 700;
            cursor: pointer;
            transition: transform 140ms ease, filter 140ms ease, opacity 140ms ease;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            font-size: 0.86rem;
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
            color: #fff8f0;
            background: var(--accent);
            box-shadow: 3px 3px 0 rgba(21, 75, 87, 0.35);
        }

        .secondary {
            color: var(--ink);
            background: #dce8ea;
            border: 1px solid #bfd0d5;
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
            border: 1px solid rgba(0, 0, 0, 0.08);
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
                height: 240px;
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
                        <audio id="audioPlayer" controls preload="metadata"></audio>
                    </div>

                    <section class="selection-panel">
                        <div class="selection-head">
                            <p class="section-title">Section</p>
                            <p class="subtle" id="selectionFeedback">Full file selected</p>
                        </div>

                        <div class="selection-values">
                            <div class="selection-chip">
                                <p class="selection-chip-label">Start</p>
                                <p class="selection-chip-value" id="selectionStartValue">0.00s</p>
                            </div>
                            <div class="selection-chip">
                                <p class="selection-chip-label">End</p>
                                <p class="selection-chip-value" id="selectionEndValue">0.00s</p>
                            </div>
                            <div class="selection-chip">
                                <p class="selection-chip-label">Length</p>
                                <p class="selection-chip-value" id="selectionLengthValue">0.00s</p>
                            </div>
                        </div>

                        <div class="selection-ranges">
                            <div class="selection-track">
                                <div class="selection-fill" id="selectionFill"></div>
                            </div>
                            <input id="selectionStart" type="range" min="0" max="100" value="0">
                            <input id="selectionEnd" type="range" min="0" max="100" value="100">
                        </div>

                        <div class="selection-actions">
                            <button class="ghost" id="setStartButton" type="button">Set Start To Playhead</button>
                            <button class="ghost" id="setEndButton" type="button">Set End To Playhead</button>
                            <button class="ghost" id="playSelectionButton" type="button">Play Selection</button>
                            <button class="ghost" id="resetSelectionButton" type="button">Use Full File</button>
                        </div>
                    </section>

                    <div class="canvas-shell">
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
            selectionStart: 0,
            selectionEnd: 0,
            selectionDrag: null,
            busy: false,
        };

        const elements = {
            audioFile: document.getElementById("audioFile"),
            audioPlayer: document.getElementById("audioPlayer"),
            fileDrop: document.getElementById("fileDrop"),
            fileTitle: document.getElementById("fileTitle"),
            fileSubtitle: document.getElementById("fileSubtitle"),
            fileSizePill: document.getElementById("fileSizePill"),
            fileTypePill: document.getElementById("fileTypePill"),
            stress: document.getElementById("stress"),
            stressValue: document.getElementById("stressValue"),
            stressMood: document.getElementById("stressMood"),
            stressDescription: document.getElementById("stressDescription"),
            selectionStart: document.getElementById("selectionStart"),
            selectionEnd: document.getElementById("selectionEnd"),
            selectionFill: document.getElementById("selectionFill"),
            selectionFeedback: document.getElementById("selectionFeedback"),
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

        function syncSelectionInputs() {
            const duration = Math.max(state.duration, 0.01);
            elements.selectionStart.max = String(duration);
            elements.selectionEnd.max = String(duration);
            elements.selectionStart.value = String(state.selectionStart);
            elements.selectionEnd.value = String(state.selectionEnd);

            const left = (state.selectionStart / duration) * 100;
            const right = (state.selectionEnd / duration) * 100;
            elements.selectionFill.style.left = left + "%";
            elements.selectionFill.style.width = Math.max(0, right - left) + "%";
            elements.selectionStartValue.textContent = formatSeconds(state.selectionStart);
            elements.selectionEndValue.textContent = formatSeconds(state.selectionEnd);
            elements.selectionLengthValue.textContent = formatSeconds(getSelectionDuration());
            elements.selectionMetric.textContent = formatSeconds(getSelectionDuration());

            const isFull = state.selectionStart <= 0.001 && Math.abs(state.selectionEnd - state.duration) <= 0.001;
            elements.selectionFeedback.textContent = isFull
                ? "Full file selected"
                : formatSeconds(state.selectionStart) + " to " + formatSeconds(state.selectionEnd);
        }

        function setSelection(start, end) {
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
            syncSelectionInputs();

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
            gradient.addColorStop(0, "rgba(255, 255, 255, 0.86)");
            gradient.addColorStop(1, "rgba(230, 239, 241, 0.98)");
            context.fillStyle = gradient;
            context.fillRect(0, 0, width, height);

            const centerY = height / 2;
            context.strokeStyle = "rgba(32, 25, 21, 0.14)";
            context.lineWidth = 1;
            context.beginPath();
            context.moveTo(0, centerY);
            context.lineTo(width, centerY);
            context.stroke();

            if (!state.waveformEnvelope.length) {
                context.fillStyle = "rgba(24, 20, 18, 0.45)";
                context.font = `${Math.max(16, Math.round(height * 0.06))}px "Avenir Next"`;
                context.textAlign = "center";
                context.fillText("Load a file to draw the waveform preview", width / 2, centerY);
                return;
            }

            const duration = state.duration || 1;
            const selectionX = (state.selectionStart / duration) * width;
            const selectionWidth = Math.max(2, ((state.selectionEnd - state.selectionStart) / duration) * width);

            context.fillStyle = "rgba(31, 111, 120, 0.12)";
            context.fillRect(selectionX, 0, selectionWidth, height);
            context.strokeStyle = "rgba(31, 111, 120, 0.8)";
            context.lineWidth = 2;
            context.beginPath();
            context.moveTo(selectionX, 0);
            context.lineTo(selectionX, height);
            context.moveTo(selectionX + selectionWidth, 0);
            context.lineTo(selectionX + selectionWidth, height);
            context.stroke();

            context.fillStyle = "rgba(231, 236, 239, 0.7)";
            context.fillRect(0, 0, selectionX, height);
            context.fillRect(selectionX + selectionWidth, 0, width - (selectionX + selectionWidth), height);

            for (const segment of state.segments) {
                const x = (segment.start / duration) * width;
                const segmentWidth = Math.max(2, ((segment.end - segment.start) / duration) * width);
                const transientGradient = context.createLinearGradient(0, 0, 0, height);
                transientGradient.addColorStop(0, "rgba(31, 111, 120, 0.08)");
                transientGradient.addColorStop(0.5, "rgba(31, 111, 120, 0.22)");
                transientGradient.addColorStop(1, "rgba(31, 111, 120, 0.08)");
                context.fillStyle = transientGradient;
                context.fillRect(x, 0, segmentWidth, height);

                context.strokeStyle = "rgba(31, 111, 120, 0.75)";
                context.lineWidth = 2;
                context.beginPath();
                context.moveTo(x, 0);
                context.lineTo(x, height);
                context.moveTo(x + segmentWidth, 0);
                context.lineTo(x + segmentWidth, height);
                context.stroke();
            }

            const barWidth = width / state.waveformEnvelope.length;
            context.fillStyle = "rgba(32, 25, 21, 0.92)";
            for (let i = 0; i < state.waveformEnvelope.length; i += 1) {
                const amplitude = state.waveformEnvelope[i];
                const barHeight = Math.max(2, amplitude * (height * 0.82));
                const x = i * barWidth;
                const y = centerY - barHeight / 2;
                context.fillRect(x, y, Math.max(1, barWidth - 1), barHeight);
            }
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
            elements.timeStart.textContent = formatSeconds(state.selectionStart);
            elements.timeCenter.textContent = snapshot.segments.length
                ? snapshot.segments.length + " slices in selection"
                : "No slices in selection";
            elements.timeEnd.textContent = formatSeconds(state.selectionEnd);

            renderSegments(state.segments);
            drawWaveform();
        }

        function updateSelectionFromInputs(activeInput) {
            const start = Number(elements.selectionStart.value);
            const end = Number(elements.selectionEnd.value);
            if (activeInput === "start" && start > end) {
                setSelection(start, start);
                return;
            }
            if (activeInput === "end" && end < start) {
                setSelection(end, end);
                return;
            }
            setSelection(start, end);
        }

        function selectionFromPointerEvent(event) {
            const rect = elements.waveCanvas.getBoundingClientRect();
            const ratio = window.devicePixelRatio || 1;
            const x = clamp((event.clientX - rect.left) * ratio, 0, elements.waveCanvas.width);
            return (x / elements.waveCanvas.width) * state.duration;
        }

        function stopSelectionDrag() {
            state.selectionDrag = null;
        }

        function handleSelectionPointerDown(event) {
            if (!state.duration) {
                return;
            }
            event.preventDefault();
            const time = selectionFromPointerEvent(event);
            state.selectionDrag = { anchor: time };
            setSelection(time, time + 0.05);
        }

        function handleSelectionPointerMove(event) {
            if (!state.selectionDrag) {
                return;
            }
            const time = selectionFromPointerEvent(event);
            setSelection(state.selectionDrag.anchor, time);
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
            state.selectionStart = 0;
            state.selectionEnd = 0;
            state.selectionDrag = null;
            state.busy = false;

            elements.audioFile.value = "";
            elements.audioPlayer.removeAttribute("src");
            elements.audioPlayer.load();
            elements.fileTitle.textContent = "Drop audio here or click to browse";
            elements.fileSubtitle.textContent = "Select a file to preview and slice.";
            elements.fileSizePill.textContent = "No file selected";
            elements.fileTypePill.textContent = "Preview idle";
            elements.durationMetric.textContent = "0.00s";
            elements.selectionMetric.textContent = "0.00s";
            elements.countMetric.textContent = "0";
            elements.thresholdMetric.textContent = (1.05 + (Number(elements.stress.value) / 100) * 1.65).toFixed(2) + "x";
            elements.timeStart.textContent = "0.00s";
            elements.timeCenter.textContent = "Load a file to preview";
            elements.timeEnd.textContent = "0.00s";
            syncSelectionInputs();
            elements.processButton.disabled = true;
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
                state.selectionStart = 0;
                state.selectionEnd = audioBuffer.duration;
                state.rmsValues = computeRmsValues(monoSamples, audioBuffer.sampleRate, WINDOW_SECONDS);
                state.waveformEnvelope = computeEnvelope(monoSamples, 420);

                state.objectUrl = URL.createObjectURL(file);
                elements.audioPlayer.src = state.objectUrl;
                elements.processButton.disabled = false;

                syncSelectionInputs();
                recomputeSegments();
                setStatus("Preview ready.", "success");
            } catch (error) {
                console.error(error);
                elements.fileTypePill.textContent = "Preview failed";
                elements.processButton.disabled = false;
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
        elements.selectionStart.addEventListener("input", () => updateSelectionFromInputs("start"));
        elements.selectionEnd.addEventListener("input", () => updateSelectionFromInputs("end"));
        elements.setStartButton.addEventListener("click", () => setSelection(elements.audioPlayer.currentTime || 0, state.selectionEnd));
        elements.setEndButton.addEventListener("click", () => setSelection(state.selectionStart, elements.audioPlayer.currentTime || state.selectionEnd));
        elements.resetSelectionButton.addEventListener("click", () => setSelection(0, state.duration));
        elements.playSelectionButton.addEventListener("click", playSelection);
        elements.processButton.addEventListener("click", processFile);
        elements.resetButton.addEventListener("click", resetPreview);
        elements.waveCanvas.addEventListener("pointerdown", handleSelectionPointerDown);
        window.addEventListener("pointermove", handleSelectionPointerMove);
        window.addEventListener("pointerup", stopSelectionDrag);
        elements.audioPlayer.addEventListener("timeupdate", () => {
            if (elements.audioPlayer.currentTime >= state.selectionEnd && !elements.audioPlayer.paused) {
                elements.audioPlayer.pause();
            }
        });
        window.addEventListener("resize", drawWaveform);

        updateStressUI();
        drawWaveform();
    </script>
</body>
</html>
"""


def render_index_html(stress: int) -> str:
    return INDEX_HTML.replace("__DEFAULT_STRESS__", str(stress))


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

        background_tasks.add_task(shutil.rmtree, temp_dir, True)
        return FileResponse(
            path=archive_path,
            filename="transient_slices.zip",
            media_type="application/zip",
            background=background_tasks,
        )
    except HTTPException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    except FFmpegUnavailableError as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeError as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        await audio_file.close()
