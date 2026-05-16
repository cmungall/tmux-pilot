"""tmux-pilot: manage tmux sessions for AI coding agents."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import subprocess


def _version_from_git() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--dirty", "--long", "--match", "v[0-9]*"],
            cwd=repo_root,
            capture_output=True,
            check=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "0.0.0"
    desc = result.stdout.strip()
    if not desc:
        return "0.0.0"
    dirty = desc.endswith("-dirty")
    if dirty:
        desc = desc[: -len("-dirty")]
    if desc.startswith("v"):
        desc = desc[1:]
    parts = desc.rsplit("-", 2)
    if len(parts) == 3 and parts[1].isdigit() and parts[2].startswith("g"):
        base, distance, sha = parts
        if distance == "0":
            normalized = base
        else:
            normalized = f"{base}.post{distance}+{sha}"
    else:
        normalized = desc
    if dirty:
        normalized = f"{normalized}.dirty" if "+" in normalized else f"{normalized}+dirty"
    return normalized

try:
    __version__ = version("tmux-pilot")
except PackageNotFoundError:
    __version__ = _version_from_git()
