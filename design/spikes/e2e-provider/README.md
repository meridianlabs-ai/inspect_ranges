# Spike: end-to-end Inspect sandbox provider

*Validates the full chain with scoped functionality: `inspect eval` → a spike `SandboxEnvironment` provider → **the real schema v0.1** (`inspect_ranges.schema.load_range`) → compiled range → booted VMs → the vsock exec/file plane — then runs Inspect's `self_check` conformance suite against it to generate the daemon punch list empirically. Run on the m6i.metal devbox, 2026-10-01.*

*Reproduce: `uv run inspect eval design/spikes/e2e-provider/task.py --model mockllm/model` (self-contained: boots and tears down its own range) and `uv run python design/spikes/e2e-provider/run_self_check.py`.*

## Verdict

**The system works end to end.** A real `inspect eval` compiles a schema-validated spec, boots a two-VM range, drives exec/network/file operations over vsock through the standard `sandbox()` API — including named sandboxes (`sandbox("web")`) — scores, and tears down cleanly in **~15 s total**. Inspect's conformance suite passes **41 of 44** checks against the prototype daemon; all three failures are one finding (below).

## What was demonstrated

- **Provider lifecycle**: `@sandboxenv(name="ranges_spike")` with `sample_init` (validate spec → compile → `compose up` → boot VMs → wait on vsock daemons → env per guest, `default` = the attacker box) and `sample_cleanup` (`compose down -v`; verified no residue). Idempotent init (best-effort `down` first) — a stale project means stale VMs on old images, learned the hard way.
- **Schema → runtime loop closed**: the compiler consumes `RangeSpec` from `inspect_ranges.schema` — the v0.1 models are demonstrably sufficient to drive the runtime, not just to validate files.
- **The smoke task** (deterministic solver, mockllm): exec on `default`, cross-VM ping over the compiled segment, file round-trip, flag planted and recovered via the named `web` sandbox, scored with `includes()`. **accuracy 1.000, 15–16 s total per run** including boot and teardown.
- **`self_check`: 41/44** — cwd (all four), env vars, user/nonexistent-user exec, text/binary/large stdin, shell-special input, large commands, UTF-8 output/stderr, return codes, **all four timeout tests** (in-daemon timeout with process-group kill), text/binary/large file round-trips, nested directories, limits, is-directory/not-found errno mapping.

## Findings (each changed code or goes on the daemon punch list)

1. **Bulk data must never ride in the protocol's control message.** The prototype carried exec stdin as base64 inside the JSON header line, and both ends read headers one byte per `recv()` — `self_check`'s 1 MB-stdin test turned that into ~1.4 M syscall round-trips and an apparent hang. Fixed: stdin is a sized raw stream after the header; header/reply reading is buffered with remainder-carry. The production protocol should length-prefix everything (same lesson as PVE's 61440-char inline cap in [guest-exec-lessons](../../inspect-ranges/guest-exec-lessons.md)).
2. **The daemon-as-root breaks permission semantics** — the three remaining failures (`read/write *_without_permissions`): root in the guest reads chmod-000 files happily. The production daemon needs a **default unprivileged user** for sandbox file/exec operations (root only on explicit `user=` — matching how Inspect's Docker provider behaves as the container user). This interacts with the agent image design (which user is the agent?).
3. **Signal-death exit codes**: Python's `Popen` reports -N; the sandbox contract expects shell convention 128+N. Mapped in the provider (prefer mapping at the daemon in production).
4. `exec` of a missing/non-executable binary, missing cwd, nonexistent user all needed explicit errno-tagged replies to satisfy the contract's exception mapping — the error *taxonomy* is as much a part of the protocol as the happy path.
5. Lifecycle hygiene: `pkill` on the harness side leaves the range running — exactly why cleanup must key off the compose project (and why the production provider needs the ported cleanup-registry pattern from [docker-provider-reuse](../../inspect-ranges/docker-provider-reuse.md)).

## Scope deliberately not covered (unchanged design intents)

Single sample at a time (no per-sample project naming/CID allocation); no kept-alive failed ranges; no Windows/qemu-ga path; no idempotent request IDs or durable results (the channel never dropped mid-suite, but the [guest-exec-lessons](../../inspect-ranges/guest-exec-lessons.md) requirements stand); no hostile-daemon shim run; blocking sockets via `asyncio.to_thread` (fine at this scale).

## Files

- `range.yaml` — schema-v0.1-valid two-guest spec (`inspect-ranges validate` green)
- `compiler.py` — `RangeSpec` → bridges/seeds/CIDs/boot script (consumes the real schema)
- `provider.py` — the spike `SandboxEnvironment` (lifecycle + exec/read/write over vsock)
- `guest/vsockd2.py` — daemon v2: argv exec, stdin/cwd/env/user, in-daemon timeout with group kill, errno-tagged file ops, buffered protocol
- `task.py` — the smoke task (deterministic solver, mockllm)
- `run_self_check.py` — boots a range and tallies all 44 `self_check` coroutines
