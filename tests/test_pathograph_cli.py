"""CLI tests for the optional pathograph conversion utility."""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from tmux_pilot.pathograph_cli import main


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pathograph"


def test_convert_html_to_cx2_file(capsys: pytest.CaptureFixture[str], tmp_path: Path):
    output_path = tmp_path / "sample.cx2"

    main(
        [
            "convert",
            str(FIXTURE_DIR / "sample_pathograph.html"),
            "--input-format",
            "html",
            "--name",
            "Rendered Sample",
            "--output",
            str(output_path),
        ]
    )

    assert output_path.exists()
    parsed = json.loads(output_path.read_text(encoding="utf-8"))
    assert isinstance(parsed, list)
    assert capsys.readouterr().out == ""


def test_convert_json_to_stdout(capsys: pytest.CaptureFixture[str]):
    main(
        [
            "convert",
            str(FIXTURE_DIR / "sample_pathograph.json"),
            "--name",
            "Fixture Sample",
        ]
    )

    stdout = capsys.readouterr().out
    parsed = json.loads(stdout)
    assert isinstance(parsed, list)
    assert any("nodes" in aspect for aspect in parsed)
