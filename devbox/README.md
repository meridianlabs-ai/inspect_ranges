# Remote development box

inspect_ranges needs Linux with KVM (libvirt/QEMU inside containers, via a metal instance or nested virtualization, plus Docker), so development happens on an EC2 devbox rather than locally. `inspect-ranges devbox` provisions one per developer and manages its lifecycle.

```bash
uv run inspect-ranges devbox --profile <profile> --region <region> up
ssh inspect-ranges-devbox
```

Then in VS Code: **Remote-SSH: Connect to Host...** → `inspect-ranges-devbox` and open `~/inspect_ranges`.

## Prerequisites

Locally:

- [`uv`](https://docs.astral.sh/uv/), `aws` CLI v2, and the [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html) (`brew install awscli session-manager-plugin`)
- A GitHub fine-grained personal access token for the box (see [GitHub access](#github-access))
- AWS credentials with the permissions listed [below](#iam-permissions)

VS Code: install the **Remote - SSH** extension and raise its connect timeout, because connecting to a stopped box starts it first, which takes a minute or two:

```json
"remote.SSH.connectTimeout": 300
```

## Commands

Global options: `--profile`, `--region` (these default to `AWS_PROFILE`/`AWS_REGION` or your AWS config) and `--name` (defaults to your local username; each developer gets their own box).

| Command | Description |
|---|---|
| `up` | Create the devbox if needed, start it, and bring it up to date. Safe to re-run. |
| `start` / `stop` | Start or stop the box. Stopping keeps the disk. |
| `status` | Show state, instance type, and auto-stop setting. |
| `ssh-config` | Rewrite the local SSH entry (`~/.ssh/config.d/inspect-ranges-devbox`). |
| `github-token` | Store a GitHub token on the box (read from stdin), then clone and sync the repo. |
| `destroy [--all]` | Terminate the box (deleting its disk, including its GitHub token). `--all` also removes the shared VPC and IAM role when no devboxes remain. |

`up` options (the instance options apply only when the box is created): `--instance-type` (default `m8i.8xlarge`; must be c8i/m8i/r8i for nested virtualization, or an x86 metal instance such as `m6i.metal`), `--volume-size` (500 GiB), `--iops` (6000), `--throughput` (500 MiB/s), `--idle-minutes` (60), `--backstop-hours` (6).

You rarely need `start`. SSH and VS Code connect through a `ProxyCommand` that starts a stopped box automatically.

## What's on the box

Ubuntu 24.04 with:

- **Virtualization:** QEMU/KVM, libvirt, virt-install, libguestfs-tools (virt-customize), OVMF, cloud-image-utils. `vhost_net` and `tun` are loaded.
- **Containers and images:** Docker CE with the compose plugin, Packer, ORAS.
- **Developer tools:** git, gh, uv, Claude Code (sign in yourself), tmux, screen, iperf3, fio.
- **Repo:** `~/inspect_ranges` is cloned and synced with `uv sync --group dev`.

Host provisioning lives in [`bootstrap.sh`](bootstrap.sh). It runs once at first boot via cloud-init; the log is at `/var/log/devbox-bootstrap.log`. To pick up changes to it, `destroy` and then `up` again.

## Auto-stop

The box stops itself after `--idle-minutes` (default 60) of inactivity. A systemd timer checks every 5 minutes, and the box counts as active when any of these hold:

- an SSH session is open (this includes VS Code Remote-SSH),
- an SSM session is open,
- the 5-minute load average is at least 1.0 (running evals and image builds keep it up),
- a keepalive is set: `devbox-keepalive 4h` (or `30m`, or `off`).

Stopping is an in-guest `shutdown`. The instance is configured to stop rather than terminate on shutdown, so the disk and everything on it survive.

A CloudWatch alarm acts as a **backstop**. It stops the box after `--backstop-hours` (default 6) of average CPU below 2%, even if the on-box check is broken or disabled. The backstop can't see `devbox-keepalive`. For a long, mostly-idle run, pass `--backstop-hours 0` (or a larger value) to `up`.

The disk is billed while the box is stopped. Use `destroy` when you're done with it for good.

## Security model

The design doc (§5, §10) assumes that anything running on a range host may escape its VM or container. So the box holds as few credentials as possible, and there's nothing inbound to attack.

| Measure | How |
|---|---|
| No exposed ports | The security group has **no inbound rules**. SSH is tunnelled over SSM Session Manager (`AWS-StartSSHSession`), so every connection is IAM-authenticated and recorded in CloudTrail. The public IP is used only for outbound traffic. |
| Restricted egress | The dedicated VPC allows outbound **TCP 80/443 only**. Git uses HTTPS. |
| IMDSv2, hop limit 1 | Instance metadata requires session tokens, and containers and VMs on the box can't reach it. |
| Minimal instance role | `AmazonSSMManagedInstanceCore` only. There are no AWS credentials on the box, and auto-stop needs no EC2 permissions. |
| GitHub access limited to one repo | A fine-grained token that can change **contents and pull requests of `meridianlabs-ai/inspect_ranges` only**, and nothing about workflows. No SSH agent or credential forwarding. See [GitHub access](#github-access). |
| Dedicated SSH key | `~/.ssh/inspect_ranges_devbox` is used only for the devbox. Host keys are pinned per box in `~/.ssh/known_hosts.d/`. |
| Encryption at rest | The EBS root volume is encrypted. |

Recommendations:

- **Protect `main`** with branch protection. Otherwise the box's token can push to it directly.
- **Use a separate AWS account** for devboxes if you can, so a compromised box can't reach anything else in the account.

## GitHub access

The box authenticates to GitHub with a **fine-grained personal access token** limited to this one repo. (The `meridianlabs-ai` org disables deploy keys, and forwarding your own GitHub login would give anything running on the box access to every repo you can push to, workflows included.)

Create the token at <https://github.com/settings/personal-access-tokens/new>:

- **Resource owner:** `meridianlabs-ai`
- **Expiration:** your choice (e.g. 90 days)
- **Repository access:** *Only select repositories* → `inspect_ranges`
- **Permissions → Repository:** *Contents: Read and write*, *Pull requests: Read and write* (*Metadata: Read-only* is added automatically). Nothing else. In particular, not *Workflows*.

If the org requires approval for fine-grained tokens, an org admin approves it under Org settings → Personal access tokens.

Copy the token and pipe it in, so it never appears in your terminal or shell history:

```bash
pbpaste | uv run inspect-ranges devbox --profile <profile> --region <region> github-token
```

On the box, `gh` stores the token (`~/.config/gh/hosts.yml`, mode 0600) and acts as git's credential helper, so both `git push` and `gh pr create` work from any terminal. Because the token has no *Workflows* permission, pushes that change `.github/workflows/` are rejected; make those changes from your own machine. When the token expires, create a new one and run `github-token` again. To revoke it, delete it in GitHub settings.

## IAM permissions

The credentials that run `inspect-ranges devbox` need roughly this policy. Replace `ACCOUNT`.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Ec2",
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "ec2:CreateVpc", "ec2:ModifyVpcAttribute", "ec2:DeleteVpc",
        "ec2:CreateSubnet", "ec2:DeleteSubnet",
        "ec2:CreateInternetGateway", "ec2:AttachInternetGateway", "ec2:DetachInternetGateway", "ec2:DeleteInternetGateway",
        "ec2:CreateRoute",
        "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup",
        "ec2:AuthorizeSecurityGroupEgress", "ec2:RevokeSecurityGroupEgress",
        "ec2:RunInstances", "ec2:StartInstances", "ec2:StopInstances", "ec2:TerminateInstances",
        "ec2:ModifyInstanceAttribute", "ec2:CreateTags"
      ],
      "Resource": "*"
    },
    {
      "Sid": "InstanceRole",
      "Effect": "Allow",
      "Action": [
        "iam:GetRole", "iam:CreateRole", "iam:DeleteRole", "iam:TagRole",
        "iam:AttachRolePolicy", "iam:DetachRolePolicy",
        "iam:GetInstanceProfile", "iam:CreateInstanceProfile", "iam:DeleteInstanceProfile", "iam:TagInstanceProfile",
        "iam:AddRoleToInstanceProfile", "iam:RemoveRoleFromInstanceProfile",
        "iam:PassRole"
      ],
      "Resource": [
        "arn:aws:iam::ACCOUNT:role/inspect-ranges-devbox",
        "arn:aws:iam::ACCOUNT:instance-profile/inspect-ranges-devbox"
      ]
    },
    {
      "Sid": "Ssm",
      "Effect": "Allow",
      "Action": ["ssm:GetParameter", "ssm:DescribeInstanceInformation", "ssm:StartSession", "ssm:TerminateSession"],
      "Resource": "*"
    },
    {
      "Sid": "Backstop",
      "Effect": "Allow",
      "Action": ["cloudwatch:PutMetricAlarm", "cloudwatch:DeleteAlarms", "cloudwatch:TagResource"],
      "Resource": "*"
    },
    {
      "Sid": "BackstopServiceLinkedRole",
      "Effect": "Allow",
      "Action": "iam:CreateServiceLinkedRole",
      "Resource": "arn:aws:iam::*:role/aws-service-role/events.amazonaws.com/AWSServiceRoleForCloudWatchEvents*",
      "Condition": {"StringLike": {"iam:AWSServiceName": "events.amazonaws.com"}}
    }
  ]
}
```

## Troubleshooting

- **`up` says the box has no GitHub token:** create one and run `github-token` (see [GitHub access](#github-access)); `up` finishes the remaining setup after that.
- **`up` fails during provisioning:** run `ssh inspect-ranges-devbox sudo tail -100 /var/log/devbox-bootstrap.log`.
- **`/dev/kvm is missing`:** the instance type can't run KVM (not metal, and nested virtualization unsupported or not enabled at launch). `destroy` and `up` with a c8i/m8i/r8i type or an x86 metal instance.
- **VS Code times out connecting:** raise `remote.SSH.connectTimeout` (see [Prerequisites](#prerequisites)).
- **Host key warning after re-creating a box:** `up` clears the pinned key automatically. Otherwise delete `~/.ssh/known_hosts.d/inspect-ranges-devbox`.
