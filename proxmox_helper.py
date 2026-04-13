"""
proxmox_helper.py
Proxmox VE REST API integration for the FET Cloud Portal.

Flow when a request is approved:
  1. Admin clicks "Approve" → Flask calls provision_vm()
  2. provision_vm() clones the OS template on Proxmox
  3. Configures CPU / RAM / disk / VLAN tag
  4. Starts the VM
  5. Records the VM in SQLite (owner, vlan, dept metadata)

For get_vms_*:
  - Metadata (owner, vlan, dept) comes from SQLite
  - Live status/IP comes from Proxmox API (merged in _enrich_vm)
"""

import secrets
import string
import requests
import urllib3
from config import Config
from database import get_db

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_BASE    = f'https://{Config.PROXMOX_HOST}:{Config.PROXMOX_PORT}/api2/json'
_ticket  = None
_csrf    = None
_node    = None   # resolved once at runtime — avoids DNS lookups on 'pve'


# ── Auth ──────────────────────────────────────────────────────────────────────

def _auth():
    global _ticket, _csrf
    try:
        r = requests.post(
            f'{_BASE}/access/ticket',
            data={'username': Config.PROXMOX_USER, 'password': Config.PROXMOX_PASSWORD},
            verify=Config.PROXMOX_VERIFY_SSL,
            timeout=10,
        )
        if r.ok:
            data    = r.json()['data']
            _ticket = data['ticket']
            _csrf   = data['CSRFPreventionToken']
            return True
        print(f"[PVE] auth failed: {r.text}")
        return False
    except Exception as e:
        print(f"[PVE] auth error: {e}")
        return False


def _session():
    if not _ticket:
        _auth()
    s = requests.Session()
    s.cookies.set('PVEAuthCookie', _ticket or '')
    s.headers.update({'CSRFPreventionToken': _csrf or ''})
    s.verify = Config.PROXMOX_VERIFY_SSL
    return s


def _req(method: str, path: str, **kwargs):
    """Make an authenticated request; re-auth once on 401."""
    s = _session()
    r = getattr(s, method)(f'{_BASE}{path}', timeout=15, **kwargs)
    if r.status_code == 401:
        _auth()
        s = _session()
        r = getattr(s, method)(f'{_BASE}{path}', timeout=15, **kwargs)
    return r


def get_node() -> str:
    """
    Return the Proxmox node name.

    Priority:
      1. Explicit env var  PROXMOX_NODE=pve
      2. Auto-discovered via GET /nodes  (uses the IP, no DNS needed)
    The result is cached for the lifetime of the process.
    """
    global _node
    if _node:
        return _node
    if Config.PROXMOX_NODE:          # explicitly set — trust it
        _node = Config.PROXMOX_NODE
        return _node
    # Auto-discover: ask Proxmox which nodes exist
    r = _req('get', '/nodes')
    if r.ok:
        nodes = r.json().get('data', [])
        if nodes:
            _node = nodes[0]['node']   # single-node setup → first entry
            print(f"[PVE] auto-discovered node name: '{_node}'")
            return _node
    raise RuntimeError(
        "Cannot determine Proxmox node name. "
        "Set PROXMOX_NODE in /opt/cloud-portal/.env"
    )


# ── Credential generator ──────────────────────────────────────────────────────

def _generate_password(length: int = 16) -> str:
    """Generate a strong random password for Cloud-Init."""
    alphabet = string.ascii_letters + string.digits + '!@#$%^&*()'
    while True:
        pw = ''.join(secrets.choice(alphabet) for _ in range(length))
        # Ensure complexity: upper, lower, digit, special
        if (any(c.isupper() for c in pw) and
                any(c.islower() for c in pw) and
                any(c.isdigit() for c in pw)):
            return pw


# ── VM listing ────────────────────────────────────────────────────────────────

def get_vms_for_user(owner_uid: str) -> list:
    """Return VMs owned by a specific Dr., enriched with live Proxmox status."""
    db   = get_db()
    rows = db.execute('SELECT * FROM vms WHERE owner_uid = ?', (owner_uid,)).fetchall()
    db.close()
    return [_enrich_vm(dict(row)) for row in rows]


def get_all_vms() -> list:
    """Return all VMs (admin view), enriched with live status."""
    db   = get_db()
    rows = db.execute('SELECT * FROM vms').fetchall()
    db.close()
    return [_enrich_vm(dict(row)) for row in rows]


def _enrich_vm(vm: dict) -> dict:
    """
    Pull live status and IP from Proxmox and merge into the SQLite record.
    Falls back gracefully if Proxmox is unreachable.
    """
    vmid = vm.get('proxmox_vmid')
    if not vmid:
        return vm
    try:
        node = get_node()   # ← uses IP-based discovery, never DNS
        r    = _req('get', f'/nodes/{node}/qemu/{vmid}/status/current')
        if r.ok:
            pve_status = r.json().get('data', {}).get('qmpstatus', '')
            if pve_status:
                vm['status'] = pve_status

        # Try QEMU guest agent for IP
        ag = _req('get', f'/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces')
        if ag.ok:
            ifaces = ag.json().get('data', {}).get('result', [])
            for iface in ifaces:
                if iface.get('name', '').lower() == 'lo':
                    continue
                for addr in iface.get('ip-addresses', []):
                    if addr.get('ip-address-type') == 'ipv4':
                        ip = addr['ip-address']
                        if not ip.startswith('127.'):
                            vm['ip_address'] = ip
                            db = get_db()
                            db.execute(
                                'UPDATE vms SET ip_address=? WHERE proxmox_vmid=?',
                                (ip, vmid),
                            )
                            db.commit()
                            db.close()
                            break
                else:
                    continue
                break
    except Exception as e:
        print(f"[PVE] _enrich_vm({vmid}) warning: {e}")
    return vm


# ── VM lifecycle ──────────────────────────────────────────────────────────────

def start_vm(vmid: int) -> bool:
    r = _req('post', f'/nodes/{get_node()}/qemu/{vmid}/status/start')
    return r.ok


def stop_vm(vmid: int) -> bool:
    r = _req('post', f'/nodes/{get_node()}/qemu/{vmid}/status/stop')
    return r.ok


def delete_vm(vmid: int) -> bool:
    stop_vm(vmid)
    r = _req('delete', f'/nodes/{get_node()}/qemu/{vmid}')
    if r.ok:
        db = get_db()
        db.execute('DELETE FROM vms WHERE proxmox_vmid=?', (vmid,))
        db.commit()
        db.close()
    return r.ok


# ── VM provisioning ───────────────────────────────────────────────────────────

def provision_vm(req: dict, owner_uid: str, vlan: int, department: str):
    """
    Clone the matching OS template, inject Cloud-Init credentials, and start the VM.

    Returns:
        (vmid, credentials_dict, None)   on success
        (None, None, error_string)       on failure

    credentials_dict = { 'username': str, 'password': str, 'type': 'ssh'|'rdp' }
    These are stored in SQLite (vms.vm_username / vms.vm_password) so they
    can be shown to the Dr. on their dashboard.
    """
    os_name     = req['os']
    template_id = Config.VM_TEMPLATES.get(os_name)
    if not template_id:
        return None, None, f'No template configured for OS: {os_name}'

    node = get_node()   # DNS-safe — resolved via IP

    # ── 1. Decide connection type & default username ──────────────────────────
    is_windows   = 'Windows' in os_name
    conn_type    = 'rdp' if is_windows else 'ssh'
    vm_username  = 'Administrator' if is_windows else 'cloudinit'
    vm_password  = _generate_password()

    # ── 2. Get next available VMID ────────────────────────────────────────────
    r = _req('get', '/cluster/nextid')
    if not r.ok:
        return None, None, 'Could not obtain next VMID from Proxmox'
    vmid = int(r.json()['data'])

    # ── 3. Clone template (full clone so each VM is independent) ─────────────
    r = _req('post', f'/nodes/{node}/qemu/{template_id}/clone', data={
        'newid':   vmid,
        'name':    req['vm_name'],
        'full':    1,
        'storage': Config.PROXMOX_STORAGE,
    })
    if not r.ok:
        return None, None, f'Template clone failed: {r.text}'

    # ── 4. Set CPU / RAM / description / tags ─────────────────────────────────
    _req('put', f'/nodes/{node}/qemu/{vmid}/config', data={
        'cores':       req['vcpu'],
        'memory':      req['ram_gb'] * 1024,
        'description': f'owner:{owner_uid} vlan:{vlan} dept:{department}',
        'tags':        f'vlan{vlan};{owner_uid}',
    })

    # ── 5. Resize disk ────────────────────────────────────────────────────────
    _req('put', f'/nodes/{node}/qemu/{vmid}/resize', data={
        'disk': 'scsi0',
        'size': f'{req["disk_gb"]}G',
    })

    # ── 6. Set VLAN tag on NIC ────────────────────────────────────────────────
    _req('put', f'/nodes/{node}/qemu/{vmid}/config', data={
        'net0': f'virtio,bridge=vmbr0,tag={vlan}',
    })

    # ── 7. Cloud-Init credentials (Linux only) ────────────────────────────────
    # Windows VMs managed separately; Cloud-Init only applies to Linux templates.
    # Your Linux templates must have the cloud-init drive (ide2: local:cloudinit).
    if not is_windows:
        ci = _req('put', f'/nodes/{node}/qemu/{vmid}/config', data={
            'ciuser':     vm_username,
            'cipassword': vm_password,
            # Allow SSH password login so the Dr. can connect right away
            # (they can add their SSH key later inside the VM)
            'sshkeys':    '',
        })
        if not ci.ok:
            print(f"[PVE] Cloud-Init warning for VMID={vmid}: {ci.text}")
            # Non-fatal — VM still boots; just won't have auto credentials

    # ── 8. Start VM ───────────────────────────────────────────────────────────
    _req('post', f'/nodes/{node}/qemu/{vmid}/status/start')

    # ── 9. Record in SQLite (including credentials) ───────────────────────────
    db = get_db()
    db.execute(
        '''INSERT OR REPLACE INTO vms
           (proxmox_vmid, name, owner_uid, vlan, department,
            os, vcpu, ram_gb, disk_gb, status,
            vm_username, vm_password, conn_type)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (vmid, req['vm_name'], owner_uid, vlan, department,
         os_name, req['vcpu'], req['ram_gb'], req['disk_gb'], 'building',
         vm_username, vm_password, conn_type),
    )
    db.commit()
    db.close()

    credentials = {
        'username': vm_username,
        'password': vm_password,
        'type':     conn_type,
    }
    print(f"[PVE] Provisioned VMID={vmid} ({conn_type}) for {owner_uid} on VLAN {vlan}")
    return vmid, credentials, None
