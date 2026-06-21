# Design and Implementation of a Private Cloud Infrastructure for University Research Environment

> **Al-Balqa Applied University — Faculty of Engineering Technology (FET)**
> Graduation Project | June 2026

[![Python](https://img.shields.io/badge/Python-3.x-blue?logo=python)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-REST%20API-black?logo=flask)](https://flask.palletsprojects.com)
[![Proxmox](https://img.shields.io/badge/Proxmox-VE%209.1-orange)](https://proxmox.com)
[![Kubernetes](https://img.shields.io/badge/Infrastructure-IaaS-green)]()
[![License](https://img.shields.io/badge/License-Academic-lightgrey)]()

---

## Overview

A full-stack, production-grade **private cloud IaaS platform** built from bare metal for Al-Balqa Applied University's Faculty of Engineering Technology. The system eliminates manual VM provisioning (previously taking days) by delivering a self-service portal that provisions virtual machines in **under 3 minutes** — with full VLAN isolation, Zero-Trust security, and real-time infrastructure monitoring.

This repository contains the source code for the **Flask-based self-service web portal** — the user-facing component of the platform.

---

## Architecture

![System Architecture](docs/architecture/system-architecture.png)

The platform is built on a single bare-metal server (Lenovo Legion 5 — AMD Ryzen 7 5800H, 32GB RAM, 1TB NVMe) running **Proxmox VE 9.1** with KVM hypervisor technology, logically partitioned into **7 IEEE 802.1Q VLAN segments**:

| VLAN | ID | Purpose |
|------|----|---------|
| Management | 99 | Admin-only control plane |
| Computer Engineering | 10 | Departmental tenant |
| Mechatronics Engineering | 20 | Departmental tenant |
| Mechanical Engineering | 30 | Departmental tenant |
| Electrical Engineering | 40 | Departmental tenant |
| Monitoring | 50 | Prometheus & Grafana stack |
| Web Portal | 80 | Self-service portal (LXC) |

---

## Web Portal — Key Features

The Flask portal communicates directly with the **Proxmox REST API** and **OpenLDAP** to provide a complete VM lifecycle management interface.

### For Researchers (Users)
- Authenticate via university LDAP credentials
- Submit VM provisioning requests (OS, resources)
- Start / Stop / Delete owned VMs
- View real-time VM status enriched from Proxmox

### For IT Administrators
- Approve or reject VM requests (triggers automated 9-step provisioning pipeline)
- Manage LDAP user accounts (create, reset password, enable/disable, delete)
- View all VMs and requests across all tenants

---

## REST API Endpoints

All endpoints are prefixed with `/api/`. Session state is maintained server-side via Flask's signed cookie mechanism.

| Method | Endpoint | Access | Description |
|--------|----------|--------|-------------|
| POST | `/api/login` | Public | Authenticate via LDAP, create session |
| POST | `/api/logout` | Auth | Clear server-side session |
| GET | `/api/me` | Auth | Return current session user profile |
| POST | `/api/change-password` | Auth | Forced first-login password change via LDAP |
| GET | `/api/vms` | Auth | User: own VMs. Admin: all VMs with live Proxmox status |
| POST | `/api/vms/<vmid>/start` | Auth | Start VM with ownership enforcement |
| POST | `/api/vms/<vmid>/stop` | Auth | Stop VM with ownership enforcement |
| DELETE | `/api/vms/<vmid>` | Auth | Stop + delete VM from Proxmox and SQLite |
| GET | `/api/requests` | Auth | User: own requests. Admin: all requests |
| POST | `/api/requests` | Auth | Submit new VM request |
| PUT | `/api/requests/<id>/approve` | Admin | Approve request → triggers full VM provisioning |
| PUT | `/api/requests/<id>/reject` | Admin | Reject request with reason |
| GET | `/api/users` | Admin | List all LDAP users with active status and VM count |
| POST | `/api/users` | Admin | Create new LDAP user |
| PUT | `/api/users/<uid>/password` | Admin | Reset user password in LDAP |
| PUT | `/api/users/<uid>/toggle` | Admin | Enable / Disable user account |
| DELETE | `/api/users/<uid>` | Admin | Remove user from LDAP and SQLite |

---

## Security Model

- **Zero-Trust perimeter** — Sophos XG Firewall with SSL VPN mandatory for all remote access
- **RBAC enforcement** — Two-tier decorator model (`@login_required`, `@admin_required`) on every API request; role sourced from OpenLDAP `employeeType` attribute at login
- **Resource-level isolation** — `_can_access_vm()` helper prevents horizontal privilege escalation between researcher accounts
- **Account-level control** — `_is_active()` helper allows disabling portal access without deleting LDAP accounts or VMs
- **Inter-VLAN blocking** — Sophos firewall rule `Block_InterVLAN_Traffic` enforces strict tenant isolation

---

## VM Provisioning Pipeline

When an admin approves a request, `proxmox_helper.provision_vm()` executes a fully automated **9-step pipeline** via the Proxmox REST API — zero manual hypervisor interaction:

1. Clone VM template (Ubuntu / Fedora / Kali / Windows 10)
2. Assign unique VMID
3. Configure vCPU and RAM
4. Attach to correct departmental VLAN bridge
5. Apply Cloudbase-Init / cloud-init for first-boot customization
6. Register VM in SQLite with owner UID
7. Start VM
8. Update request status to `approved`
9. Return VM details to frontend

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Hypervisor | Proxmox VE 9.1 (KVM) |
| Web Portal | Python 3 / Flask |
| Identity | OpenLDAP (RBAC via `employeeType`) |
| Database | SQLite (via Python `sqlite3`) |
| Networking | IEEE 802.1Q VLANs, Linux Bridge (OVS) |
| Security | Sophos XG Firewall, SSL VPN |
| Monitoring | Prometheus + Grafana + Telegram Alerts |
| VM Templates | Ubuntu 22.04, Fedora 38, Kali Linux, Windows 10 Pro |

---

## Project Structure

```
BAU_cloud_web_portal/
├── README.md
├── portal/
│   ├── app.py                  # Flask application entry point
│   ├── proxmox_helper.py       # Proxmox REST API integration & VM provisioning
│   ├── ldap_helper.py          # OpenLDAP authentication and user management
│   ├── database.py             # SQLite schema and query helpers
│   ├── config.py               # Environment configuration
│   ├── requirements.txt
│   ├── setup.sh
│   ├── static/
│   └── templates/
│       └── dashboard.html
└── docs/
    └── architecture/
        └── system-architecture.png
---

 Al-Balqa Applied University, FET

---

## Keywords

`Private Cloud` `IaaS` `Proxmox VE` `KVM` `Flask` `OpenLDAP` `RBAC` `SSL VPN` `Zero-Trust` `VLAN` `Prometheus` `Grafana` `Sophos XG` `DevOps` `Infrastructure Automation`
