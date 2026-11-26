#!/usr/bin/env python3
"""Master a round from already-authorized local audio files.

This path never resolves, downloads, or contacts a music provider. Each input
cue is rendered to exactly 30 seconds and cues are separated by five seconds
of silence, except after the final cue.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pydub import AudioSegment

CUE_MS = 30_000
GAP_MS = 5_000


def render_local_round(input_manifest: Path, output: Path, manifest_output: Path | None = None) -> dict:
    payload = json.loads(input_manifest.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("input manifest must be a JSON object")
    cues = payload.get("cues")
    if not isinstance(cues, list) or not cues:
        raise ValueError("input manifest must contain a non-empty cues array")
    master = AudioSegment.empty()
    rendered = []
    for index, cue in enumerate(cues, 1):
        if not isinstance(cue, dict) or not isinstance(cue.get("path"), str) or not cue["path"]:
            raise ValueError(f"cue {index} must contain a non-empty string path")
        source = Path(cue["path"])
        if not source.is_file():
            raise FileNotFoundError(source)
        audio = AudioSegment.from_file(source)
        audio = audio.set_channels(1).set_frame_rate(44_100)
        if len(audio) >= CUE_MS:
            audio = audio[:CUE_MS]
        else:
            audio += AudioSegment.silent(duration=CUE_MS - len(audio), frame_rate=44_100)
        start = index - 1
        start_ms = start * (CUE_MS + GAP_MS)
        master += audio
        if index != len(cues):
            master += AudioSegment.silent(duration=GAP_MS, frame_rate=44_100)
        rendered.append({
            "position": index,
            "startSeconds": start_ms / 1000,
            "endSeconds": (start_ms + CUE_MS) / 1000,
            "source": str(source),
            "label": cue.get("label"),
        })
    output.parent.mkdir(parents=True, exist_ok=True)
    master.export(output, format="mp3", bitrate="128k", parameters=["-ar", "44100"])
    result = {
        "format": "mp3",
        "durationSeconds": len(master) / 1000,
        "cueDurationSeconds": CUE_MS / 1000,
        "gapSeconds": GAP_MS / 1000,
        "cues": rendered,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "renderer": "QuizzicalBeats local-file authoring CLI",
    }
    if manifest_output:
        manifest_output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--manifest-output", type=Path)
    args = parser.parse_args()
    print(json.dumps(render_local_round(args.input_manifest, args.output, args.manifest_output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
