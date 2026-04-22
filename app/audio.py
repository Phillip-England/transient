from __future__ import annotations

import math
import os
import platform
import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class FFmpegUnavailableError(RuntimeError):
    """Raised when FFmpeg cannot be found or installed."""


@dataclass(frozen=True)
class SlicePoint:
    start: float
    end: float


def ensure_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    _attempt_ffmpeg_install()

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    raise FFmpegUnavailableError(
        "FFmpeg was not found and the automatic installation attempt did not succeed."
    )


def _attempt_ffmpeg_install() -> None:
    system = platform.system().lower()
    commands: list[list[str]] = []

    if system == "darwin" and shutil.which("brew"):
        commands.append(["brew", "install", "ffmpeg"])
    elif system == "linux":
        if shutil.which("apt-get"):
            commands.extend(
                [
                    ["apt-get", "update"],
                    ["apt-get", "install", "-y", "ffmpeg"],
                ]
            )
        elif shutil.which("dnf"):
            commands.append(["dnf", "install", "-y", "ffmpeg"])
        elif shutil.which("pacman"):
            commands.append(["pacman", "-Sy", "--noconfirm", "ffmpeg"])
    elif system == "windows":
        if shutil.which("winget"):
            commands.append(["winget", "install", "Gyan.FFmpeg"])
        elif shutil.which("choco"):
            commands.append(["choco", "install", "ffmpeg", "-y"])

    for command in commands:
        try:
            subprocess.run(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            continue


def transcode_to_wav(source: Path, target: Path, ffmpeg_bin: str) -> None:
    run_ffmpeg(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-sample_fmt",
            "s16",
            str(target),
        ]
    )


def extract_slices(
    source: Path,
    output_dir: Path,
    stress: int,
    ffmpeg_bin: str,
) -> list[Path]:
    analysis_wav = output_dir / "analysis.wav"
    transcode_to_wav(source, analysis_wav, ffmpeg_bin)

    segments = detect_transient_segments(analysis_wav, stress)
    if not segments:
        duration = probe_duration(analysis_wav, ffmpeg_bin)
        segments = [SlicePoint(0.0, duration)]

    output_files: list[Path] = []
    for index, segment in enumerate(segments, start=1):
        target = output_dir / f"slice_{index:03d}.wav"
        run_ffmpeg(
            [
                ffmpeg_bin,
                "-y",
                "-i",
                str(source),
                "-ss",
                f"{segment.start:.3f}",
                "-to",
                f"{segment.end:.3f}",
                str(target),
            ]
        )
        output_files.append(target)

    analysis_wav.unlink(missing_ok=True)
    return output_files


def detect_transient_segments(wav_path: Path, stress: int) -> list[SlicePoint]:
    frame_rate, window_rms = list_window_rms(wav_path)
    if not window_rms:
        return []

    average_rms = sum(window_rms) / len(window_rms)
    threshold_multiplier = 1.05 + (stress / 100.0) * 1.65
    threshold = average_rms * threshold_multiplier

    total_duration = len(window_rms) * 0.02
    pre_roll = max(0.01, 0.12 - (stress / 100.0) * 0.06)
    post_roll = 0.22 + (stress / 100.0) * 0.22
    min_gap = 0.08 + (stress / 100.0) * 0.22
    max_length = 0.45 + (stress / 100.0) * 0.55

    transient_times = [
        index * 0.02
        for index, rms in enumerate(window_rms)
        if rms >= threshold
    ]

    if not transient_times:
        return []

    merged: list[float] = []
    for point in transient_times:
        if not merged or point - merged[-1] >= min_gap:
            merged.append(point)

    boundaries = [0.0]
    for point in merged:
        boundaries.append(max(0.0, point - pre_roll))

    boundaries.append(total_duration)
    boundaries = sorted(set(boundaries))

    segments: list[SlicePoint] = []
    for start, end in pairwise(boundaries):
        adjusted_end = min(end, start + max_length)
        if adjusted_end - start >= 0.03:
            adjusted_end = min(total_duration, max(adjusted_end, start + post_roll))
            segments.append(SlicePoint(start=start, end=adjusted_end))

    if not segments:
        return []

    normalized: list[SlicePoint] = [segments[0]]
    for segment in segments[1:]:
        previous = normalized[-1]
        if segment.start <= previous.end:
            normalized[-1] = SlicePoint(previous.start, max(previous.end, segment.end))
        else:
            normalized.append(segment)

    return normalized


def list_window_rms(wav_path: Path, window_seconds: float = 0.02) -> tuple[int, list[float]]:
    with wave.open(str(wav_path), "rb") as wav_file:
        frame_rate = wav_file.getframerate()
        sample_width = wav_file.getsampwidth()
        frame_count = wav_file.getnframes()
        raw_frames = wav_file.readframes(frame_count)

    if sample_width != 2:
        raise RuntimeError("Only 16-bit WAV analysis is supported.")

    samples = [
        int.from_bytes(raw_frames[index : index + 2], byteorder="little", signed=True)
        for index in range(0, len(raw_frames), 2)
    ]

    window_size = max(1, int(frame_rate * window_seconds))
    rms_values: list[float] = []
    for start in range(0, len(samples), window_size):
        window = samples[start : start + window_size]
        if not window:
            continue
        square_mean = sum(sample * sample for sample in window) / len(window)
        rms_values.append(math.sqrt(square_mean))

    return frame_rate, rms_values


def probe_duration(source: Path, ffmpeg_bin: str) -> float:
    ffprobe = str(Path(ffmpeg_bin).with_name("ffprobe"))
    if not Path(ffprobe).exists():
        return 0.0

    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(source),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return float(result.stdout.strip() or 0.0)


def run_ffmpeg(command: list[str]) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "AV_LOG_FORCE_NOCOLOR": "1"},
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr.strip() or "FFmpeg command failed.") from exc


def pairwise(items: Iterable[float]) -> Iterable[tuple[float, float]]:
    iterator = iter(items)
    previous = next(iterator, None)
    for current in iterator:
        if previous is None:
            previous = current
            continue
        yield previous, current
        previous = current
