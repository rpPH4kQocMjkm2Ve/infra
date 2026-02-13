#!/usr/bin/env python3
"""
Centralized wildcard certificate management.

Obtains a wildcard cert from Google ACME via Cloudflare DNS challenge
using lego, stores locally, distributes to /etc/ssl/ on remote servers.

Usage:
    python deploy.py status
    python deploy.py issue [--force]
    python deploy.py distribute [HOST]
    python deploy.py renew
"""
import os
import sys
import subprocess
import time
import signal
import shutil
import argparse
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.sops import decrypt_sops
from lib.deploy import load_hosts, resolve_target
from lib.remote import ssh_run, rsync_file

BASE = Path(__file__).parent
CERT_STORE = BASE / ".certstore"
SECRETS_FILE = BASE / "secrets" / "secrets.enc.yaml"

RENEW_DAYS = 30
DOH_PROXY_PORT = 5053


def start_doh_proxy() -> subprocess.Popen:
    """Start a local DNS proxy with DoH upstream for lego."""
    proc = subprocess.Popen(
        ["dnsproxy", "-l", "127.0.0.1", "-p", str(DOH_PROXY_PORT),
         "-u", "https://1.1.1.1/dns-query"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(1)
    return proc


def stop_doh_proxy(proc: subprocess.Popen):
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=5)


def cert_paths(domain: str) -> tuple[Path, Path]:
    """Return local lego output paths for a wildcard domain."""
    certs_dir = CERT_STORE / "lego" / "certificates"
    return certs_dir / f"_.{domain}.crt", certs_dir / f"_.{domain}.key"


def read_expiry(cert_file: Path) -> datetime | None:
    """Read expiry date from a PEM certificate via openssl."""
    r = subprocess.run(
        ["openssl", "x509", "-enddate", "-noout", "-in", str(cert_file)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None
    date_str = r.stdout.strip().split("=", 1)[1]
    return datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z").replace(
        tzinfo=timezone.utc
    )


def issue(secrets: dict, force: bool = False) -> bool:
    """Obtain or renew the wildcard certificate using lego."""
    if not shutil.which("lego"):
        print("ERROR: lego not found in PATH", file=sys.stderr)
        print("  https://github.com/go-acme/lego#installation", file=sys.stderr)
        sys.exit(1)

    domain = secrets["domain"]
    crt, _ = cert_paths(domain)
    exists = crt.exists()

    if exists and not force:
        expiry = read_expiry(crt)
        if expiry:
            days = (expiry - datetime.now(timezone.utc)).days
            if days > RENEW_DAYS:
                print(f"  valid for {days} days, skipping (--force to override)")
                return False

    CERT_STORE.mkdir(parents=True, exist_ok=True)

    proxy = start_doh_proxy()
    try:
        cmd = [
            "lego",
            "--email", secrets["acme_email"],
            "--server", "https://dv.acme-v02.api.pki.goog/directory",
            "--eab",
            "--kid", secrets["acme_eab_kid"],
            "--hmac", secrets["acme_eab_hmac"],
            "--dns", "cloudflare",
            "--dns.propagation-disable-ans",
            "--dns.resolvers", f"127.0.0.1:{DOH_PROXY_PORT}",
            "--domains", f"*.{domain}",
            "--domains", domain,
            "--path", str(CERT_STORE / "lego"),
            "--accept-tos",
        ]

        if exists:
            cmd.extend(["renew", "--days", "9999" if force else str(RENEW_DAYS)])
        else:
            cmd.append("run")

        env = {
            **os.environ,
            "CLOUDFLARE_DNS_API_TOKEN": secrets["cf_api_token"],
            "CLOUDFLARE_PROPAGATION_TIMEOUT": "15",
            "CLOUDFLARE_POLLING_INTERVAL": "5",
        }

        print(f"  requesting *.{domain} ...")
        r = subprocess.run(cmd, env=env)
    finally:
        stop_doh_proxy(proxy)

    if r.returncode != 0:
        print("ERROR: lego failed", file=sys.stderr)
        sys.exit(1)

    if not crt.exists():
        print("ERROR: certificate not found after lego run", file=sys.stderr)
        sys.exit(1)

    print(f"  \033[0;32m✓\033[0m certificate ready")
    return True


def distribute(secrets: dict, hosts: dict, only_host: str = None):
    """Push certificate and key to target servers at /etc/ssl/."""
    domain = secrets["domain"]
    crt, key = cert_paths(domain)

    if not crt.exists() or not key.exists():
        print("ERROR: no certificate in store, run 'issue' first", file=sys.stderr)
        sys.exit(1)

    remote_crt = f"/etc/ssl/certs/{domain}.crt"
    remote_key = f"/etc/ssl/private/{domain}.key"

    targets = secrets["targets"]
    if only_host:
        targets = [t for t in targets if t["host"] == only_host]
        if not targets:
            avail = ", ".join(t["host"] for t in secrets["targets"])
            print(f"ERROR: '{only_host}' not in targets ({avail})", file=sys.stderr)
            sys.exit(1)

    for t in targets:
        host_ref = t["host"]
        target, port = resolve_target(hosts, host_ref)
        print(f"\n\033[1;36m── {host_ref} ({target}) ──\033[0m")

        ssh_run(target, "mkdir -p /etc/ssl/certs /etc/ssl/private", port)

        changed = False

        if rsync_file(crt, target, remote_crt, port):
            print(f"  \033[1;33m→\033[0m {remote_crt} updated")
            changed = True
        else:
            print(f"  \033[0;32m✓\033[0m {remote_crt} unchanged")

        if rsync_file(key, target, remote_key, port):
            print(f"  \033[1;33m→\033[0m {remote_key} updated")
            changed = True
        else:
            print(f"  \033[0;32m✓\033[0m {remote_key} unchanged")

        ssh_run(target, f"chmod 644 {remote_crt} && chmod 600 {remote_key}", port)

        if changed and "post_deploy" in t:
            ssh_run(target, t["post_deploy"], port)
            print(f"  \033[0;32m✓\033[0m post-deploy done")
        elif not changed:
            print(f"  \033[0;32m✓\033[0m no changes")


def status(secrets: dict):
    """Print certificate status."""
    domain = secrets["domain"]
    crt, _ = cert_paths(domain)

    print(f"\n  domains:  *.{domain}, {domain}")

    if crt.exists():
        expiry = read_expiry(crt)
        if expiry:
            days = (expiry - datetime.now(timezone.utc)).days
            icon = "⚠️ " if days < RENEW_DAYS else "✅"
            print(f"  status:   {icon} {days} days left ({expiry:%Y-%m-%d %H:%M} UTC)")
        else:
            print("  status:   ❌ unreadable")
    else:
        print("  status:   ❌ not issued")

    print(f"  targets:  {', '.join(t['host'] for t in secrets['targets'])}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Wildcard certificate management")
    parser.add_argument("command", choices=["status", "issue", "distribute", "renew"])
    parser.add_argument("host", nargs="?", help="target host (for distribute)")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    secrets = decrypt_sops(SECRETS_FILE)
    hosts = load_hosts()

    if args.command == "status":
        status(secrets)
    elif args.command == "issue":
        issue(secrets, force=args.force)
    elif args.command == "distribute":
        distribute(secrets, hosts, only_host=args.host)
    elif args.command == "renew":
        issue(secrets)
        distribute(secrets, hosts)


if __name__ == "__main__":
    main()
