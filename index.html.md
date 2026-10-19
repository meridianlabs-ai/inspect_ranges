# Inspect Ranges

## Overview

Inspect Ranges is an [Inspect AI](https://inspect.aisi.org.uk) extension for evaluating models and agents on network intrusion and defense tasks, using cyber ranges built from libvirt/KVM virtual machines.

> **NOTE: Note**
>
> Inspect Ranges is under active development and is not yet ready for general use. These pages are published for reviewers, and the design and syntax may change in response to feedback.

The source code is available in the [inspect_ranges](https://github.com/meridianlabs-ai/inspect_ranges) repository on GitHub. For the overall design (range definitions, the libvirt/KVM runtime, attacker containment, and evidence collection), start with the [Inspect Ranges overview](https://github.com/meridianlabs-ai/inspect_ranges/blob/main/design/ranges-overview.qmd).

## Documentation

The [Tutorial](./tutorial.html.md) is a hands-on walkthrough, from a first minimal range to building and evaluating the vulhub-zabbix example. The rest of the documentation is organized in three sections, available for review and feedback:

- [Building Ranges](./building.html.md): authoring a range, from the definition language ([Ranges](./ranges.html.md), [Guests](./guests.html.md), [Networks](./networks.html.md)) to the build that realizes declared content into captured, verified images.

- Evaluation: [Challenges](./challenges.html.md) covers defining what an agent is asked to do and how success is verified; [Custom Goals](./goals.html.md) covers creating new goal types; [Evidence](./evidence.html.md) covers the tamper-evident record scoring relies on.

- [Running Ranges](./cli.html.md): the operator workflow, the [sandbox provider](./provider.html.md) that runs Inspect evals against ranges, the [host topology](./topology.html.md), and the [security model](./security.html.md).
