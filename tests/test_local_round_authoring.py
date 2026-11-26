import json
import wave
from pathlib import Path

from scripts.render_local_round import render_local_round


def _tone(path: Path, seconds: float) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(44_100)
        handle.writeframes(b"\0\0" * int(44_100 * seconds))


def test_local_round_has_exact_cues_and_gaps(tmp_path):
    first, second = tmp_path / "one.wav", tmp_path / "two.wav"
    _tone(first, 1)
    _tone(second, 31)
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"cues": [{"path": str(first)}, {"path": str(second)}]}))
    result = render_local_round(source, tmp_path / "round.mp3")
    assert result["durationSeconds"] == 65.0
    assert [cue["startSeconds"] for cue in result["cues"]] == [0.0, 35.0]
    assert [cue["endSeconds"] for cue in result["cues"]] == [30.0, 65.0]
