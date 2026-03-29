"""Tests for git hook installation helpers."""

from __future__ import annotations

from tmux_pilot import hooks


def test_install_hooks_chains_existing_hook(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "_get_hooks_path_config", lambda: "/tmp/original-hooks")
    configured_paths: list[str] = []
    monkeypatch.setattr(hooks, "_set_hooks_path_config", configured_paths.append)

    existing = tmp_path / "post-commit"
    existing.write_text("#!/bin/sh\necho legacy\n")

    result = hooks.install_hooks(tmp_path)

    assert result["hooks_dir"] == str(tmp_path)
    assert sorted(result["hooks_installed"]) == sorted(hooks.HOOKS)
    assert configured_paths == [str(tmp_path)]
    assert (tmp_path / "post-commit.pre-tp").read_text() == "#!/bin/sh\necho legacy\n"
    assert hooks._MARKER in (tmp_path / "post-commit").read_text()
    assert (tmp_path / hooks._SAVED_PATH_FILE).read_text() == "/tmp/original-hooks"


def test_uninstall_hooks_restores_previous_hook_and_path(tmp_path, monkeypatch):
    restored_paths: list[str] = []
    unset_calls: list[bool] = []
    monkeypatch.setattr(hooks, "_set_hooks_path_config", restored_paths.append)
    monkeypatch.setattr(hooks, "_unset_hooks_path_config", lambda: unset_calls.append(True))

    for name, content in hooks.HOOKS.items():
        path = tmp_path / name
        path.write_text(content)
        path.chmod(0o755)

    restored_hook = tmp_path / "post-commit.pre-tp"
    restored_hook.write_text("#!/bin/sh\necho restored\n")
    (tmp_path / hooks._SAVED_PATH_FILE).write_text("/tmp/original-hooks")

    result = hooks.uninstall_hooks(tmp_path)

    assert sorted(result["hooks_removed"]) == sorted(hooks.HOOKS)
    assert result["restored_hooks_path"] == "/tmp/original-hooks"
    assert restored_paths == ["/tmp/original-hooks"]
    assert unset_calls == []
    assert (tmp_path / "post-commit").read_text() == "#!/bin/sh\necho restored\n"


def test_uninstall_hooks_unsets_when_no_saved_path(tmp_path, monkeypatch):
    unset_calls: list[bool] = []
    monkeypatch.setattr(hooks, "_unset_hooks_path_config", lambda: unset_calls.append(True))

    hook_path = tmp_path / "pre-push"
    hook_path.write_text(hooks.HOOKS["pre-push"])

    result = hooks.uninstall_hooks(tmp_path)

    assert result["hooks_removed"] == ["pre-push"]
    assert result["restored_hooks_path"] == ""
    assert unset_calls == [True]
