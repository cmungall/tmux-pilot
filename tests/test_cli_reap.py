"""Tests for the `tp reap` CLI command's preview -> confirm -> reap flow.

These guard against the regression where `tp reap` reaped immediately, before
(and instead of) prompting, and where the dry-run output listed skipped
sessions under a misleading "would reap" header.
"""

from __future__ import annotations

import argparse

from tmux_pilot import cli, reaper


def _ns(**overrides: object) -> argparse.Namespace:
    base = dict(dry_run=False, force=False, include_no_pr=False, include_dead=False)
    base.update(overrides)
    return argparse.Namespace(**base)


_MERGED = {
    "session": "ltv-22", "branch": "fix/issue-22", "pr": 23,
    "reason": "pr-merged", "action": "confirm", "skipped": False,
}
_OPEN = {
    "session": "amr", "branch": "feat/amr", "pr": 1458,
    "reason": "pr-open", "skipped": True,
}


def test_cmd_reap_previews_before_killing_and_aborts(monkeypatch, capsys):
    calls: list[bool] = []

    def fake_reap(*, dry_run, force, include_no_pr, include_dead):
        calls.append(dry_run)
        if dry_run:
            return [dict(_MERGED)]
        raise AssertionError("real reap must not run after the user declines")

    monkeypatch.setattr(reaper, "reap_sessions", fake_reap)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")

    cli.cmd_reap(_ns())

    assert calls == [True]  # only the preview ran; nothing was reaped
    assert "Aborted" in capsys.readouterr().out


def test_cmd_reap_confirm_then_reaps(monkeypatch, capsys):
    calls: list[bool] = []

    def fake_reap(*, dry_run, force, include_no_pr, include_dead):
        calls.append(dry_run)
        if dry_run:
            return [dict(_MERGED)]
        return [{"session": "ltv-22", "killed": True, "worktree_removed": True, "branch_deleted": True}]

    monkeypatch.setattr(reaper, "reap_sessions", fake_reap)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")

    cli.cmd_reap(_ns())

    assert calls == [True, False]  # preview, then the real reap
    assert "Reaped 1 session(s)." in capsys.readouterr().out


def test_cmd_reap_dry_run_separates_reap_from_skip(monkeypatch, capsys):
    def fake_reap(*, dry_run, force, include_no_pr, include_dead):
        return [dict(_MERGED), dict(_OPEN)]

    monkeypatch.setattr(reaper, "reap_sessions", fake_reap)

    cli.cmd_reap(_ns(dry_run=True))

    out = capsys.readouterr().out
    assert "Would reap:" in out
    assert "Would skip:" in out
    # the open PR belongs under "skip", not "reap"
    skip_idx = out.index("Would skip:")
    assert out.index("ltv-22") < skip_idx
    assert out.index("amr") > skip_idx


def test_cmd_reap_force_skips_prompt(monkeypatch, capsys):
    calls: list[bool] = []

    def fake_reap(*, dry_run, force, include_no_pr, include_dead):
        calls.append(dry_run)
        if dry_run:
            return [dict(_MERGED)]
        return [{"session": "ltv-22", "killed": True}]

    def no_input(prompt=""):
        raise AssertionError("--force must not prompt")

    monkeypatch.setattr(reaper, "reap_sessions", fake_reap)
    monkeypatch.setattr("builtins.input", no_input)

    cli.cmd_reap(_ns(force=True))

    assert calls == [True, False]
    assert "Reaped 1 session(s)." in capsys.readouterr().out
