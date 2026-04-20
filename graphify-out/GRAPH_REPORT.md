# Graph Report - .  (2026-04-20)

## Corpus Check
- Corpus is ~15,700 words - fits in a single context window. You may not need a graph.

## Summary
- 56 nodes · 57 edges · 15 communities detected
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 4 edges (avg confidence: 0.72)
- Token cost: 3,200 input · 1,900 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Core Deployment Library|Core Deployment Library]]
- [[_COMMUNITY_Service Deployment Orchestration|Service Deployment Orchestration]]
- [[_COMMUNITY_Service Definitions|Service Definitions]]
- [[_COMMUNITY_Network Services|Network Services]]
- [[_COMMUNITY_Communication Services|Communication Services]]
- [[_COMMUNITY_Config Generation|Config Generation]]
- [[_COMMUNITY_Remote Deployment|Remote Deployment]]
- [[_COMMUNITY_Certificate Management|Certificate Management]]
- [[_COMMUNITY_Test Documentation|Test Documentation]]
- [[_COMMUNITY_Lib Module|Lib Module]]
- [[_COMMUNITY_Test Library|Test Library]]
- [[_COMMUNITY_Jinja Tests|Jinja Tests]]
- [[_COMMUNITY_SOPS Tests|SOPS Tests]]
- [[_COMMUNITY_Remote Tests|Remote Tests]]
- [[_COMMUNITY_Cloudflare Tests|Cloudflare Tests]]

## God Nodes (most connected - your core abstractions)
1. `ServiceDeployer - Central deployment orchestration class` - 16 edges
2. `ServiceDeployer Library` - 16 edges
3. `ServiceDeployer class` - 7 edges
4. `ssh_run - SSH command execution` - 4 edges
5. `sing-box config generator` - 3 edges
6. `decrypt_sops - SOPS decryption function` - 3 edges
7. `Wildcard certificate management` - 3 edges
8. `router/generate.py` - 3 edges
9. `Jitsi Service - Video Conferencing` - 3 edges
10. `WireGuard Service - VPN Mesh` - 3 edges

## Surprising Connections (you probably didn't know these)
- `Traefik Service - Reverse Proxy` --semantically_similar_to--> `Sing-Box Service - Proxy Server`  [INFERRED] [semantically similar]
  traefik/deploy.py → sing-box/deploy.py
- `Jitsi Service - Video Conferencing` --semantically_similar_to--> `Element Call Service - LiveKit SFU`  [INFERRED] [semantically similar]
  jitsi/deploy.py → element-call/deploy.py
- `Coturn Service - TURN STUN Relay` --semantically_similar_to--> `WireGuard Service - VPN Mesh`  [INFERRED] [semantically similar]
  coturn/deploy.py → wireguard/deploy.py
- `Sing-Box Service - Proxy Server` --semantically_similar_to--> `WireGuard Service - VPN Mesh`  [INFERRED] [semantically similar]
  sing-box/deploy.py → wireguard/deploy.py
- `Synapse Matrix homeserver deployment` --calls--> `ServiceDeployer - Central deployment orchestration class`  [EXTRACTED]
  synapse/deploy.py → lib/deploy.py

## Hyperedges (group relationships)
- **Pod-based Services** — synapse_service, elementcall_service, nextcloud_service [INFERRED]
- **Native System Services** — coturn_service, wireguard_service, system_service, firewall_service [INFERRED]
- **Deployment Models** — router_service, singbox_service [INFERRED]

## Communities

### Community 0 - "Core Deployment Library"
Cohesion: 0.2
Nodes (11): CFKVUploader class, ServiceDeployer class, TestServiceDeployer, create_jinja_env function, create_uploader function, decrypt_sops function, element-call/deploy.py, firewall/deploy.py (+3 more)

### Community 1 - "Service Deployment Orchestration"
Cohesion: 0.18
Nodes (11): Backup scripts, Coturn TURN server, Element web + synapse admin deployment, Jitsi video conferencing, ServiceDeployer - Central deployment orchestration class, Prometheus + Grafana metrics stack, sing-box server deployment, sing-box relay deployment (+3 more)

### Community 2 - "Service Definitions"
Cohesion: 0.2
Nodes (10): TestDeployHelpers, Backup Service - Kopia Snapshots, Certificates Service - TLS Certificates, Element Service - Element Web, Firewall Service - Firewalld Zones, ServiceDeployer Library, Metrics Service - Prometheus Grafana, Nextcloud Service - Cloud Storage (+2 more)

### Community 3 - "Network Services"
Cohesion: 0.5
Nodes (4): Coturn Service - TURN STUN Relay, Sing-Box Service - Proxy Server, Traefik Service - Reverse Proxy, WireGuard Service - VPN Mesh

### Community 4 - "Communication Services"
Cohesion: 0.5
Nodes (4): Element Call Service - LiveKit SFU, Jitsi Service - Video Conferencing, infra - Infrastructure-as-Code Project, Router Service - OpenWrt Configs

### Community 5 - "Config Generation"
Cohesion: 0.67
Nodes (3): CFKVUploader - Cloudflare KV storage uploader, create_jinja_env - Jinja2 environment factory, sing-box config generator

### Community 6 - "Remote Deployment"
Cohesion: 0.67
Nodes (3): ssh_run - SSH command execution, Nextcloud self-hosted cloud, Synapse Matrix homeserver deployment

### Community 7 - "Certificate Management"
Cohesion: 1.0
Nodes (2): Wildcard certificate management, decrypt_sops - SOPS decryption function

### Community 8 - "Test Documentation"
Cohesion: 1.0
Nodes (2): Tests README - Test Framework Documentation, Test Library - Lib Tests

### Community 9 - "Lib Module"
Cohesion: 1.0
Nodes (0): 

### Community 10 - "Test Library"
Cohesion: 1.0
Nodes (1): tests/test_lib.py

### Community 11 - "Jinja Tests"
Cohesion: 1.0
Nodes (1): TestJinja

### Community 12 - "SOPS Tests"
Cohesion: 1.0
Nodes (1): TestSops

### Community 13 - "Remote Tests"
Cohesion: 1.0
Nodes (1): TestRemote

### Community 14 - "Cloudflare Tests"
Cohesion: 1.0
Nodes (1): TestCloudflare

## Knowledge Gaps
- **33 isolated node(s):** `sing-box server deployment`, `sing-box relay deployment`, `Traefik reverse proxy deployment`, `CFKVUploader - Cloudflare KV storage uploader`, `CFKVUploader class` (+28 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Certificate Management`** (2 nodes): `Wildcard certificate management`, `decrypt_sops - SOPS decryption function`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Test Documentation`** (2 nodes): `Tests README - Test Framework Documentation`, `Test Library - Lib Tests`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Lib Module`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Test Library`** (1 nodes): `tests/test_lib.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Jinja Tests`** (1 nodes): `TestJinja`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `SOPS Tests`** (1 nodes): `TestSops`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Remote Tests`** (1 nodes): `TestRemote`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cloudflare Tests`** (1 nodes): `TestCloudflare`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ServiceDeployer Library` connect `Service Definitions` to `Test Documentation`, `Network Services`, `Communication Services`?**
  _High betweenness centrality (0.108) - this node is a cross-community bridge._
- **Why does `ServiceDeployer - Central deployment orchestration class` connect `Service Deployment Orchestration` to `Config Generation`, `Remote Deployment`, `Certificate Management`?**
  _High betweenness centrality (0.093) - this node is a cross-community bridge._
- **What connects `sing-box server deployment`, `sing-box relay deployment`, `Traefik reverse proxy deployment` to the rest of the system?**
  _33 weakly-connected nodes found - possible documentation gaps or missing edges._