# infra

Infrastructure-as-code for a personal server stack and home network. Podman Quadlet configs, OpenWrt router configs, service configs and secrets — all templated, versioned and deployed over SSH or distributed via Cloudflare Workers KV.

## Stack

| Service | What |
|---|---|
| `system` | Base OS hardening: sshd, sysctl, systemd-networkd, maintenance timers (btrfs scrub, paccache, sysctl reapply) |
| `firewall` | Firewalld zones: public, wireguard, filter-closed, trusted — ports opened per-instance from secrets |
| `backup` | Kopia snapshots to S3 with btrfs atomic snapshots, systemd timer |
| `certs` | Centralized wildcard TLS certificates (Google ACME + Cloudflare DNS challenge via lego) |
| `traefik` | Reverse proxy, TLS termination |
| `synapse` | Matrix homeserver + PostgreSQL |
| `nextcloud` | Nextcloud + MariaDB + Valkey + Nginx + cron timer |
| `element` | Element Web + Synapse Admin |
| `metrics` | Prometheus + Node Exporter + Grafana |
| `jitsi` | Jitsi Meet video conferencing (prosody + jicofo + jvb + web) |
| `coturn` | TURN/STUN relay servers for Synapse and Jitsi (native, no container) |
| `wireguard` | WireGuard mesh + client tunnels (native, no container) |
| `sing-box` | Proxy server + client/router config generator with Cloudflare KV distribution |
| `router` | OpenWrt router configs: nftables tproxy, network, wireless, firewall, dhcp — distributed via KV |

## Structure

```text
infra/
├── secrets/
│   └── hosts.enc.yaml
├── lib/
│   ├── sops.py
│   ├── remote.py
│   ├── jinja.py
│   ├── deploy.py
│   └── cloudflare.py
├── system/
│   ├── deploy.py
│   ├── templates/
│   └── secrets/
├── firewall/
│   ├── deploy.py
│   ├── templates/
│   └── secrets/
├── backup/
│   ├── deploy.py
│   ├── templates/
│   └── secrets/
├── certs/
│   ├── deploy.py
│   ├── secrets/
│   └── .certstore/              ← gitignored, lego state + certs
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
├── jitsi/
│   ├── deploy.py
│   ├── templates/
│   └── secrets/
├── coturn/
│   ├── deploy.py
│   ├── templates/
│   └── secrets/
├── wireguard/
│   ├── deploy.py
│   ├── templates/
│   └── secrets/
├── sing-box/
│   ├── deploy.py              ← server deploy (render/diff/deploy)
│   ├── generate.py            ← client/router config generator + KV
│   ├── templates/
│   ├── secrets/
│   └── output/                ← gitignored
└── router/
    ├── generate.py            ← OpenWrt config generator + KV
    ├── templates/
    ├── secrets/
    └── output/                ← gitignored
```

## How it works

Each service has:

- `templates/` — Jinja2 templates for Quadlet units, configs or scripts
- `secrets/` — SOPS-encrypted YAML with passwords, domains, keys
- `deploy.py` — thin config that plugs into `lib/deploy.py`

### Server deploy flow

1. Decrypts secrets with SOPS
2. Resolves SSH target from `secrets/hosts.enc.yaml`
3. Renders Jinja2 templates
4. Syncs files to remote via rsync (checksum-based, idempotent)
5. Applies file ownership/permissions if specified (`owner`, `mode` in file config)
6. Restarts systemd units only if something changed

### Router/client config flow

`sing-box/generate.py` and `router/generate.py` use a different delivery model — configs are rendered locally, uploaded to Cloudflare Workers KV, and pulled by devices over HTTPS:

```
sops decrypt → jinja render → KV upload → device wget/curl
```

This avoids SSH to constrained devices (OpenWrt routers, phones) while keeping configs versioned and secrets encrypted at rest.

## File permissions

Files in the `files` list support an optional third element — a dict with `owner` and/or `mode`:

```python
'files': [
    ('config.yml.j2', '/opt/podman/myservice/config.yml'),                           # no perms
    ('wg0.conf.j2', '/etc/wireguard/wg0.conf', {'owner': 'root:root', 'mode': '600'}),   # both
    ('config.php.j2', '/opt/podman/nextcloud/config.php', {'owner': '33:33'}),            # owner only
    ('backup.sh.j2', '/root/scripts/backup.sh', {'owner': 'root:root', 'mode': '700'}),  # script
]
```

Applied after rsync via `chown`/`chmod` over SSH. Shown in `render` and `diff` output.

## Certificates

Wildcard certificate is managed centrally by `certs/deploy.py`:

1. Obtains `*.example.com` from Google ACME via Cloudflare DNS challenge using [lego](https://github.com/go-acme/lego)
2. Uses a local DoH proxy ([dnsproxy](https://github.com/AdguardTeam/dnsproxy)) to bypass DNS caching during propagation checks
3. Stores certificate locally in `.certstore/`
4. Distributes cert and key to `/etc/ssl/certs/` and `/etc/ssl/private/` on target servers via rsync
5. Triggers Traefik config reload via `touch` on dynamic config (no restart needed)

```bash
cd certs/
python deploy.py status                # check certificate expiry
python deploy.py issue                 # obtain/renew certificate
python deploy.py issue --force         # force re-issue regardless of expiry
python deploy.py distribute            # push to all target servers
python deploy.py distribute server1    # push to specific server
python deploy.py renew                 # issue if <30 days + distribute
```

Traefik reads certificates from `/etc/ssl/` via file provider with `watch: true` — updating the cert files and touching the dynamic config is enough, no container restart required.

The same wildcard certificate is used by coturn, and other native services — they read directly from `/etc/ssl/` on the host.

Auto-renewal via cron:

```
0 3 * * * cd /path/to/infra/certs && python deploy.py renew >> /var/log/cert-renew.log 2>&1
```

## Single-instance vs multi-instance

Services deployed to **one server** (synapse, nextcloud, element, jitsi, backup) have `host: server1` in their secrets.

Services deployed to **multiple servers** (traefik, metrics, coturn, wireguard, sing-box, system, firewall) have `instances:` with a `host:` reference per instance and support `--all`.

**Router** uses a different model — multiple routers defined under `routers:` in secrets, configs delivered via KV instead of SSH.

## Containerized vs native

Most services run as **Podman containers** managed via Quadlet units.

**coturn**, **wireguard**, **system**, and **firewall** run as **native systemd services** — they need host networking, direct access to `/etc/ssl/`, kernel-level interfaces (WireGuard), or tight integration with system sockets (coturn UDP relay). Only config files are deployed, no Quadlet units.

**Router** configs are native OpenWrt UCI/nftables files — no containers involved.

## Prerequisites

- Python 3.10+
- `pip install jinja2 pyyaml requests`
- [SOPS](https://github.com/getsops/sops) configured with your age key
- SSH access to target hosts
- rsync
- [lego](https://github.com/go-acme/lego) (for `certs/`)
- [dnsproxy](https://github.com/AdguardTeam/dnsproxy) (for `certs/`)

## Secrets

All secrets are SOPS-encrypted.

```bash
# SSH connection info (shared by all services)
sops secrets/hosts.enc.yaml

# Service secrets
sops certs/secrets/secrets.enc.yaml
sops traefik/secrets/secrets.enc.yaml
sops synapse/secrets/secrets.enc.yaml
sops nextcloud/secrets/secrets.enc.yaml
sops element/secrets/secrets.enc.yaml
sops metrics/secrets/secrets.enc.yaml
sops jitsi/secrets/secrets.enc.yaml
sops coturn/secrets/secrets.enc.yaml
sops wireguard/secrets/secrets.enc.yaml
sops sing-box/secrets/secrets.enc.yaml
sops system/secrets/secrets.enc.yaml
sops firewall/secrets/secrets.enc.yaml
sops backup/secrets/secrets.enc.yaml
sops router/secrets/secrets.enc.yaml
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

### certs secrets

```yaml
domain: example.com
acme_email: you@example.com
acme_eab_kid: "..."
acme_eab_hmac: "..."
cf_api_token: "..."

targets:
  - host: server1
    post_deploy: "touch /opt/podman/traefik/settings/dynamic/dynamic_tls.yml"
  - host: server2
    post_deploy: "touch /opt/podman/traefik/settings/dynamic/dynamic_tls.yml"
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
  cert_domain: example.com
  cloudflare_ips:
    - ...

instances:
  server1:
    host: server1
    domain: metrics1.example.com
  server2:
    host: server2
    domain: metrics2.example.com
```

### system secrets

```yaml
common:
  ssh_port: 2222
  ssh_allowed_users:
    - user_A
    - user_B
  ssh_otp_users:
    - user_A
  journal_max_use: 200M
  network_stack: dual

instances:
  instance1:
    host: server1
    network_stack: dual
  instance2:
    host: server2
    network_stack: dual
```

### firewall secrets

```yaml
common:
  ssh_port: 2222
  wg_port: 51453
  trusted_ips:
    - 10.0.0.0/8
    - ...

instances:
  instance1:
    host: server1
    filter_zone: true
    ssh_on_public: true
    wireguard: true
    wg_endpoint: true
    web: true
    turn: true
  instance2:
    host: server2
    filter_zone: true
    ssh_on_public: true
    wireguard: true
    wg_endpoint: true
    web: true
    turn: true
```

### backup secrets

```yaml
host: server1

backup:
  hostname: vps1
  kopia_password: "..."
  schedule: "*-*-* 04:00:00"
  repositories:
    - name: s3-backup
      bucket: my-bucket
      prefix: vps1
      endpoint: s3.example.com
      region: us-east-1
      access_key: "..."
      secret_key: "..."
```

### coturn secrets

```yaml
common:
  cert_domain: example.com

instances:
  synapse-turn:
    host: server1
    realm: matrix.example.com
    external_ip: "203.0.113.10"
    listening_ip: "203.0.113.10"
    static_auth_secret: "..."
    fingerprint: true
    user_quota: 100
    total_quota: 1200
  jitsi-turn:
    host: server2
    realm: meet.example.com
    external_ip: "203.0.113.20"
    listening_ip: "203.0.113.20"
    static_auth_secret: "..."
    keep_address_family: true
    no_loopback_peers: true
    dh2066: true
```

### wireguard secrets

```yaml
common:
  listen_port: 51453

instances:
  server1:
    host: server1
    address: "...::1/128"
    private_key: "..."
    peers:
      - name: Vps2
        public_key: "..."
        allowed_ips: ["...::2/128", "...::5/128", "...::6/128"]
        endpoint: "1.2.3.4:51453"
        keepalive: 20
      - name: Phone
        public_key: "..."
        allowed_ips: ["...::3/128"]
      - name: Pc
        public_key: "..."
        allowed_ips: ["...::4/128"]
  server2:
    host: server2
    address: "...::2/128"
    private_key: "..."
    peers:
      - name: Vps1
        public_key: "..."
        allowed_ips: ["...::1/128", "...::3/128", "...::4/128"]
        endpoint: "4.5.6.7:51453"
        keepalive: 20
      - name: Phone
        public_key: "..."
        allowed_ips: ["...::6/128"]
      - name: Pc
        public_key: "..."
        allowed_ips: ["...::5/128"]
```

### router secrets

```yaml
cloudflare:
  account_id: "..."
  api_token: "..."
  kv_namespace_id: "..."
  worker_domain: "..."

shared:
  timezone: "UTC-2"
  zonename: "Afrika/Juba"
  wifi:
    country: "PA"
    main:
      ssid: "main"
      key: "..."
      mobility_domain: "4f11"
    guest:
      ssid: "guest"
      key: "..."
  sing_box:
    binary: "/root/sing-box"
    config_dir: "/etc/sing-box"
    files:
      - main.json
      - sing-box_anytls.json
      - sing-box_vless_grpc.json
      - sing-box_vless_ws.json
      - sing-box_vless_httpupgrade.json

routers:
  router-1:
    hostname: "OpenWrt"
    token: "..."
    sing_box_token: "..."
    network:
      wan_mac: "..."
      lan_ipaddr: "192.168.x.1"
      ...
    nftables:
      local_v6: [...]
    dhcp:
      router_ipv4: "..."
      router_ula: "..."
      static_hosts: [...]
    radios: [...]
    leds: [...]
```

## Usage

### Single-instance (synapse, nextcloud, element, jitsi, backup)

```bash
cd synapse/
python deploy.py render
python deploy.py diff
python deploy.py deploy
python deploy.py deploy --no-restart
```

### Multi-instance (traefik, metrics, coturn, wireguard, sing-box, system, firewall)

```bash
cd firewall/
python deploy.py list
python deploy.py render instance1
python deploy.py diff instance1
python deploy.py deploy instance1
python deploy.py deploy instance1 instance2   # multiple instances
python deploy.py diff --all
python deploy.py deploy --all
python deploy.py deploy --all --no-restart
```

### sing-box client/router configs

`sing-box/generate.py` generates client and router configs locally and optionally uploads them to Cloudflare Workers KV for remote distribution via URL.

```bash
cd sing-box/

# Generate configs locally
python generate.py                             # all clients + routers
python generate.py --target clients            # only clients
python generate.py --target router             # only routers

# Generate + upload to Cloudflare KV
python generate.py --upload

# Token management
python generate.py --gen-token                 # generate 1 token
python generate.py --gen-token -n 5            # generate 5 tokens
python generate.py --gen-token --user bob      # generate token for user 'bob'

# KV management
python generate.py --list-kv                   # list all keys in KV
python generate.py --revoke phone-m            # delete phone-m configs from KV
python generate.py --purge-kv                  # delete everything from KV
```

Add new user:

1. `python generate.py --gen-token --user new-phone`
2. `sops secrets/secrets.enc.yaml` — add user block with token
3. `python generate.py --upload`
4. Send URL from `output/urls.md`

### Router configs

`router/generate.py` generates OpenWrt configs (nftables, network, wireless, firewall, dhcp, system, init scripts) and uploads to KV. Routers pull configs via `update.sh`.

```bash
cd router/

python generate.py list                        # list routers
python generate.py render router-1             # print rendered configs
python generate.py generate router-1           # generate to output/
python generate.py generate --upload router-1  # generate + upload to KV
python generate.py generate --upload --all     # all routers
```

On the router:

```bash
sh /root/update.sh                             # pull configs from KV
reboot                                         # apply
```

## What gets deployed where

Quadlet units go to `/etc/containers/systemd/` on remote.

Service configs go to `/opt/podman/<service>/` and are mounted into containers via Quadlet `Volume=`.

Secrets (signing keys, API tokens) are written via SSH with `chmod 600`.

Certificates go to `/etc/ssl/certs/` and `/etc/ssl/private/` — mounted read-only into containers that need them, read directly by native services (coturn).

Native service configs:
- system → `/etc/ssh/sshd_config`, `/etc/sysctl.d/`, `/etc/systemd/network/`, `/etc/systemd/journald.conf`, systemd timers
- firewall → `/etc/firewalld/zones/`
- backup → `/root/scripts/backup.sh`, systemd service + timer
- coturn → `/etc/turnserver/turnserver.conf`
- wireguard → `/etc/wireguard/wg0.conf`

Router configs (via KV):
- nftables → `/etc/nftables/nft-ipv6`
- network, wireless, firewall, dhcp, system → `/etc/config/`
- sing-box init → `/etc/init.d/sing-box_my`
- ip rules → `/etc/rc.local`

## Remote server layout

```text
/etc/ssh/
└── sshd_config

/etc/sysctl.d/
├── 10-default.conf
└── 11-overcommit_memory.conf

/etc/systemd/
├── network/10-default.network
├── journald.conf
└── system/
    ├── 10-paccache_user.timer
    ├── 10-paccache_user.service
    ├── 10-btrfs_scrub.timer
    ├── 10-btrfs_scrub.service
    ├── 10-sysctl_user.timer
    ├── 10-sysctl_user.service
    ├── backup.service
    ├── backup.timer
    ├── nextcloud-cron_podman.service
    └── nextcloud-cron_podman.timer

/etc/firewalld/zones/
├── public.xml
├── filter-closed.xml
├── wireguard.xml
└── trusted.xml

/etc/ssl/
├── certs/example.com.crt
└── private/example.com.key

/etc/turnserver/
└── turnserver.conf

/etc/wireguard/
└── wg0.conf

/root/scripts/
└── backup.sh

/opt/podman/
├── traefik/
│   ├── settings/traefik.yml
│   ├── settings/dynamic/dynamic1.yml
│   ├── settings/dynamic/dynamic_tls.yml
│   └── logs/
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
├── metrics/
│   └── prometheus/prometheus.yml
├── jitsi/
│   ├── jitsi.env
│   └── jitsi-meet-cfg/
│       ├── prosody/
│       ├── jicofo/
│       ├── jvb/
│       ├── web/
│       └── transcripts/
└── sing-box/
    └── sing-box_settings/
        ├── main.json
        ├── inbounds.json
        ├── ruleset.json
        └── warp.json
```

## Router layout

```text
/etc/config/
├── network
├── wireless
├── firewall
├── dhcp
└── system

/etc/nftables/
└── nft-ipv6

/etc/init.d/
└── sing-box_my

/etc/rc.local

/etc/sing-box/
├── main.json
├── sing-box_anytls.json
├── sing-box_vless_grpc.json
├── sing-box_vless_ws.json
└── sing-box_vless_httpupgrade.json

/root/
├── sing-box
└── update.sh
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
        ('secret.conf.j2', '/etc/myservice/secret.conf', {'owner': 'root:root', 'mode': '600'}),
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

## Pod vs shared network

Some services use a Quadlet **Pod** (shared network namespace, containers talk via `localhost`): synapse + postgresql, nextcloud + mariadb + valkey + nginx.

Jitsi uses a **Quadlet Network** instead — containers need DNS-based discovery (`NetworkAlias=xmpp.meet.jitsi` for prosody), which doesn't work inside a pod since pods share a single network namespace and bypass container DNS.
