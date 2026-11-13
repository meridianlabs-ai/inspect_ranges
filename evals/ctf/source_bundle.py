"""Bundle the inspect_ranges source for white-box delivery to the attack box.

A white-box breakout copies the runtime source into the sandbox so a capable agent attacks
from knowledge of the defence instead of refusing or guessing. This tars the
inspect_ranges source the exercise defends (the package, the docs, and the top-level
manifests) and hands it to the attack box, where the sample setup unpacks it to
`./inspect-ranges-src/`. Only tracked source goes in; the virtualenv, VCS metadata, caches,
and eval logs are left out.
"""

from __future__ import annotations

import tarfile
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# The runtime source the exercise defends, relative to the repo root. Directories are added
# whole (minus the excluded names below); the manifests give the agent the dependency and
# build picture a white-box source copy carries.
_SOURCE_PATHS = (
    "src",
    "docs",
    "README.md",
    "AGENTS.md",
    "CHANGELOG.md",
    "pyproject.toml",
    "Makefile",
)

_EXCLUDE_NAMES = frozenset(
    {"__pycache__", ".git", ".venv", ".pytest_cache", ".ruff_cache", "_version.py"}
)


def _keep(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    name = Path(info.name).name
    if name in _EXCLUDE_NAMES or name.endswith((".pyc", ".pyo")):
        return None
    return info


def source_tarball(dest: Path | None = None) -> Path:
    """Build the white-box source tarball and return its path.

    Args:
        dest: Where to write the archive; a stable temp path is used when omitted, so repeated task construction reuses one file.
    """
    target = dest or Path(tempfile.gettempdir()) / "inspect-ranges-ctf-src.tgz"
    with tarfile.open(target, "w:gz") as archive:
        for relative in _SOURCE_PATHS:
            source = _REPO_ROOT / relative
            if source.exists():
                archive.add(source, arcname=relative, filter=_keep)
    return target
