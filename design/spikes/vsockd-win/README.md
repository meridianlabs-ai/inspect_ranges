# Spike: vsockd-win — the Windows vsock daemon port

*Executes the plan agreed 2026-10-04: a parity port of the v2 wire protocol ([vsockd2.py](../e2e-provider/guest/vsockd2.py)) to Windows, validated hard, so the control plane unifies across guest OSes and the qemu-ga exec machinery + ISO hot-plug bulk path can retire for Windows targets. Protocol v3 (request IDs, durable acked results, length-prefixed framing, hostile-daemon shim) remains the named successor at production-provider start; this port's codec is isolated behind an interface so v3 is a swap, not a rewrite. Run on the m6i.metal devbox, 2026-10-04. `./run.sh` reproduces end to end (ISOs from the win-guest cache; busybox-w32 fetched to the cache); `./run.sh down` tears down; `./run.sh bootstrap|conformance` run partial phases; `./redeploy.sh` is the dev loop.*

## Verdict

**The port works, and Windows targets can join the vsock control plane as first-class citizens.** A ~700-line C# 5 daemon (compiled in-guest by the in-box .NET Framework 4.8 `csc.exe` — no toolchain or download added to images) runs as an auto-restarting SYSTEM service and speaks the identical wire protocol, verified by the identical host-side provider code that scored 41/44 against the Linux daemon: **40/44 `self_check` with zero unexpected failures** (every xfail a documented platform fact, below), **15/15 Windows-native supplement checks**, **570/570 soak operations with zero flake** (qemu-ga baseline: ~5–7%), clean recovery across `virsh save`/`restore` and reboot, and a file plane at **400/281 MB/s** write/read — roughly **500×** the 0.6 MB/s qemu-ga file plane it replaces.

## Measurements (metal, final clean run)

| What | Result | Baseline |
|---|---|---|
| channel RTT (ping op, ×1000) | **0.36 ms** median, 0.42 p95 | Linux exec RTT 1.1 ms; qemu-ga ~2 s/call |
| exec RTT (`cmd /c exit 0`, ×50) | **17.3 ms** median (Windows process creation dominates) | qemu-ga exec ~2 s |
| file plane, 100 MB verified | **write 400 MB/s, read 281 MB/s** (raw channel read: 449 MB/s) | qemu-ga ~0.6 MB/s; Linux vsock ~400/700 MB/s |
| `self_check` conformance | **40 passed, 4 xfailed, 0 unexpected** of 44 | Linux daemon: 41/44 |
| native supplement | **15/15** (argv quoting incl. empty args, byte fidelity, UTF-8, output cap, concurrency, background survival, user=, tree-kill) | — |
| soak | **570/570**, zero failures (500 sequential + 50 parallel execs + 20 file round trips) | qemu-ga ~5–7% flake |
| save/restore mid-session | in-flight call severed cleanly; next op succeeds (per-op connect) | — |
| reboot | service auto-restarts, daemon answers unattended | — |

## The xfail list (all four are platform facts, not daemon defects)

1. `test_read_file_not_allowed` — NTFS has no POSIX read-permission bit; nothing maps `chmod -r`. (The write-permission siblings **pass**: busybox `chmod -w` sets the read-only attribute, which Windows honors even for SYSTEM.)
2. `test_exec_as_user` — the suite provisions its test user via `adduser`/`userdel`. The `user=` path itself passes in the supplement (`LogonUser` + `CreateProcessAsUser` from SYSTEM, credentials from the image-planted config; nonexistent users fail cleanly).
3. `test_exec_large_command` — Windows caps command lines at 32,767 UTF-16 chars (vs Linux `ARG_MAX` 2 MiB); the suite's ~1 MiB argv exceeds the platform. The daemon replies a clean `E2BIG`.
4. `test_exec_timeout_not_raised_on_fast_signal_death` — no POSIX signals on Windows; busybox's `kill` emulation exits 0, not 143.

How the suite runs on Windows at all: the test image (never production goldens) stages busybox-w32 applets in `C:\usr\bin` (on PATH; also satisfies the suite's `/usr/bin` cwd fixture), `C:\tmp`, and `C:\etc\passwd` (the suite hardcodes `/etc` for its is-directory and exec-permission fixtures; `.NET` resolves `/`-rooted paths against the system drive, so both sides agree).

## viosock provider quirks found (the knowledge the port encodes)

1. **No blocking mode**: recv on an empty queue and send into a full TX buffer fail immediately — recv with `WSAEWOULDBLOCK`, send with NTSTATUS `0xC0000023` (`STATUS_BUFFER_TOO_SMALL`), which is also its answer for a genuinely oversized single send. The daemon treats both as poll-and-retry.
2. **Single sends above ~32 KiB are rejected outright** (even into an empty buffer; 64 KiB always fails). Sends are chunked at 32 KiB.
3. **No working select or overlapped I/O**: `WSPSelect` and IOCP-backed `Begin*` both fail ("operation not supported"), so waits are yield/sleep-based (`timeBeginPeriod(1)` keeps backoff at ~1 ms).
4. None of this hurts throughput in practice (400 MB/s with a prompt reader), and the Linux side of the connection behaves normally.

## Design consequences

1. **The OS-split exec plane ends.** Windows targets speak the same protocol, through the same provider code, with the same errno taxonomy (`ENOENT`/`EACCES`/`EISDIR`/`ENOTDIR` mapped from Win32/.NET; spawn failures as rc 127/126 with the provider's expected message shapes). ISO hot-plug retires as the Windows bulk path; qemu-ga returns to being a build-time image tool.
2. **Image recipe addition** (production goldens): `pnputil` the signed viosock driver, drop in `VsockDaemon.cs`, compile with in-box csc, register the service — all offline, scripted in [install-daemon.ps1](assets/guest/install-daemon.ps1). The busybox/`/etc` staging is test-image-only.
3. **Windows exec semantics worth keeping**: Job Objects give airtight tree-kill (a detached `Start-Process` grandchild dies with the timeout; verified), without `KILL_ON_JOB_CLOSE` so legitimately detached background processes survive the call. Exit codes pass through as Windows reports them (NTSTATUS values appear as large integers; no signal mapping).
4. **For protocol v3**: the codec seam held (all wire format lives in one class); the provider quirks above argue for v3 keeping payload chunking explicit and never trusting transport-level blocking semantics.
5. **Not yet done**: wiring Windows guests through the production compiler/provider path (this spike drives a standalone guest), measured daemon behavior under memory-snapshot *checkpoint* flows (plain save/restore is verified), and the v3 contract itself.

## Files

- `assets/guest/VsockDaemon.cs` — the daemon (C# 5 / .NET Framework 4.8): vsock endpoint shim, codec behind an interface, the five ops, CreateProcess/CreateProcessAsUser exec engine with Job Objects, errno mapping, ServiceBase + `-console` mode
- `assets/guest/install-daemon.ps1` — in-guest setup (driver, compile, service, test fixtures)
- `assets/boot-vm.sh`, `compose.yaml`, `range/`, `assets/{autounattend.xml,install.sh}`, `ga.py` — boot/bootstrap machinery (qemu-ga is the bootstrap channel only)
- `harness/run_self_check_win.py` — the 44-test suite via the e2e provider class, with the xfail list
- `harness/windows_checks.py` — the native supplement
- `harness/soak.py`, `harness/perf.py`, `harness/v2client.py` — stdlib soak/perf/CLI
- `redeploy.sh` — dev loop (daemon-carried push with chunked qemu-ga fallback)
- `tmp/run-final-clean.log` — the authoritative run
