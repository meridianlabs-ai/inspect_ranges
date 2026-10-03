# inspect_ranges

Working folder for **`inspect_ranges`** — a new [Inspect](https://inspect.aisi.org.uk/) package for defining cyber range evaluations via a `range.yaml` format, backed by a new libvirt-based sandbox (Docker/Compose compatibility is a non-goal). Project opened 2026-09-30.

* **[Design and architecture review (draft 1)](architecture.md)** - the synthesis document for broader review: system overview, spec/networking/control-plane design with measured spike evidence, the full security analysis, deployment model, performance envelope, implemented-vs-designed ledger, and open questions

* [Small realistic cyber ranges — source survey](survey.md) - what public artifacts define small, realistic, quickly-runnable ranges with machine-readable configs; the six selected for the baseline; catalog of everything surveyed; finding: the full MHBench corpus is public, with a measured assessment
* [range.yaml — draft schema swag (v0.1)](range-yaml-swag.md) - the working strawman schema the six examples exercise: the L1–L9 range anatomy and D0–D5 defense spectrum, the networking-requirements table (each requirement → its libvirt realization → the example that forces it), and the attack_path concept mapped across surveyed formats
* [Decision: schema v0.1 scope](schema-v0.1-scope.md) - the implemented schema (`inspect_ranges.schema`, `inspect-ranges validate`) covers only the strict runtime core (range/networks/routers/hosts/attacker); the deferral table for everything excluded, and the normalizations applied to the examples (whose carved content lives in each `deferred.yaml`)
* [Decision: own the libvirt sandbox provider](docker-provider-reuse.md) - why we write our own provider rather than reusing Inspect's Docker provider, what we give up, and which pieces we port (with attribution) vs rewrite
* [Decision: untrusted-agent containment](agent-containment.md) - the agent is always a VM (`kind: vm`) controlled over virtio-vsock, no privileged components anywhere; Nitro one-sample-per-instance is the inter-sample boundary; vsock control-plane and L2 exposure rules
* [Decision: deployment seam](host-provider.md) - sharded Inspect with strictly local realization (worker on each Nitro instance, direct vsock); the remote `HostProvider`/Docker-endpoint path is deferred — a documented fallback built only if sharding proves unviable; isolation is a logged per-sample claim
* [Guest exec/file edge cases](guest-exec-lessons.md) - lessons mined from the Proxmox provider's qemu-ga handling (single-shot exec-status, flock-guarded launches, ~5–7% Windows channel flake, tamper validation) and the contract they impose on the vsock daemon
* [Image distribution](image-distribution.md) - qcow2 backing chains as content-addressed OCI layers (Docker's distribution model transplanted), EBS/FSR as the fleet cold-start path, curl+copy-on-read lazy pull, CDC held for base-rebuild churn
* [Upstream licenses and attribution](LICENSES.md) - what is vendored under each `upstream/` directory, from where, and under which license

## Example ranges (development/testing baseline)

Each directory holds `range.yaml` (our translation, draft schema v0.1), `challenges.yaml` (task prompts as example-dataset seeds — verbatim from the upstream ecosystem where tasks exist: KYPO training levels, Incalmo attacker prompts, cochise pentest scenario; tagged as ours where not), `notes.md` (per-field provenance, tagged defaults, to-verify items), and `upstream/` (the verbatim original source configs and prompts, so `inspect_ranges` code can see the originals, not just our translation).

* [vulhub-zabbix](ranges/vulhub-zabbix/notes.md) - 4 Linux hosts, flat network, real CVE (Zabbix SQLi→RCE); the minimal/smoke-test case
* [kypo-demo](ranges/kypo-demo/notes.md) - 2 hosts + explicit router across 2 routed subnets; static IPs, randomized variables (KYPO CRP)
* [cyris-basic](ranges/cyris-basic/notes.md) - firewall-gatewayed office/servers segments with per-guest task provisioning (CyRIS, KVM-native)
* [mhbench-equifax-small](ranges/mhbench-equifax-small/notes.md) - breach-derived 3-subnet enterprise with asymmetric ACLs and a planted SSH-key pivot (MHBench, CMU)
* [goad-light](ranges/goad-light/notes.md) - 3-VM Windows AD forest (parent+child domains) with seeded AD attack surface and Defender toggles (GOAD)
* [attack-range-windows](ranges/attack-range-windows/notes.md) - Splunk-instrumented Windows endpoint; telemetry as first-class config (Splunk attack_range)
