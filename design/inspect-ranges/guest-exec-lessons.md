---
type: document
title: "Guest exec/file edge cases: lessons from the Proxmox provider (and what they imply for the vsock daemon)"
audience: inspect-ranges development
status: draft
tags: [inspect-ranges, sandbox, qemu-guest-agent, vsock, exec, prior-art]
timestamp: 2026-10-01
---

# Guest exec/file edge cases: lessons from the Proxmox provider (and what they imply for the vsock daemon)

*On the Proxmox provider author's advice ("proxmox basically just wraps the QEMU API in exec/read_file/write_file, and you'll run into the same edge cases"), surveyed `UKGovernmentBEIS/inspect_proxmox_sandbox` (MIT, surveyed 2026-10-01: `_impl/agent_commands.py`, `_impl/qga_responses.py`, `_proxmox_sandbox_environment.py`, `tests/..._hostile_guest_agent_e2e.py`). Everything below is encoded behavior, not documentation — exactly the hard-won class of knowledge the [docker-provider-reuse](docker-provider-reuse.md) decision ports from Inspect's Docker provider. This doc splits the findings into: facts about qemu-ga we inherit directly (our Windows-target path, per [agent-containment](agent-containment.md)), and contract lessons the vsock daemon must satisfy even though its transport avoids most of the mechanics.*

## The architectural lesson: never run the user's command directly

The provider's exec never passes the user's command to `guest-exec` directly. It generates a **wrapper script** (sh / batch), uploads it, and runs that. The wrapper: applies `cd`/env/`su -l <user>`/stdin, enforces the timeout **in-guest** (`timeout -k 5s <t>s`), and — crucially — **writes stdout, stderr, and returncode to disk files** before exiting. Nearly every reliability property hangs off this:

- **`guest-exec-status` is single-shot**: qemu-ga discards a finished process's captured output after one successful read. A retry whose first response was lost finds the PID gone — *with the output gone too*. The disk files turn "PID does not exist" into "finished; read results from disk", making status polling idempotent and freely retryable.
- **Retried launches can double-run the command** (narrow window: agent received `guest-exec`, the pid response was lost). The wrapper opens an **flock keyed on the per-exec temp path**; the duplicate launch blocks and the command runs once.
- Output limits become capped file reads with an explicit truncated flag → `OutputLimitExceededError` with partial output, matching the `self_check` contract.
- A wrapper that dies before writing its returncode file is detectable (`ReturnCodeNotWritten` → report killed-by-signal / 137 with an explanatory stderr note).

## Facts about qemu-ga / the virtio-serial channel (inherited by our Windows path)

- **The channel is genuinely flaky on Windows: ~5–7% of calls fail** ("got timeout", "is not running", "being used by another process"). The provider wraps *every* QGA call in retry with exponential backoff and a total time budget, with careful transient-vs-permanent classification (missing file, EISDIR, pid-gone are surfaced immediately; everything 5xx/transport retries). Reliability is a protocol layer, not an afterthought.
- **Budgets are layered**: command timeout ≠ agent-communication allowance (180 s) ≠ untimed-command bound (4 h, env-tunable); poll backoff capped at 30 s; polling runs `timeout + 8 s` grace so the in-guest SIGKILL's real exit is observed rather than racing it.
- **qemu-ga caps captured exec output at 16 MiB per stream** (`GUEST_EXEC_MAX_OUTPUT`) — another reason the wrapper redirects to files instead of using capture-output for real workloads.
- **Non-ASCII bytes in `guest-exec` argv can wedge the agent bridge** (Proxmox bug 6609 observed at the PVE layer; the defensive conclusion generalizes): keep argv ASCII — ship anything interesting via the uploaded script/file, never inline.
- **Windows specifics**: qemu-ga does not expand `%TEMP%` (hardcode `C:\Windows\Temp`); exit codes come back as unsigned 32-bit (convert to negative for >2³¹); error strings are platform-specific ("cannot find the path" vs "No such file or directory") and are the only material for errno mapping (`FileNotFoundError`/`IsADirectoryError`/`PermissionError` — the rc-126 + single-line-stderr heuristic for exec-permission-denied is deliberate and worth copying).
- **Payload caps force chunking at every boundary** (some PVE-specific, the pattern general): write chunking with guest-side reassembly (`cat` / `copy /b`), stdin above ~30 KiB written to a file and redirected rather than inlined, file reads capped per call (clamp externally-raised limits to the transport cap). Their ISO hot-plug fast path kicks in at ≥128 KiB on Linux — and the upload path for the exec wrapper itself must be **bootstrap-safe** (must not recurse into exec).
- Temp-file cleanup is fire-and-forget exec; per-exec temp names are timestamped (also our crash-leak finding from [the win-guest spike](../spikes/win-guest/README.md) — stale `guest-file-open` handles block reopening).

## The adversarial lesson: validate every reply from the guest

The provider treats the guest agent as **an attacker-controlled endpoint** (an agent that roots a VM owns its qemu-ga). `qga_responses.py` strict-schema-validates (pydantic, Strict types) every exec/file reply and raises `GuestAgentTamperError` for anything an honest qemu-ga cannot produce — and the e2e suite includes a **canned hostile guest-agent shim** that replaces qemu-ga and feeds malformed/malicious replies to the provider. One subtle decode bug class caught there: Proxmox concatenates independently-encoded base64 chunks, so naive whole-string decode silently stops at the first padded chunk — decode segment-wise.

This operationalizes agent-containment's "guest-agent responses are untrusted input" rule, and it applies **with equal force to our vsockd protocol** on compromised Linux targets: the daemon's replies must be strict-schema-validated, byte caps enforced reader-side (never trust a length field), and a hostile-daemon shim belongs in our conformance tests from day one.

## What this means for us, concretely

**qemu-ga path (Windows targets): port, don't rediscover.** `inspect_proxmox_sandbox` is MIT — add it alongside `inspect_ai`'s Docker provider as a porting source in [docker-provider-reuse](docker-provider-reuse.md): the retry/classification layer, the wrapper-script generators (sh + batch), the single-shot/disk-results dance, exit-code semantics, errno mapping, response validation. Strip the PVE-API-specific caps; keep the qemu-ga-level ones (16 MiB streams, no env expansion, unsigned exit codes).

**vsock path (agent + Linux targets): the transport dodges the mechanics, not the contract.** Vsock has no single-shot status, no payload caps, no 5–7% channel flake — but the daemon must still deliver, by design rather than by accident:

1. **Idempotent, retry-safe launches** — a request ID per exec so a reconnect-and-retry after a dropped reply never double-runs (the vsock equivalent of the flock guard).
2. **Durable results independent of any one reply** — completed exec results held (bounded) until acknowledged, so a lost response is re-readable (the vsock equivalent of results-on-disk).
3. **In-guest timeout with kill-grace and process-tree kill**, observed via poll grace, exactly per the wrapper semantics.
4. **cwd/env/user/stdin** in the daemon's exec contract from the start (`self_check` exercises them), with the same exit-code and errno mappings.
5. **Strict reply validation + hostile-daemon shim tests** (above).
6. Layered budgets (per-command vs channel vs untimed bound) even though the channel is reliable — "reliable" is a measurement, not a property, and the budget layer is where tamper/stall detection lives (agent-containment's "stalled or tampered" timeout language, which the Proxmox provider also uses).

## Updates made elsewhere

- [docker-provider-reuse](docker-provider-reuse.md): `inspect_proxmox_sandbox` added as a second porting source (guest-agent path).
- [agent-containment](agent-containment.md): vsockd production requirements extended with idempotent launches, durable results, and hostile-daemon testing.
