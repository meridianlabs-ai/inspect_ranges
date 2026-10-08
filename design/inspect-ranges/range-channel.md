---
type: decision
title: "RangeChannel wire contract: transport-independent messages for realization, guest control, and evidence"
status: accepted
tags: [inspect-ranges, sandbox, deployment, channel, protocol, decision]
timestamp: 2026-10-04
---

# RangeChannel wire contract: transport-independent messages for realization, guest control, and evidence

*Decision record, companion to the re-cut deployment seam in [host-provider](host-provider.md). The seam contracts on a `RangeChannel`; this records what every transport of that channel must satisfy at the message level. The requirements are not new: the [guest-exec-lessons](guest-exec-lessons.md) punch list already binds the vsock daemon to most of them. A protocol with request IDs and durable replies is already an asynchronous message protocol; the long-lived stream was only ever an optimization. Specify these properties once and transports differ only in latency.*

## Two planes, one set of properties

The channel carries two kinds of traffic, kept distinct in the protocol:

- **Host lifecycle**: `realize` and `teardown` requests; staged progress reports (fetch, construct, boot, verify, ready | failed) with structured diagnostics; a periodic heartbeat with per-guest state. These address the host's applier.
- **Guest control**: `exec`, `read_file`, `write_file`, `forward`. These address a named guest and are relayed to its vsock daemon.

Both planes ride the same message contract below. A transport that can deliver a schema-validated message and return a schema-validated reply can carry the channel; nothing in the contract requires a connection.

## Message properties every transport must satisfy

1. **Request IDs**: every request carries an ID; a retried request with the same ID never double-runs (the channel-level form of the daemon's idempotent-launch rule, itself the vsock equivalent of the Proxmox wrapper's flock guard).
2. **Idempotent retry**: a lost reply is recovered by re-sending the request, never by guessing at state.
3. **Durable replies**: completed results are held (bounded) until acknowledged, so a dropped reply is re-readable (the channel-level form of the daemon's results-held-until-acked rule, itself the vsock equivalent of results-on-disk).
4. **Bulk data never rides the control message**: file contents, large stdout, and the realization bundle's artifacts travel length-prefixed out of band of the control payload (the e2e spike's lesson, generalized).
5. **Error taxonomy**: errors are errno-tagged with the exit-code semantics already specified for the daemon (`FileNotFoundError`/`IsADirectoryError`/`PermissionError` mappings, unsigned-exit-code conversion, killed-by-signal reporting).
6. **Layered budgets**: per-command timeout (enforced in-guest), channel-communication allowance, and an untimed-command bound are independent, exactly as the daemon contract already layers them. "Reliable" is a measurement, not a property; the budget layer is where stall and tamper detection lives.

## Every reply is untrusted input

Everything arriving over the channel — stage reports, exec results, heartbeats — originates on the attackable instance, and after a compromise is attacker-influenceable. The rule [guest-exec-lessons](guest-exec-lessons.md) states for daemon replies applies at the channel layer unchanged: strict-schema-validate every reply, enforce byte caps reader-side (never trust a length field), and surface anything an honest endpoint cannot produce as a tamper error, not a parse fallback.

## Conformance

Two mock channels join the conformance suite beside the hostile-daemon shim, from the first provider implementation:

- **A hostile mock channel** feeding malformed, oversized, and protocol-violating replies to the driver, verifying the validation rule above end to end.
- **A latency-injecting mock channel** running the full `self_check` battery at second-scale round trips in CI, so a multi-round-trip regression in the hot path fails fast instead of surfacing only on a slow backend.

The state machine from the seam (acquire → realize → verify → execute → finalize evidence → destroy) is testable against a mock channel with no cloud behind it.
