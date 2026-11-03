"""The hardened range container image: built from package data, hard-required by `up`.

Per the realizer-v1 Decisions, `up` always runs the hardened profile (non-root QEMU, mount namespaces off, docker-default AppArmor/seccomp, the render-emitted capability floor) with no bypass flag; prototype images remain spike-harness material only.
"""

import hashlib
import json
import logging
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from .. import __version__

RANGE_IMAGE_TAG = f"inspect-ranges-range:v{__version__}"
"""The tag `up` builds and pins into the compose environment."""

RANGE_IMAGE_ENV = "INSPECT_RANGES_RANGE_IMAGE"
"""A digest-pinned published range image (`repo@sha256:<hex>`, the catalog's conventional Docker repo): set, `up` pulls and uses it instead of building locally (standard-images-v1 slice 3). The pin is mandatory: a mutable tag could swap the hardened jail under a fleet, so unpinned values refuse. The local build remains the default and the dev loop."""

# docker's reference grammar allows uppercase in the registry host, never in the
# repository path; a tag+digest form (repo:tag@sha256:) is refused outright rather
# than silently dropping the tag the way docker would
_PINNED_REF = re.compile(
    r"\A(?:[A-Za-z0-9][A-Za-z0-9.-]*(?::[0-9]+)?/)?[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}\Z"
)


class RangeImageError(RuntimeError):
    """A pinned range image could not be used; the message names the pin and the cause."""


def pinned_range_image() -> str | None:
    """The validated `INSPECT_RANGES_RANGE_IMAGE` pin, or `None` when the knob is unset.

    Raises:
        RangeImageError: The knob is set but not digest-pinned.
    """
    pinned = os.environ.get(RANGE_IMAGE_ENV)
    if not pinned:
        return None
    if _PINNED_REF.fullmatch(pinned) is None:
        raise RangeImageError(
            f"{RANGE_IMAGE_ENV} must be digest-pinned (repo@sha256:<hex>); "
            f"got {pinned!r}: a mutable tag could swap the hardened jail"
        )
    return pinned


DockerRunner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]
"""Executes a docker command, capturing text output; injectable for tests."""


def range_image_context() -> Path:
    """The in-package docker build context (Dockerfile plus entrypoint)."""
    return Path(__file__).parent / "range_image"


CONTENT_LABEL = "inspect-ranges.range-image-content"

logger = logging.getLogger("inspect_ranges.rangeimage")

RANGE_IMAGE_CONVENTION_NAME = "range"
"""The name the range container image takes inside a registry location when a fleet drafts it off `INSPECT_RANGES_REGISTRY` instead of pinning, spelled by the location's own rules: a tag in a single-repository location (`<repo>:<prefix>--range--v<version>`), the name-prefixed repository on the hub form (`<org>/<name-prefix>-range`, exactly the public catalog's published name), a plain `<prefix>/range` elsewhere; always at the engine-version tag."""


def conventional_range_image(runner: DockerRunner) -> str | None:
    """The registry-drafted range image, resolved to a digest, or `None`.

    Drafting happens only when `INSPECT_RANGES_REGISTRY` is explicitly set (the default public-org search path never drafts: a pin-less dev host keeps building locally), and only off the FIRST configured location. The version-coupled convention tag is a lookup, never what runs: it resolves to a digest here, so the no-mutable-tag posture holds end to end; a fleet that wants one digest across engine upgrades keeps setting `INSPECT_RANGES_RANGE_IMAGE`, which always wins. A missing or unpullable convention ref logs the attempt and yields the local build, exactly today's default.
    """
    from .._dist.errors import DistError
    from .._dist.location import REGISTRY_ENV, parse_location

    raw = os.environ.get(REGISTRY_ENV)
    if raw is None or not raw.strip():
        return None
    first = raw.split(",")[0].strip()
    try:
        location = parse_location(first)
    except DistError as error:
        logger.warning("range image drafting skipped: %s", error)
        return None
    if location.is_directory:
        return None
    base, prefix = location.registry_base_and_prefix()
    host = base.split("://", 1)[1]
    version_tag = f"v{__version__}"
    if location.tag_prefix:
        repo = f"{host}/{prefix}" if prefix else host
        ref = f"{repo}:{location.tag_prefix}--{RANGE_IMAGE_CONVENTION_NAME}--{version_tag}"
    else:
        spelled = (
            f"{location.name_prefix}-{RANGE_IMAGE_CONVENTION_NAME}"
            if location.name_prefix
            else RANGE_IMAGE_CONVENTION_NAME
        )
        repo = f"{prefix}/{spelled}" if prefix else spelled
        ref = f"{host}/{repo}:{version_tag}"
    pull = runner(["docker", "pull", ref])
    if pull.returncode != 0:
        logger.info(
            "no registry range image at %s (%s); building locally "
            "(publish the convention ref there, or set %s)",
            ref,
            pull.stderr.strip()[-120:],
            RANGE_IMAGE_ENV,
        )
        return None
    inspect = runner(
        ["docker", "image", "inspect", ref, "--format", "{{json .RepoDigests}}"]
    )
    if inspect.returncode != 0:
        logger.warning("range image %s pulled but uninspectable; building locally", ref)
        return None
    repo_only = ref.rsplit(":", 1)[0]
    digests = [
        d for d in json.loads(inspect.stdout) if d.startswith(f"{repo_only}@sha256:")
    ]
    if not digests:
        logger.warning(
            "range image %s carries no digest for its own repository; building locally",
            ref,
        )
        return None
    logger.info("range image drafted off the registry: %s -> %s", ref, digests[0])
    return digests[0]


def _content_hash() -> str:
    """Hash of the package version and the build context, so a stale or substituted image rebuilds."""
    hasher = hashlib.sha256(__version__.encode())
    for name in ("Dockerfile", "entrypoint.sh"):
        hasher.update((range_image_context() / name).read_bytes())
    return hasher.hexdigest()


def ensure_range_image(
    runner: DockerRunner | None = None, tag: str = RANGE_IMAGE_TAG
) -> str:
    """Resolve the hardened range image: the `INSPECT_RANGES_RANGE_IMAGE` pin (pulled once) when set; else, with `INSPECT_RANGES_REGISTRY` explicitly configured, the registry's convention ref resolved to a digest (`conventional_range_image`); else the local content-labeled tag, built unless this host has one whose label matches.

    Tag presence alone is not trusted: the image must carry the content label for the current package version and build context, so `docker tag` substitution or an edited Dockerfile within one version both trigger a rebuild.

    With `INSPECT_RANGES_RANGE_IMAGE` set to a digest-pinned published image, the pin is pulled (once) and used verbatim: the digest is the content key, so the local content-label discipline does not apply to it.

    Raises:
        RangeImageError: The env pin is not digest-pinned, or its pull failed.
        subprocess.CalledProcessError: The docker build failed (stderr attached).
        FileNotFoundError: docker is not on this host.
    """
    run = runner or run_docker
    pinned = pinned_range_image()
    if pinned:
        inspect = run(["docker", "image", "inspect", pinned, "--format", "ok"])
        if inspect.returncode != 0:
            pull = run(["docker", "pull", pinned])
            if pull.returncode != 0:
                raise RangeImageError(
                    f"pulling the pinned range image {pinned!r} failed: "
                    f"{pull.stderr.strip()[-300:]}"
                )
        return pinned
    conventional = conventional_range_image(run)
    if conventional:
        return conventional
    content = _content_hash()
    inspect = run(
        [
            "docker",
            "image",
            "inspect",
            tag,
            "--format",
            f'{{{{index .Config.Labels "{CONTENT_LABEL}"}}}}',
        ]
    )
    if inspect.returncode == 0 and inspect.stdout.strip() == content:
        return tag
    build = run(
        [
            "docker",
            "build",
            "-q",
            "-t",
            tag,
            "--label",
            f"{CONTENT_LABEL}={content}",
            str(range_image_context()),
        ]
    )
    if build.returncode != 0:
        raise subprocess.CalledProcessError(
            build.returncode, build.args, build.stdout, build.stderr
        )
    return tag


def run_docker(argv: list[str]) -> "subprocess.CompletedProcess[str]":
    """The default runner: `subprocess.run` with captured text output, no check."""
    return subprocess.run(argv, capture_output=True, text=True)
