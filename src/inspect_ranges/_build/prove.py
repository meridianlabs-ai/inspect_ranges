"""`inspect-ranges prove`: re-run a built range's conformance proofs post hoc through the build's own proof boot, and stamp the manifest.

The build already runs every declared proof fail-closed (a failure lands a REFUSED manifest; nothing unproven is consumable). The standalone runner exists for the other direction of trust: a consumer of a built or pulled artifact re-demonstrates scoring against the exact realized images the manifest names, through the exact seam the build used (`run_proof_boot`), and records the demonstration in the manifest's `proven` slot. The stamp is additive and fail-open by design: a failed standalone proof changes nothing on disk (the error names what contradicted what), it never touches `verification.behavioral_checks`, and a REFUSED manifest refuses standalone proving outright (rebuild first: the build is where refusals are earned and cleared).
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .._compiler.plan import plan_totals, spec_sha256
from .._provider.naming import CidAllocator
from .._runtime.images import default_image_cache
from .._runtime.ownership import PROJECT_PREFIX, StageLog, default_state_dir
from .._runtime.up import OnStage
from ..schema import load_range
from .behavioral import (
    checks_digest,
    load_challenges,
    proofs_declared,
    validate_conformance,
)
from .manifest import (
    BuildManifest,
    GoalAssertion,
    ProvenRecord,
    default_build_cache,
    load_manifest,
    manifest_matches_spec,
    stamp_proven,
)
from .orchestrate import (
    _BuildTee,  # pyright: ignore[reportPrivateUsage]
    run_proof_boot,
)


def run_prove(
    range_dir: Path,
    *,
    image_cache: Path | None = None,
    build_cache: Path | None = None,
    state_dir: Path | None = None,
    uplink_network: str | None = None,
    readiness_timeout: float = 300.0,
    keep: bool = False,
    on_stage: OnStage | None = None,
) -> ProvenRecord:
    """Boot the recorded build once (the `-bx` proof boot), run every declared conformance proof against it, and stamp the manifest `proven` when all pass.

    The runner is sync and owns no event loop (`run_proof_boot`'s spans manage their own); the boot leases its own CID block (`origin="cli"`), the manifest comes from disk and must match this directory's spec revision, proof tree, and carry no failing records.

    Raises:
        ConformanceError: No proofs or manifest, a spec/proof-tree revision mismatch, a REFUSED manifest, a failing proof (the manifest is left unmarked), or a CID block still held by a previous prove.
        BuildError: The retired `checks/` layout, a malformed conformance tree, or an infra failure inside the proof boot.
        UpError: The proof boot failed; with `keep` the failed range stays up and the message names the down command.
    """
    from .._challenges.prove import ConformanceError
    from .._runtime.down import down
    from .._runtime.up import up

    image_cache = (image_cache or default_image_cache()).resolve()
    build_cache = build_cache or default_build_cache()
    state_dir = state_dir or default_state_dir()

    if not proofs_declared(range_dir):
        raise ConformanceError(
            f"{range_dir} declares no conformance proofs (conformance/ with "
            "challenges.yaml)"
        )
    spec = load_range(range_dir / "range.yaml")
    spec_hash = spec_sha256(spec)
    manifest = load_manifest(build_cache, spec.meta.name)
    if manifest is None:
        raise ConformanceError(
            f"no build manifest for {spec.meta.name!r}; build (or pull) the "
            "range before proving it"
        )
    _refuse_unprovable(manifest, spec_hash, range_dir)
    # tree validation runs AFTER the manifest gates: it imports the range's
    # loose task.py (arbitrary code, needed to register goal types for the
    # scripts' assertions), and a cheap manifest refusal must come first
    validate_conformance(load_challenges(range_dir), range_dir)

    project = f"{PROJECT_PREFIX}{spec.meta.name}-{spec_hash[:12]}-prove"
    # the lease keys the exact project the seam boots (`<project>-bx`)
    bx_project = f"{project}-bx"
    allocator = CidAllocator(state_dir)
    try:
        lease = allocator.lease(bx_project, plan_totals(spec).guests, origin="cli")
    except ValueError as error:
        raise ConformanceError(
            f"{error}; a previous prove of this range likely still holds it: "
            f"inspect-ranges down {bx_project} releases the block"
        ) from error

    # the seam's teardown keeps project state (the evidence record is the
    # proof's audit trail), and `down` releases a lease on FULL teardown only,
    # so this runner must release its own block; a teardown failure logged by
    # the seam means the range may still be up, and a block must never free
    # under live VMs, so the watch holds the lease in that case (the stage
    # log carries the retry hint, and the operator's full `down` releases)
    teardown_failed = False

    def watch(stage: str, status: str, fields: dict[str, Any]) -> None:
        nonlocal teardown_failed
        if stage == "teardown" and status == "fail":
            teardown_failed = True
        if on_stage is not None:
            on_stage(stage, status, fields)

    tee = _BuildTee(StageLog(state_dir, project), watch)
    assertions: list[GoalAssertion] = []
    try:
        records = run_proof_boot(
            spec,
            range_dir,
            manifest=manifest,
            image_cache=image_cache,
            state_dir=state_dir,
            project=project,
            stage_log=tee,
            up_fn=up,
            down_fn=down,
            cid_base=lease.base,
            readiness_timeout=readiness_timeout,
            uplink_network=uplink_network,
            keep_on_failure=keep,
            assertion_sink=assertions,
        )
    except BaseException:
        # pre-up and settle failures: with keep the seam left the failed boot
        # up (its lease must survive until the operator's down); otherwise the
        # seam's teardown ran, unless it FAILED (never free a block under a
        # possibly-live range)
        if not keep and not teardown_failed:
            allocator.release(bx_project)
        raise
    failed = [record for record in records if record.status != "pass"]
    kept_range = keep and bool(failed)
    if not teardown_failed and not kept_range:
        allocator.release(bx_project)
    if failed:
        verdict = failed[0]
        hint = (
            f"; the failed proof boot is kept: inspect-ranges down {bx_project}"
            if kept_range
            else ""
        )
        raise ConformanceError(
            f"challenge {verdict.challenge!r} check {verdict.check!r} failed: "
            f"{verdict.detail} (the manifest is left unmarked; the build is "
            f"where refusals are earned{hint})"
        )
    record = ProvenRecord(
        proven_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        scripts=[f"{item.challenge}/{item.check}" for item in records],
        assertions=assertions,
    )
    stamp_proven(
        build_cache, spec.meta.name, spec_hash, record, built_at=manifest.built_at
    )
    return record


def _refuse_unprovable(
    manifest: BuildManifest, spec_hash: str, range_dir: Path
) -> None:
    """The standalone gate: the stamp must describe exactly the recorded build, so a revision drift or a recorded refusal refuses before any boot.

    Raises:
        ConformanceError: Spec revision drift, a recorded refusal, or a conformance tree the recorded build did not prove (including a build that predates the tree, whose recorded digest is empty).
    """
    from .._challenges.prove import ConformanceError

    if not manifest_matches_spec(manifest, spec_hash):
        raise ConformanceError(
            "the recorded build is a different spec revision than this range "
            "directory; rebuild before proving"
        )
    failing = [
        record
        for record in manifest.verification.behavioral_checks
        if record.status != "pass"
    ]
    if failing:
        raise ConformanceError(
            f"the recorded build is REFUSED (challenge "
            f"{failing[0].challenge!r} check {failing[0].check!r}: "
            f"{failing[0].detail}); fix the range and rebuild before proving"
        )
    if manifest.checks_sha256 != checks_digest(range_dir):
        raise ConformanceError(
            "the conformance tree is not the one the recorded build proved "
            "(checks_sha256 mismatch; an empty recorded digest means the "
            "build predates the tree); rebuild to re-prove"
        )
