import os

class Config:
    # ── Flask ──────────────────────────────────────────────
    SECRET_KEY = os.environ.get('SECRET_KEY', 'fet-cloud-change-this-in-production-2025!')

    # ── OpenLDAP ───────────────────────────────────────────
    LDAP_HOST            = 'localhost'
    LDAP_PORT            = 389
    LDAP_BASE_DN         = 'dc=fet,dc=bau,dc=jo'
    LDAP_USERS_OU        = 'ou=users,dc=fet,dc=bau,dc=jo'
    LDAP_ADMIN_DN        = 'cn=admin,dc=fet,dc=bau,dc=jo'
    LDAP_ADMIN_PASSWORD  = os.environ.get('LDAP_ADMIN_PASSWORD', 'LdapAdmin@FET2025')

    # ── Proxmox ────────────────────────────────────────────
    # Change PROXMOX_HOST to your actual Proxmox node IP
    PROXMOX_HOST       = os.environ.get('PROXMOX_HOST', '192.168.1.100')
    PROXMOX_PORT       = 8006
    PROXMOX_USER       = os.environ.get('PROXMOX_USER', 'root@pam')
    PROXMOX_PASSWORD   = os.environ.get('PROXMOX_PASSWORD', 'Moh123123$')
    PROXMOX_NODE       = os.environ.get('PROXMOX_NODE', 'privatedatacenter')   # run: pvesh get /nodes
    PROXMOX_VERIFY_SSL = False
    PROXMOX_STORAGE    = 'local-lvm'   # Storage pool for VM disks

    # VM Template IDs (set these after creating templates in Proxmox)
    # Create a template VM in Proxmox, then note its VMID here
    VM_TEMPLATES = {
    'Ubuntu 22.04 LTS': 9000,
    'Ubuntu 24.04 LTS': 9001,
}

    VM_ID_START = 200   # First VMID for newly provisioned VMs

    # ── SQLite Database ────────────────────────────────────
    DATABASE = '/opt/cloud-portal/portal.db'

    # ── VLAN → Department mapping ──────────────────────────
    VLAN_DEPT_MAP = {
        10: 'Computer Engineering',
        20: 'Mechatronics Engineering',
        30: 'Mechanical Engineering',
        40: 'Electrical Engineering',
        99: 'IT Department',
    }
