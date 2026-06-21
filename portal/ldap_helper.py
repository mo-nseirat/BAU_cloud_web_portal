"""
ldap_helper.py
All OpenLDAP operations for the FET Cloud Portal.

LDAP structure used:
  dc=fet,dc=bau,dc=jo
  └── ou=users
        ├── uid=dr.ahmad   (employeeType=user,  departmentNumber=20)
        ├── uid=dr.sara    (employeeType=user,  departmentNumber=10)
        └── uid=it.admin   (employeeType=admin, departmentNumber=99)
"""

import ldap
import ldap.modlist as modlist
from config import Config

_LDAP_URL = f'ldap://{Config.LDAP_HOST}:{Config.LDAP_PORT}'


# ── Internal helpers ──────────────────────────────────────────────────────────

def _admin_conn():
    """Return an LDAP connection bound as the directory admin."""
    conn = ldap.initialize(_LDAP_URL)
    conn.protocol_version = ldap.VERSION3
    conn.set_option(ldap.OPT_REFERRALS, 0)
    conn.simple_bind_s(Config.LDAP_ADMIN_DN, Config.LDAP_ADMIN_PASSWORD)
    return conn


def _user_dn(uid: str) -> str:
    return f'uid={uid},{Config.LDAP_USERS_OU}'


def _parse(attrs: dict) -> dict:
    """Convert raw LDAP attribute dict to a clean Python dict."""
    def g(k):
        v = attrs.get(k)
        return v[0].decode('utf-8', errors='ignore') if v else ''

    uid  = g('uid')
    name = g('cn')
    return {
        'uid':      uid,
        'name':     name,
        'dept':     g('ou'),
        'vlan':     int(g('departmentNumber') or 0),
        'role':     g('employeeType') or 'user',
        'initials': ''.join(w[0].upper() for w in name.split() if w)[:2],
    }


# ── Public API ────────────────────────────────────────────────────────────────

def authenticate(uid: str, password: str):
    """
    Try to bind as the user.
    Returns a user dict on success, None on failure.
    """
    if not uid or not password:
        return None
    try:
        conn = ldap.initialize(_LDAP_URL)
        conn.protocol_version = ldap.VERSION3
        conn.set_option(ldap.OPT_REFERRALS, 0)
        conn.simple_bind_s(_user_dn(uid), password)

        # Fetch attributes after successful bind
        result = conn.search_s(
            Config.LDAP_USERS_OU,
            ldap.SCOPE_ONELEVEL,
            f'(uid={uid})',
            ['cn', 'uid', 'departmentNumber', 'ou', 'employeeType'],
        )
        conn.unbind_s()
        if not result:
            return None
        _, attrs = result[0]
        return _parse(attrs)

    except ldap.INVALID_CREDENTIALS:
        return None
    except Exception as e:
        print(f"[LDAP] authenticate error: {e}")
        return None


def get_user(uid: str):
    """Look up a single user by uid. Returns user dict or None."""
    try:
        conn = _admin_conn()
        result = conn.search_s(
            Config.LDAP_USERS_OU,
            ldap.SCOPE_ONELEVEL,
            f'(uid={uid})',
            ['cn', 'uid', 'departmentNumber', 'ou', 'employeeType'],
        )
        conn.unbind_s()
        if not result:
            return None
        _, attrs = result[0]
        return _parse(attrs)
    except Exception as e:
        print(f"[LDAP] get_user error: {e}")
        return None


def list_users():
    """Return all users in ou=users."""
    try:
        conn = _admin_conn()
        result = conn.search_s(
            Config.LDAP_USERS_OU,
            ldap.SCOPE_ONELEVEL,
            '(objectClass=inetOrgPerson)',
            ['cn', 'uid', 'departmentNumber', 'ou', 'employeeType'],
        )
        conn.unbind_s()
        return [_parse(attrs) for _, attrs in result if attrs]
    except Exception as e:
        print(f"[LDAP] list_users error: {e}")
        return []


def create_user(uid: str, password: str, full_name: str,
                department: str, vlan: int, role: str = 'user') -> bool:
    """
    Create a new LDAP user entry.
    Returns True on success, False if uid already exists or on error.
    """
    try:
        conn = _admin_conn()
        dn = _user_dn(uid)

        parts = full_name.strip().split()
        sn = parts[-1] if len(parts) > 1 else full_name

        entry = {
            'objectClass':    [b'inetOrgPerson', b'organizationalPerson', b'person'],
            'uid':            [uid.encode()],
            'cn':             [full_name.encode()],
            'sn':             [sn.encode()],
            'ou':             [department.encode()],
            'departmentNumber': [str(vlan).encode()],
            'employeeType':   [role.encode()],
            'userPassword':   [password.encode()],
        }
        ldif = modlist.addModlist(entry)
        conn.add_s(dn, ldif)
        conn.unbind_s()
        print(f"[LDAP] Created user: {uid}")
        return True

    except ldap.ALREADY_EXISTS:
        print(f"[LDAP] create_user: {uid} already exists")
        return False
    except Exception as e:
        print(f"[LDAP] create_user error: {e}")
        return False


def set_password(uid: str, new_password: str) -> bool:
    """Reset a user's password."""
    try:
        conn = _admin_conn()
        conn.modify_s(
            _user_dn(uid),
            [(ldap.MOD_REPLACE, 'userPassword', [new_password.encode()])],
        )
        conn.unbind_s()
        return True
    except Exception as e:
        print(f"[LDAP] set_password error: {e}")
        return False


def delete_user(uid: str) -> bool:
    """Remove a user entry from LDAP."""
    try:
        conn = _admin_conn()
        conn.delete_s(_user_dn(uid))
        conn.unbind_s()
        print(f"[LDAP] Deleted user: {uid}")
        return True
    except Exception as e:
        print(f"[LDAP] delete_user error: {e}")
        return False
