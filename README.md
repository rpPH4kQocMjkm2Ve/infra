# infra

Infrastructure-as-code for personal server stack. Podman Quadlet configs, service configs and secrets — all templated, versioned, and deployed over SSH.

## Stack

| Service | What |
|---|---|
| `traefik` | Reverse proxy, TLS termination (Google ACME + Cloudflare DNS) |
| `synapse` | Matrix homeserver + PostgreSQL |
| `nextcloud` | Nextcloud + MariaDB + Valkey + Nginx |
| `element` | Element Web + Synapse Admin |
| `metrics` | Prometheus + Node Exporter + Grafana |
| `sing-box` | Proxy server (templates only, generator lives in a separate repo) |

## Structure

```text
infra/
├── secrets/
│   └── hosts.enc.yaml
├── lib/
│   ├── sops.py
│   ├── remote.py
│   ├── jinja.py
│   └── deploy.py
├── traefik/
│   ├── deploy.py
│   ├── templates/
│   └── secrets/
├── synapse/
│   ├── deploy.py
│   ├── templates/
│   └── secrets/
├── nextcloud/
│   ├── deploy.py
│   ├── templates/
│   └── secrets/
├── element/
│   ├── deploy.py
│   ├── templates/
│   └── secrets/
├── metrics/
│   ├── deploy.py
│   ├── templates/
│   └── secrets/
└── sing-box/
    ├── templates/
    └── secrets/
```

## How it works

Each service has:

- `templates/` — Jinja2 templates for Quadlet units and service configs
- `secrets/` — SOPS-encrypted YAML with passwords, domains, keys
- `deploy.py` — thin config that plugs into `lib/deploy.py`

Deploy flow:

1. Decrypts secrets with SOPS
2. Resolves SSH target from `secrets/hosts.enc.yaml`
3. Renders Jinja2 templates
4. Syncs files to remote via rsync (checksum-based, idempotent)
5. Restarts systemd units only if something changed

## Single-instance vs multi-instance

Services deployed to **one server** (synapse, nextcloud, element) have `host: server1` in their secrets.

Services deployed to **multiple servers** (traefik, metrics) have `instances:` with a `host:` reference per instance and support `--all`.

## Prerequisites

- Python 3.10+
- `pip install jinja2 pyyaml`
- [SOPS](https://github.com/getsops/sops) configured with your age key
- SSH access to target hosts
- rsync

## Secrets

All secrets are SOPS-encrypted.

```bash
# SSH connection info (shared by all services)
sops secrets/hosts.enc.yaml

# Service secrets
sops traefik/secrets/secrets.enc.yaml
sops synapse/secrets/secrets.enc.yaml
sops nextcloud/secrets/secrets.enc.yaml
sops element/secrets/secrets.enc.yaml
sops metrics/secrets/secrets.enc.yaml
```

### hosts.enc.yaml

Central SSH config referenced by all services:

```yaml
server1:
  address: server1.example.com
  ssh_port: 2222
  ssh_user: user_A
server2:
  address: server2.example.com
  ssh_port: 2222
  ssh_user: user_A
```

### Single-instance secrets

```yaml
host: server1

synapse:
  server_name: matrix.example.com
  postgres_password: "..."
```

### Multi-instance secrets

```yaml
common:
  ech_domain: ech.example.com

instances:
  server1:
    host: server1
    domain: metrics1.example.com
  server2:
    host: server2
    domain: metrics2.example.com
```

## Usage

### Single-instance (synapse, nextcloud, element)

```bash
cd synapse/
python deploy.py render
python deploy.py diff
python deploy.py deploy
python deploy.py deploy --no-restart
```

### Multi-instance (traefik, metrics)

```bash
cd traefik/
python deploy.py list
python deploy.py render instance1
python deploy.py diff instance1
python deploy.py deploy instance1
python deploy.py diff --all
python deploy.py deploy --all
python deploy.py deploy --all --no-restart
```

## What gets deployed where

Quadlet units go to `/etc/containers/systemd/` on remote.

Service configs go to `/opt/podman/<service>/` and are mounted into containers via Quadlet `Volume=`.

Secrets (signing keys, API tokens) are written via SSH with `chmod 600`.

## Remote server layout

```text
/opt/podman/
├── traefik/
│   ├── settings/traefik.yml
│   ├── settings/dynamic/dynamic1.yml
│   ├── google_acme/
│   ├── logs/
│   ├── cf_email
│   └── cf_token
├── synapse/
│   ├── data/homeserver.yaml
│   ├── data/*.signing.key
│   ├── data/*.log.config
│   ├── data/media_store/
│   └── db/
├── nextcloud/
│   ├── nextcloud/config/config.php
│   ├── nginx.conf
│   ├── db/
│   └── log/
├── element_synapse_admin/
│   ├── element_config.json
│   └── synapse_config.json
└── metrics/
    └── prometheus/prometheus.yml
```

## Adding a new service

1. Create `<service>/templates/`, `<service>/secrets/`, `<service>/deploy.py`
2. Write Jinja2 templates (replace hardcoded secrets with variables)
3. Create SOPS-encrypted secrets
4. Write `deploy.py`:

```python
#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.deploy import ServiceDeployer

BASE = Path(__file__).parent

deployer = ServiceDeployer({
    'templates_dir': BASE / 'templates',
    'secrets_file': BASE / 'secrets' / 'secrets.enc.yaml',
    'files': [
        ('myservice.container.j2', '/etc/containers/systemd/myservice.container'),
        ('config.yml.j2', '/opt/podman/myservice/config.yml'),
    ],
    'setup_dirs': ['/opt/podman/myservice'],
    'restart_cmd': 'systemctl daemon-reload && systemctl restart myservice',
})

if __name__ == '__main__':
    deployer.run_cli()
```

5. Test: `render` then `diff` then `deploy`

## Traefik middleware notes

Two IP allowlist middlewares in `dynamic1.yml`:

**`blacklist`** — for services behind Cloudflare. Uses `ipStrategy.excludedIPs` to strip CF proxy IPs and check real client IP.

**`blacklist-direct`** — for services accessed directly (no CF). Same allowlist, no `ipStrategy`.

Controlled by `behind_cf` flag in service secrets.
