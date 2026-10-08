# Inspect Ranges

## Overview

Inspect Ranges is an [Inspect AI](https://inspect.aisi.org.uk) extension for evaluating models and agents on network intrusion and defense tasks, using cyber ranges built from libvirt/KVM virtual machines.

> **NOTE: Note**
>
> Inspect Ranges is under active development and is not yet ready for general use. These pages are published for reviewers, and the design and syntax may change in response to feedback.

The source code is available in the [inspect_ranges](https://github.com/meridianlabs-ai/inspect_ranges) repository on GitHub. For the overall design (range definitions, the libvirt/KVM runtime, attacker containment, and evidence collection), start with the [Inspect Ranges overview](https://github.com/meridianlabs-ai/inspect_ranges/blob/main/design/ranges-overview.qmd).

## Defining Ranges

Documentation for the range definition language (`range.yaml` and its typed Python equivalent) is available for review and feedback:

- [Ranges](./ranges.html.md): what a range definition is, end-to-end examples in YAML and Python, and the validation workflow.

- [Guests](./guests.html.md): hosts, images, resources, routers and the attacker as guests, and guest content such as accounts, services, seeded weaknesses, defense, and Active Directory.

- [Networks](./networks.html.md): addressing, DHCP, name resolution, segmentation, firewall rules, routing topology, and egress.
