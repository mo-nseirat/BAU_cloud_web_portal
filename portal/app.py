"""
app.py  —  FET Private Cloud Portal — Flask Backend
============================================================
Routes
------
POST  /api/login                    Authenticate via LDAP
POST  /api/logout                   Clear session
GET   /api/me                       Current session user

GET   /api/vms                      User: own VMs | Admin: all VMs
POST  /api/vms/<vmid>/start         Start a VM
POST  /api/vms/<vmid>/stop          Stop a VM
DELETE /api/vms/<vmid>              Delete a VM

GET   /api/requests                 User: own requests | Admin: all
POST  /api/requests                 Submit a new VM request (user)
PUT   /api/requests/<id>/approve    Approve + provision VM (admin)
PUT   /api/requests/<id>/reject     Reject with reason (admin)

GET   /api/users                    List all users (admin)
POST  /api/users                    Create Dr. account in LDAP (admin)
PUT   /api/users/<uid>/password     Reset password in LDAP (admin)
PUT   /api/users/<uid>/toggle       Enable / disable account (admin)
DELETE /api/users/<uid>             Remove from LDAP + DB (admin)
"""

import os
import uuid
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, session, send_from_directory

from config import Config
from database import get_db, init_db
import ldap_helper  as ldap_h
import proxmox_helper as pve

# ── App setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder='static')
app.config.from_object(Config)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# ── Decorators ────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'uid' not in session:
            return jsonify({'error': 'Unauthorized — please log in'}), 401
        return f(*args, **kwargs)
    return wrapped


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'uid' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        if session.get('role') != 'admin':
            return jsonify({'error': 'Forbidden — IT Admin only'}), 403
        return f(*args, **kwargs)
    return wrapped


# ── Helper: check active flag in SQLite ───────────────────────────────────────

def _is_active(uid: str) -> bool:
    db  = get_db()
    row = db.execute('SELECT active FROM user_settings WHERE uid=?', (uid,)).fetchone()
    db.close()
    # Not in table yet → treat as active (new user)
    return row is None or row['active'] == 1


def _can_access_vm(vmid: int) -> bool:
    """Admin can access all VMs; Dr. can only access their own."""
    if session.get('role') == 'admin':
        return True
    db  = get_db()
    row = db.execute('SELECT owner_uid FROM vms WHERE proxmox_vmid=?', (vmid,)).fetchone()
    db.close()
    return row is not None and row['owner_uid'] == session['uid']


# ── Serve frontend ─────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('static', 'dashboard.html')


# ═══════════════════════════════════════════════════════════
#  AUTH
# ═══════════════════════════════════════════════════════════

@app.route('/api/login', methods=['POST'])
def login():
    data     = request.get_json(silent=True) or {}
    uid      = data.get('username', '').strip()
    password = data.get('password', '')

    if not uid or not password:
        return jsonify({'error': 'Username and password are required'}), 400

    user = ldap_h.authenticate(uid, password)
    if not user:
        return jsonify({'error': 'Invalid username or password'}), 401

    if not _is_active(uid):
        return jsonify({'error': 'Your account is disabled. Contact the IT team.'}), 403

    # Fix 3: check first-login flag
    db  = get_db()
    row = db.execute('SELECT must_change_password FROM user_settings WHERE uid=?', (uid,)).fetchone()
    db.close()
    must_change = row['must_change_password'] if row else 0   # admins created manually default to 0

    session['uid']               = user['uid']
    session['name']              = user['name']
    session['role']              = user['role']
    session['vlan']              = user['vlan']
    session['dept']              = user['dept']
    session['initials']          = user['initials']
    session['must_change_password'] = bool(must_change)

    return jsonify({'user': user, 'must_change_password': bool(must_change)})


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'ok': True})


@app.route('/api/me')
def me():
    if 'uid' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    return jsonify({
        'uid':                  session['uid'],
        'name':                 session['name'],
        'role':                 session['role'],
        'vlan':                 session['vlan'],
        'dept':                 session['dept'],
        'initials':             session['initials'],
        'must_change_password': session.get('must_change_password', False),
    })


@app.route('/api/change-password', methods=['POST'])
@login_required
def change_password():
    """
    Called from the forced password-change screen.
    Validates the new password, updates LDAP, clears the flag.
    """
    data         = request.get_json(silent=True) or {}
    new_password = data.get('new_password', '').strip()
    confirm      = data.get('confirm_password', '').strip()

    if not new_password or len(new_password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400
    if new_password != confirm:
        return jsonify({'error': 'Passwords do not match'}), 400

    uid = session['uid']
    ok  = ldap_h.set_password(uid, new_password)
    if not ok:
        return jsonify({'error': 'Failed to update password. Contact IT.'}), 500

    # Clear the flag in SQLite and in the current session
    db = get_db()
    db.execute(
        'UPDATE user_settings SET must_change_password=0 WHERE uid=?', (uid,)
    )
    db.commit()
    db.close()
    session['must_change_password'] = False
    return jsonify({'ok': True})


# ═══════════════════════════════════════════════════════════
#  VMs
# ═══════════════════════════════════════════════════════════

@app.route('/api/vms')
@login_required
def get_vms():
    if session['role'] == 'admin':
        vms = pve.get_all_vms()
    else:
        vms = pve.get_vms_for_user(session['uid'])
    return jsonify(vms)


@app.route('/api/vms/<int:vmid>/start', methods=['POST'])
@login_required
def vm_start(vmid):
    if not _can_access_vm(vmid):
        return jsonify({'error': 'Forbidden'}), 403
    ok = pve.start_vm(vmid)
    return jsonify({'ok': ok})


@app.route('/api/vms/<int:vmid>/stop', methods=['POST'])
@login_required
def vm_stop(vmid):
    if not _can_access_vm(vmid):
        return jsonify({'error': 'Forbidden'}), 403
    ok = pve.stop_vm(vmid)
    return jsonify({'ok': ok})


@app.route('/api/vms/<int:vmid>', methods=['DELETE'])
@login_required
def vm_delete(vmid):
    if not _can_access_vm(vmid):
        return jsonify({'error': 'Forbidden'}), 403
    ok = pve.delete_vm(vmid)
    return jsonify({'ok': ok})


# ═══════════════════════════════════════════════════════════
#  REQUESTS
# ═══════════════════════════════════════════════════════════

@app.route('/api/requests')
@login_required
def get_requests():
    db = get_db()
    if session['role'] == 'admin':
        rows = db.execute(
            'SELECT * FROM requests ORDER BY created_at DESC'
        ).fetchall()
    else:
        rows = db.execute(
            'SELECT * FROM requests WHERE owner_uid=? ORDER BY created_at DESC',
            (session['uid'],),
        ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/requests', methods=['POST'])
@login_required
def submit_request():
    data = request.get_json(silent=True) or {}
    required = ['vm_name', 'os', 'vcpu', 'ram_gb', 'disk_gb']
    missing  = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({'error': f'Missing fields: {", ".join(missing)}'}), 400

    req_id = 'REQ-' + str(uuid.uuid4())[:8].upper()
    db     = get_db()
    db.execute(
        '''INSERT INTO requests
           (id, owner_uid, vm_name, os, vcpu, ram_gb, disk_gb, purpose, notes, status)
           VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (req_id, session['uid'], data['vm_name'], data['os'],
         data['vcpu'], data['ram_gb'], data['disk_gb'],
         data.get('purpose', ''), data.get('notes', ''), 'pending'),
    )
    db.commit()
    db.close()
    return jsonify({'id': req_id}), 201


@app.route('/api/requests/<req_id>/approve', methods=['PUT'])
@admin_required
def approve_request(req_id):
    db  = get_db()
    row = db.execute('SELECT * FROM requests WHERE id=?', (req_id,)).fetchone()
    db.close()
    if not row:
        return jsonify({'error': 'Request not found'}), 404
    req = dict(row)

    if req['status'] != 'pending':
        return jsonify({'error': f'Request is already {req["status"]}'}), 409

    owner = ldap_h.get_user(req['owner_uid'])
    if not owner:
        return jsonify({'error': 'Owner account not found in LDAP'}), 404

    # Fix 2: provision_vm now returns (vmid, credentials, error)
    vmid, credentials, err = pve.provision_vm(
        req, req['owner_uid'], owner['vlan'], owner['dept']
    )
    if err:
        return jsonify({'error': f'Proxmox provisioning failed: {err}'}), 500

    db = get_db()
    db.execute(
        '''UPDATE requests
           SET status='approved', it_note=?, proxmox_vmid=?, updated_at=?
           WHERE id=?''',
        ('Request approved. VM provisioning initiated.', vmid,
         datetime.utcnow().isoformat(), req_id),
    )
    db.commit()
    db.close()
    return jsonify({'ok': True, 'vmid': vmid, 'credentials': credentials})


@app.route('/api/requests/<req_id>/reject', methods=['PUT'])
@admin_required
def reject_request(req_id):
    data   = request.get_json(silent=True) or {}
    reason = data.get('reason', '').strip()
    if not reason:
        return jsonify({'error': 'A rejection reason is required'}), 400

    db = get_db()
    db.execute(
        '''UPDATE requests
           SET status='rejected', it_note=?, updated_at=?
           WHERE id=?''',
        (reason, datetime.utcnow().isoformat(), req_id),
    )
    db.commit()
    db.close()
    return jsonify({'ok': True})


# ═══════════════════════════════════════════════════════════
#  USERS  (IT Admin only)
# ═══════════════════════════════════════════════════════════

@app.route('/api/users')
@admin_required
def get_users():
    users = ldap_h.list_users()
    db    = get_db()
    for u in users:
        row       = db.execute(
            'SELECT active FROM user_settings WHERE uid=?', (u['uid'],)
        ).fetchone()
        u['active']   = (row['active'] == 1) if row else True
        u['vm_count'] = db.execute(
            'SELECT COUNT(*) AS c FROM vms WHERE owner_uid=?', (u['uid'],)
        ).fetchone()['c']
    db.close()
    return jsonify(users)


@app.route('/api/users', methods=['POST'])
@admin_required
def create_user():
    data     = request.get_json(silent=True) or {}
    required = ['uid', 'password', 'name', 'department', 'vlan']
    missing  = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({'error': f'Missing fields: {", ".join(missing)}'}), 400

    ok = ldap_h.create_user(
        data['uid'],
        data['password'],
        data['name'],
        data['department'],
        int(data['vlan']),
        data.get('role', 'user'),
    )
    if not ok:
        return jsonify({'error': 'Username already exists or LDAP error'}), 409

    # Ensure active flag and first-login password-change flag are set
    db = get_db()
    db.execute(
        'INSERT OR REPLACE INTO user_settings (uid, active, must_change_password) VALUES (?,1,1)',
        (data['uid'],),
    )
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/users/<uid>/password', methods=['PUT'])
@admin_required
def reset_password(uid):
    data     = request.get_json(silent=True) or {}
    password = data.get('password', '').strip()
    if not password or len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    ok = ldap_h.set_password(uid, password)
    return jsonify({'ok': ok})


@app.route('/api/users/<uid>/toggle', methods=['PUT'])
@admin_required
def toggle_user(uid):
    user = ldap_h.get_user(uid)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    if user['role'] == 'admin':
        return jsonify({'error': 'Cannot disable the IT Admin account'}), 403

    db      = get_db()
    row     = db.execute('SELECT active FROM user_settings WHERE uid=?', (uid,)).fetchone()
    current = row['active'] if row else 1
    new_val = 0 if current else 1
    db.execute(
        'INSERT OR REPLACE INTO user_settings (uid, active) VALUES (?,?)',
        (uid, new_val),
    )
    db.commit()
    db.close()
    return jsonify({'ok': True, 'active': bool(new_val)})


@app.route('/api/users/<uid>', methods=['DELETE'])
@admin_required
def delete_user(uid):
    user = ldap_h.get_user(uid)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    if user['role'] == 'admin':
        return jsonify({'error': 'Cannot delete the IT Admin account'}), 403

    ok = ldap_h.delete_user(uid)
    if ok:
        db = get_db()
        db.execute('DELETE FROM user_settings WHERE uid=?', (uid,))
        db.commit()
        db.close()
    return jsonify({'ok': ok})


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    # Ensure DB exists before first request
    os.makedirs(os.path.dirname(Config.DATABASE), exist_ok=True)
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=False)
