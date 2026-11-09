# Contributing to Inspect Ranges

Thanks for your interest in contributing. Bug reports, doc fixes, and core changes are all welcome.

## Development setup

Inspect Ranges uses [uv](https://docs.astral.sh/uv/) 0.13.4 or later for environment and dependency management, and requires Python 3.12+.

```bash
git clone https://github.com/meridianlabs-ai/inspect_ranges
cd inspect_ranges
uv sync --group dev
```

This installs Inspect Ranges in editable mode along with the dev tools (ruff, pyright, pytest), and puts the `inspect-ranges` CLI on your path. `uv sync` uses the exact versions in `uv.lock`. The dev tools are in the `dev` extra. The default `dev` dependency group includes that extra, so `uv sync` and `uv run` install them. `uv sync --extra dev` does the same, and works with `--no-default-groups` too.

### Dependencies and the cooldown

`uv.lock` pins every Python dependency except the build toolchain. CI's lint, type-check, test and build jobs install their dependencies from it, and fail when `uv.lock` is out of date with `pyproject.toml`. CI's build job and the release build use the build toolchain (build, hatchling, hatch-vcs) pinned with hashes in `scripts/build-dist/requirements.txt`. Dependabot updates that file weekly, and `.github/workflows/publish.yaml` gives the command to update it by hand. When uv builds Inspect Ranges, for example for the editable install in `uv sync`, it resolves the build requirements (hatchling, hatch-vcs) without `uv.lock` or hashes, but within the cooldown. When you change dependencies in `pyproject.toml`, run `uv lock` and commit both files.

`pyproject.toml` sets `exclude-newer = "7 days"` under `[tool.uv]`, so `uv lock`, `uv sync` and `uv pip` only pick releases that have been on PyPI for at least seven days. A compromised release is usually found and removed within that time, before it reaches `uv.lock`, CI or your machine. Only a direct dependency (a package in `dependencies` or the `dev` extra in `pyproject.toml`) that is a model provider SDK or an Inspect package can wait 6 hours instead, so Inspect Ranges can adopt a new release the day it ships. Today those are `anthropic`, `inspect-ai` and `inspect-scout`, listed with `"6 hours"` in `[tool.uv.exclude-newer-package]`. Every other package keeps the seven-day cooldown. Dependabot's `uv` entry in `.github/dependabot.yml` repeats the cooldown and the list. When you add a `"6 hours"` entry, also add the package to `cooldown.exclude` and the `six-hour-cooldown` group there. `tests/test_dependency_cooldown.py` checks that each entry is a direct dependency, that dated entries (below) are less than seven days old, and that the two files match. Whether a package is a provider SDK or an Inspect package is up to review.

Dependabot proposes `uv.lock` updates daily, once a release has cleared its cooldown. To adopt a release sooner, run `uv lock --upgrade-package <package>` and commit `uv.lock`. A release still inside its cooldown can't be locked; wait for it rather than overriding `exclude-newer`, unless it's an emergency (below).

In an emergency, for example a security fix, you can adopt a release that is less than seven days old with a one-time dated entry:

1. Under `[tool.uv.exclude-newer-package]` in `pyproject.toml`, add `<package> = "<timestamp>"`. The package must be a direct dependency. Use an RFC 3339 timestamp just after the upload time of the fixed release. Don't add a dated entry to `.github/dependabot.yml`.
2. Run `uv lock --upgrade-package <package>` and commit both files.
3. Within seven days, once the normal cooldown includes the release, delete the entry, run `uv lock --upgrade-package <package>`, and commit both files. A plain `uv lock` doesn't reliably remove the entry from `uv.lock`, and CI then fails. A test fails when a dated entry is seven days old or older.

Testing against the newest release of every dependency happens in the nightly canary in [meridianlabs-ai/canaries](https://github.com/meridianlabs-ai/canaries), so Inspect Ranges's own CI doesn't need to.

### Remote development

Running ranges requires Linux with KVM and nested virtualization, so day-to-day development happens on an EC2 devbox:

```bash
uv run devbox/devbox.py --profile <profile> --region <region> up
```

This provisions the box, clones the repo onto it, and sets up SSH so you can connect with `ssh inspect-ranges-devbox` or VS Code Remote-SSH. The box stops itself when idle. See [`devbox/README.md`](devbox/README.md) for prerequisites, the security model, and the required IAM permissions.

## Checks and tests

Before opening a PR, make sure these pass:

```bash
make check   # pyright + ruff check --fix + ruff format
make test    # pytest
```

To run a single test:

```bash
uv run pytest tests/path/to/test.py::test_name -v
```

## Code style

- Type-annotate all functions (including tests). Use modern syntax (`X | None`, `list[str]`).
- Google-style docstrings for public APIs.
- `ruff` handles formatting and import order; don't fight it.
- Don't catch exceptions defensively — let unexpected errors propagate.

See [`CLAUDE.md`](CLAUDE.md) for the full conventions used in this repo.

## Building the docs

Docs live in `docs/` and are built with [Quarto](https://quarto.org). The Quarto CLI and the doc-build dependencies are in the `doc` group, which a plain `uv sync` leaves out (and removes):

```bash
uv sync --group doc
cd docs
source ../.venv/bin/activate
quarto render        # outputs to docs/_site/
quarto preview       # live-reload server
```

The venv must be activated (not just `uv run quarto`) so the reference-page filter can import `griffe` and the `inspect_ranges` package itself.

## Updating the docs extension

`docs/_extensions/` holds a checked-in copy of the [inspect-docs](https://github.com/meridianlabs-ai/inspect-docs) Quarto extension, which contributes the project type `_quarto.yml` declares. It is committed (per Quarto convention) so that a fresh clone can render without any install step.

To pull a newer version:

```bash
cd docs
mv _quarto.yml _quarto.yml.bak
uv run --group doc quarto update meridianlabs-ai/inspect-docs --no-prompt
mv _quarto.yml.bak _quarto.yml
```

The `mv` is a bootstrap workaround, not superstition: `quarto add`/`update` parses `_quarto.yml` to choose an install directory, so it chokes on the very project type the extension provides. Commit the resulting diff.

## Pull requests

- Branch from `main`; we squash-merge.
- Keep PRs focused on one change.
- Add or update tests for behavior changes.
- Update `CHANGELOG.md` under a new top entry if the change is user-visible.

## Reporting issues

Use the [issue tracker](https://github.com/meridianlabs-ai/inspect_ranges/issues). For bugs, include the `inspect_ranges` and `inspect_ai` versions (`pip show inspect-ranges inspect-ai`) and a minimal repro.
