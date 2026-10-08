# Reference – Inspect Ranges

Provision and manage an inspect_ranges development box on EC2.

#### Usage

``` text
inspect-ranges [OPTIONS] COMMAND [ARGS]...
```

#### Subcommands

|  |  |
|----|----|
| [up](#inspect-ranges-up) | Create (or start) the devbox and bring it fully up to date. |
| [github-token](#inspect-ranges-github-token) | Store a GitHub token on the devbox (read from stdin), then clone the repo. |
| [start](#inspect-ranges-start) | Start the devbox and wait until it accepts connections. |
| [stop](#inspect-ranges-stop) | Stop the devbox (the disk is kept). |
| [status](#inspect-ranges-status) | Show the devbox’s state. |
| [ssh-config](#inspect-ranges-ssh-config) | (Re)write the local SSH config entry for the devbox. |
| [destroy](#inspect-ranges-destroy) | Terminate the devbox (its disk, including its GitHub token, is deleted). |

## inspect-ranges up

Create (or start) the devbox and bring it fully up to date.

#### Usage

``` text
inspect-ranges up [OPTIONS]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--instance-type` | text | c8i/m8i/r8i family (nested virt) or an x86 metal instance. | `m8i.8xlarge` |
| `--volume-size` | integer | Root volume size (GiB). | `500` |
| `--iops` | integer | gp3 IOPS. | `6000` |
| `--throughput` | integer | gp3 throughput (MiB/s). | `500` |
| `--idle-minutes` | integer | Stop after this many idle minutes. | `60` |
| `--backstop-hours` | integer range (between `0` and `24`) | CloudWatch stop after N hours \<2% CPU (0 = off). | `6` |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |

## inspect-ranges github-token

Store a GitHub token on the devbox (read from stdin), then clone the repo.

Use a fine-grained token limited to meridianlabs-ai/inspect_ranges. Reading it from stdin keeps it out of your shell history, the terminal, and process listings.

#### Usage

``` text
inspect-ranges github-token [OPTIONS]
```

#### Options

| Name     | Type    | Description                 | Default          |
|----------|---------|-----------------------------|------------------|
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |

## inspect-ranges start

Start the devbox and wait until it accepts connections.

#### Usage

``` text
inspect-ranges start [OPTIONS]
```

#### Options

| Name     | Type    | Description                 | Default          |
|----------|---------|-----------------------------|------------------|
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |

## inspect-ranges stop

Stop the devbox (the disk is kept).

#### Usage

``` text
inspect-ranges stop [OPTIONS]
```

#### Options

| Name     | Type    | Description                 | Default          |
|----------|---------|-----------------------------|------------------|
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |

## inspect-ranges status

Show the devbox’s state.

#### Usage

``` text
inspect-ranges status [OPTIONS]
```

#### Options

| Name     | Type    | Description                 | Default          |
|----------|---------|-----------------------------|------------------|
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |

## inspect-ranges ssh-config

(Re)write the local SSH config entry for the devbox.

#### Usage

``` text
inspect-ranges ssh-config [OPTIONS]
```

#### Options

| Name     | Type    | Description                 | Default          |
|----------|---------|-----------------------------|------------------|
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |

## inspect-ranges destroy

Terminate the devbox (its disk, including its GitHub token, is deleted).

#### Usage

``` text
inspect-ranges destroy [OPTIONS]
```

#### Options

| Name | Type | Description | Default |
|----|----|----|----|
| `--all` | boolean | Also delete the shared VPC and IAM role if unused. | `Sentinel.UNSET` |
| `--yes` | boolean | Don’t ask for confirmation. | `Sentinel.UNSET` |
| `--help` | boolean | Show this message and exit. | `Sentinel.UNSET` |
