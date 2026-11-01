"""The standalone prove runner: manifest gating, the seam handoff, lease hygiene, and the revision-locked additive stamp, all against fakes (no VMs)."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from inspect_ranges._build.manifest import (
    BehavioralCheckRecord,
    BuildManifest,
    GoalAssertion,
    ProvenRecord,
    VerificationRecord,
    load_manifest,
    save_manifest,
    stamp_proven,
)
from inspect_ranges._challenges.prove import ConformanceError
from inspect_ranges._provider.naming import CidAllocator


def _manifest(
    spec_sha: str,
    *,
    checks_sha: str = "",
    behavioral: tuple[BehavioralCheckRecord, ...] = (),
) -> BuildManifest:
    return BuildManifest(
        range_name="proof-range",
        schema_version="0.1",
        spec_sha256=spec_sha,
        built_at="2026-11-01T00:00:00+00:00",
        checks_sha256=checks_sha,
        guests=(),
        verification=VerificationRecord(
            verified_at="2026-11-01T00:00:00+00:00",
            declarations=(),
            behavioral_checks=behavioral,
        ),
    )


def _range_dir(tmp_path: Path) -> Path:
    range_dir = tmp_path / "range"
    (range_dir / "conformance" / "demo").mkdir(parents=True)
    (range_dir / "conformance" / "demo" / "prove_flow.py").write_text(
        "async def prove(ctx):\n    pass\n"
    )
    (range_dir / "challenges.yaml").write_text("placeholder: unused\n")
    (range_dir / "range.yaml").write_text("placeholder: unused\n")
    return range_dir


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    spec_sha: str = "a" * 64,
    manifest: BuildManifest | None = None,
    digest: str = "",
) -> dict[str, Any]:
    """Fake the runner's collaborators (spec load, challenge load/validation, manifest load, digest, stamp); the seam itself is wired per test."""
    import inspect_ranges._build.prove as prove_module

    seen: dict[str, Any] = {}

    def fake_load_range(path: Path) -> Any:
        return SimpleNamespace(meta=SimpleNamespace(name="proof-range"))

    def fake_sha(spec: Any) -> str:
        return spec_sha

    def fake_load_challenges(range_dir: Path) -> Any:
        return SimpleNamespace(challenges=[])

    def fake_validate(challenges: Any, range_dir: Path) -> None:
        seen["validated"] = True

    def fake_load_manifest(build_cache: Path, name: str) -> BuildManifest | None:
        return manifest

    def fake_digest(range_dir: Path) -> str:
        return digest

    def fake_totals(spec: Any) -> Any:
        return SimpleNamespace(guests=2)

    def fake_stamp(
        build_cache: Path, name: str, sha: str, record: ProvenRecord, *, built_at: str
    ) -> None:
        seen["stamped"] = (sha, record, built_at)

    monkeypatch.setattr(prove_module, "load_range", fake_load_range)
    monkeypatch.setattr(prove_module, "spec_sha256", fake_sha)
    monkeypatch.setattr(prove_module, "load_challenges", fake_load_challenges)
    monkeypatch.setattr(prove_module, "validate_conformance", fake_validate)
    monkeypatch.setattr(prove_module, "load_manifest", fake_load_manifest)
    monkeypatch.setattr(prove_module, "checks_digest", fake_digest)
    monkeypatch.setattr(prove_module, "plan_totals", fake_totals)
    monkeypatch.setattr(prove_module, "stamp_proven", fake_stamp)
    return seen


def test_run_prove_boots_through_the_seam_and_stamps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The happy path: the seam runs from a sync context (the fake calls asyncio.run itself, as the real seam does, so a runner holding an ambient loop dies here), the CLI lease's base feeds the boot, and the stamp lands keyed to the booted revision with the sink's assertions."""
    import inspect_ranges._build.prove as prove_module
    from inspect_ranges._build.prove import run_prove

    sha = "a" * 64
    seen = _wire(monkeypatch, spec_sha=sha, manifest=_manifest(sha))
    state = tmp_path / "state"
    state.mkdir()

    def fake_seam(spec: Any, range_dir: Path, **kwargs: Any) -> Any:
        async def inner() -> None:
            pass

        asyncio.run(inner())  # the real seam manages its own loops
        seen["cid_base"] = kwargs["cid_base"]
        seen["keep"] = kwargs["keep_on_failure"]
        kwargs["assertion_sink"].append(
            GoalAssertion(goal_id="token", expected_achieved=True)
        )
        return (
            BehavioralCheckRecord(
                challenge="demo", check="reference", status="pass", detail=""
            ),
            BehavioralCheckRecord(
                challenge="demo", check="prove_flow.py", status="pass", detail=""
            ),
        )

    monkeypatch.setattr(prove_module, "run_proof_boot", fake_seam)
    record = run_prove(_range_dir(tmp_path), state_dir=state)
    assert seen["validated"] and seen["keep"] is False
    stamped_sha, stamped, stamped_built_at = seen["stamped"]
    assert stamped_sha == sha and stamped is record
    assert stamped_built_at == "2026-11-01T00:00:00+00:00"  # the loaded build's
    assert record.scripts == ["demo/reference", "demo/prove_flow.py"]
    assert [a.goal_id for a in record.assertions] == ["token"]
    # the seam's keep_state teardown never releases leases (down releases on
    # FULL teardown only), so the runner releases its own block on success
    assert CidAllocator(state).leased_projects() == []
    assert seen["cid_base"] >= 3


def test_run_prove_holds_the_lease_when_teardown_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A seam-logged teardown failure means the range may still be up: the block must never free under live VMs, so the runner retains the lease (the operator's full down releases it); the stamp still lands, since the proof itself passed."""
    import inspect_ranges._build.prove as prove_module
    from inspect_ranges._build.prove import run_prove

    sha = "a" * 64
    seen = _wire(monkeypatch, spec_sha=sha, manifest=_manifest(sha))
    state = tmp_path / "state"
    state.mkdir()

    def seam_with_failed_teardown(spec: Any, range_dir: Path, **kwargs: Any) -> Any:
        kwargs["stage_log"].log(
            "teardown", "fail", error="synthetic", project="ir-x-bx"
        )
        return (
            BehavioralCheckRecord(
                challenge="demo", check="reference", status="pass", detail=""
            ),
        )

    monkeypatch.setattr(prove_module, "run_proof_boot", seam_with_failed_teardown)
    run_prove(_range_dir(tmp_path), state_dir=state)
    assert "stamped" in seen
    lease_project = f"ir-proof-range-{'a' * 12}-prove-bx"
    assert CidAllocator(state).leased_projects() == [lease_project]
    CidAllocator(state).release(lease_project)


def test_run_prove_failure_shapes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failing record raises without stamping, an un-kept seam exception releases the lease, a kept one retains it, and a held block refuses with the down hint."""
    import inspect_ranges._build.prove as prove_module
    from inspect_ranges._build.prove import run_prove

    sha = "a" * 64
    seen = _wire(monkeypatch, spec_sha=sha, manifest=_manifest(sha))
    state = tmp_path / "state"
    state.mkdir()
    range_dir = _range_dir(tmp_path)
    lease_project = f"ir-proof-range-{'a' * 12}-prove-bx"
    allocator = CidAllocator(state)

    def failing_seam(spec: Any, range_dir: Path, **kwargs: Any) -> Any:
        return (
            BehavioralCheckRecord(
                challenge="demo", check="prove_flow.py", status="fail", detail="nope"
            ),
        )

    monkeypatch.setattr(prove_module, "run_proof_boot", failing_seam)
    with pytest.raises(ConformanceError, match="left unmarked"):
        run_prove(range_dir, state_dir=state)
    assert "stamped" not in seen
    # an un-kept failing verdict released its lease (the seam tore down)
    assert allocator.leased_projects() == []
    # a KEPT failing verdict retains it (the seam left the boot up) and the
    # error names the down command
    with pytest.raises(ConformanceError, match=f"down {lease_project}"):
        run_prove(range_dir, state_dir=state, keep=True)
    assert allocator.leased_projects() == [lease_project]
    allocator.release(lease_project)

    def raising_seam(spec: Any, range_dir: Path, **kwargs: Any) -> Any:
        raise RuntimeError("boot exploded")

    monkeypatch.setattr(prove_module, "run_proof_boot", raising_seam)
    with pytest.raises(RuntimeError, match="boot exploded"):
        run_prove(range_dir, state_dir=state)
    assert allocator.leased_projects() == []  # un-kept failure released it
    with pytest.raises(RuntimeError, match="boot exploded"):
        run_prove(range_dir, state_dir=state, keep=True)
    assert allocator.leased_projects() == [lease_project]  # kept boot keeps it
    with pytest.raises(ConformanceError, match="releases the block"):
        run_prove(range_dir, state_dir=state)  # the held block refuses
    allocator.release(lease_project)


def test_run_prove_gates_on_the_recorded_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Standalone proving refuses before any boot when there is no manifest, the spec revision drifted, the recorded build is REFUSED, or the proof tree changed since the build proved it."""
    import inspect_ranges._build.prove as prove_module
    from inspect_ranges._build.prove import run_prove

    sha = "a" * 64
    state = tmp_path / "state"
    state.mkdir()
    range_dir = _range_dir(tmp_path)

    def seam_must_not_run(spec: Any, range_dir: Path, **kwargs: Any) -> Any:
        raise AssertionError("the gate must refuse before any boot")

    monkeypatch.setattr(prove_module, "run_proof_boot", seam_must_not_run)

    _wire(monkeypatch, spec_sha=sha, manifest=None)
    monkeypatch.setattr(prove_module, "run_proof_boot", seam_must_not_run)
    with pytest.raises(ConformanceError, match="no build manifest"):
        run_prove(range_dir, state_dir=state)

    _wire(monkeypatch, spec_sha=sha, manifest=_manifest("b" * 64))
    monkeypatch.setattr(prove_module, "run_proof_boot", seam_must_not_run)
    with pytest.raises(ConformanceError, match="different spec revision"):
        run_prove(range_dir, state_dir=state)

    refused = _manifest(
        sha,
        behavioral=(
            BehavioralCheckRecord(
                challenge="demo", check="forged", status="fail", detail="scored 1.0"
            ),
        ),
    )
    _wire(monkeypatch, spec_sha=sha, manifest=refused)
    monkeypatch.setattr(prove_module, "run_proof_boot", seam_must_not_run)
    with pytest.raises(ConformanceError, match="REFUSED"):
        run_prove(range_dir, state_dir=state)

    _wire(
        monkeypatch,
        spec_sha=sha,
        manifest=_manifest(sha, checks_sha="c" * 64),
        digest="d" * 64,
    )
    monkeypatch.setattr(prove_module, "run_proof_boot", seam_must_not_run)
    with pytest.raises(ConformanceError, match="checks_sha256 mismatch"):
        run_prove(range_dir, state_dir=state)

    (tmp_path / "bare").mkdir()
    with pytest.raises(ConformanceError, match="declares no conformance proofs"):
        run_prove(tmp_path / "bare", state_dir=state)
    assert CidAllocator(state).leased_projects() == []  # no gate leaks a lease


def test_stamp_proven_is_revision_locked_and_additive(tmp_path: Path) -> None:
    """The stamp lands only on the exact spec revision the proofs booted, under the manifest lock, and alters nothing but the `proven` slot; a drifted or absent manifest refuses loudly."""
    build_cache = tmp_path / "builds"
    behavioral = (
        BehavioralCheckRecord(
            challenge="demo", check="reference", status="pass", detail="value=1.00"
        ),
    )
    manifest = _manifest("a" * 64, checks_sha="c" * 64, behavioral=behavioral)
    save_manifest(manifest, build_cache)
    record = ProvenRecord(
        proven_at="2026-11-01T01:00:00+00:00",
        scripts=["demo/prove_flow.py"],
        assertions=[GoalAssertion(goal_id="token", expected_achieved=True)],
    )
    built_at = manifest.built_at
    with pytest.raises(RuntimeError, match="different spec revision"):
        stamp_proven(build_cache, "proof-range", "b" * 64, record, built_at=built_at)
    # a concurrent SAME-SPEC rebuild (new built_at) must not inherit the stamp
    with pytest.raises(RuntimeError, match="different build of the same revision"):
        stamp_proven(
            build_cache, "proof-range", "a" * 64, record, built_at="2026-11-01T02:00:00+00:00"
        )
    stamp_proven(build_cache, "proof-range", "a" * 64, record, built_at=built_at)
    reloaded = load_manifest(build_cache, "proof-range")
    assert reloaded is not None and reloaded.proven is not None
    assert reloaded.proven.scripts == ["demo/prove_flow.py"]
    assert reloaded.verification.behavioral_checks == behavioral  # untouched
    assert reloaded.checks_sha256 == "c" * 64
    with pytest.raises(RuntimeError, match="absent"):
        stamp_proven(build_cache, "other-range", "a" * 64, record, built_at=built_at)
    # a concurrent refused re-proof of the same build must never read proven
    refused = _manifest(
        "a" * 64,
        behavioral=(
            BehavioralCheckRecord(
                challenge="demo", check="forged", status="fail", detail="scored 1.0"
            ),
        ),
    )
    save_manifest(refused, build_cache)
    with pytest.raises(RuntimeError, match="REFUSED"):
        stamp_proven(build_cache, "proof-range", "a" * 64, record, built_at=built_at)
