#!/bin/bash
# =============================================================
#  FET Private Cloud Portal — Setup Script
#  Ubuntu 22.04 LXC  |  OpenLDAP already installed
# =============================================================
# Run as root inside the LXC container:
#   chmod +x setup.sh && ./setup.sh
# =============================================================

set -e

# ── CONFIG — edit these before running ───────────────────────
LDAP_DOMAIN="fet.bau.jo"           # used to build base DN:  dc=fet,dc=bau,dc=jo
LDAP_ORG="FET-BAU"
LDAP_ADMIN_PASS="LdapAdmin@FET2025"    # OpenLDAP admin password
IT_ADMIN_PASS="ITAdmin@Portal2025"     # Initial password for it.admin portal account
PORTAL_DIR="/opt/cloud-portal"
PORTAL_USER="cloudportal"
# ─────────────────────────────────────────────────────────────

LDAP_BASE="dc=$(echo $LDAP_DOMAIN | sed 's/\./,dc=/g')"
echo "Base DN will be: $LDAP_BASE"

# ══════════════════════════════════════════════════════════════
#  1. System packages
# ══════════════════════════════════════════════════════════════
echo "==> Installing system packages..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    slapd ldap-utils \
    python3 python3-pip python3-venv python3-dev \
    libldap2-dev libsasl2-dev \
    nginx \
    curl

# ══════════════════════════════════════════════════════════════
#  2. Configure OpenLDAP (slapd installed but not configured)
# ══════════════════════════════════════════════════════════════
echo "==> Configuring OpenLDAP..."

# Feed answers to debconf so dpkg-reconfigure runs non-interactively
debconf-set-selections <<EOF
slapd slapd/internal/generated_adminpw  password $LDAP_ADMIN_PASS
slapd slapd/internal/adminpw            password $LDAP_ADMIN_PASS
slapd slapd/password2                   password $LDAP_ADMIN_PASS
slapd slapd/password1                   password $LDAP_ADMIN_PASS
slapd slapd/domain                      string   $LDAP_DOMAIN
slapd shared/organization               string   $LDAP_ORG
slapd slapd/purge_database              boolean  true
slapd slapd/move_old_database           boolean  true
slapd slapd/allow_ldap_v2               boolean  false
slapd slapd/no_configuration            boolean  false
slapd slapd/dump_database               select   when needed
EOF

DEBIAN_FRONTEND=noninteractive dpkg-reconfigure slapd

# Restart and enable
systemctl restart slapd
systemctl enable  slapd
echo "    slapd running with base DN: $LDAP_BASE"

# ══════════════════════════════════════════════════════════════
#  3. Build LDAP directory structure
# ══════════════════════════════════════════════════════════════
echo "==> Creating LDAP directory structure..."

# Create ou=users
ldapadd -x -D "cn=admin,$LDAP_BASE" -w "$LDAP_ADMIN_PASS" <<LDIF || true
dn: ou=users,$LDAP_BASE
objectClass: organizationalUnit
ou: users
LDIF

echo "    ou=users created."

# Create initial IT Admin account
# employeeType=admin  departmentNumber=99
ldapadd -x -D "cn=admin,$LDAP_BASE" -w "$LDAP_ADMIN_PASS" <<LDIF || echo "    it.admin may already exist — skipping"
dn: uid=it.admin,ou=users,$LDAP_BASE
objectClass: inetOrgPerson
objectClass: organizationalPerson
objectClass: person
uid: it.admin
cn: IT Administrator
sn: Administrator
ou: IT Department
departmentNumber: 99
employeeType: admin
userPassword: $IT_ADMIN_PASS
LDIF

echo "    it.admin account created (password: $IT_ADMIN_PASS)"

# Verify
echo "==> LDAP directory contents:"
ldapsearch -x -LLL -D "cn=admin,$LDAP_BASE" -w "$LDAP_ADMIN_PASS" \
    -b "ou=users,$LDAP_BASE" "(objectClass=inetOrgPerson)" uid cn employeeType

# ══════════════════════════════════════════════════════════════
#  4. Create portal directory + Python virtualenv
# ══════════════════════════════════════════════════════════════
echo "==> Setting up portal directory..."

mkdir -p "$PORTAL_DIR/static"
mkdir -p "$PORTAL_DIR/logs"

# Create dedicated system user
if ! id "$PORTAL_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /sbin/nologin "$PORTAL_USER"
fi

# Python virtual environment
python3 -m venv "$PORTAL_DIR/venv"
source "$PORTAL_DIR/venv/bin/activate"

pip install --quiet --upgrade pip
pip install --quiet flask>=3.0.0 requests>=2.31.0

# python-ldap needs system headers already installed above
pip install --quiet python-ldap>=3.4.0

deactivate
echo "    Python venv ready at $PORTAL_DIR/venv"

# ══════════════════════════════════════════════════════════════
#  5. Copy application files
# ══════════════════════════════════════════════════════════════
echo "==> Copying application files..."
# Run from the directory that contains setup.sh and all .py files
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cp "$SCRIPT_DIR/app.py"             "$PORTAL_DIR/"
cp "$SCRIPT_DIR/config.py"          "$PORTAL_DIR/"
cp "$SCRIPT_DIR/database.py"        "$PORTAL_DIR/"
cp "$SCRIPT_DIR/ldap_helper.py"     "$PORTAL_DIR/"
cp "$SCRIPT_DIR/proxmox_helper.py"  "$PORTAL_DIR/"

# Frontend
if [ -f "$SCRIPT_DIR/dashboard.html" ]; then
    cp "$SCRIPT_DIR/dashboard.html" "$PORTAL_DIR/static/dashboard.html"
fi

# Set permissions
chown -R "$PORTAL_USER:$PORTAL_USER" "$PORTAL_DIR"
chmod 750 "$PORTAL_DIR"

echo "    Files copied to $PORTAL_DIR"

# ══════════════════════════════════════════════════════════════
#  6. Write environment file (secrets — keep this file safe)
# ══════════════════════════════════════════════════════════════
cat > "$PORTAL_DIR/.env" <<ENV
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
LDAP_ADMIN_PASSWORD=$LDAP_ADMIN_PASS
# Set these to match your Proxmox server:
PROXMOX_HOST=192.168.99.1
PROXMOX_USER=root@pam
PROXMOX_PASSWORD=your-proxmox-root-password
PROXMOX_NODE=pve
ENV

chmod 600 "$PORTAL_DIR/.env"
chown "$PORTAL_USER:$PORTAL_USER" "$PORTAL_DIR/.env"
echo "    .env file written. Edit $PORTAL_DIR/.env with your Proxmox credentials."

# ══════════════════════════════════════════════════════════════
#  7. Systemd service
# ══════════════════════════════════════════════════════════════
echo "==> Creating systemd service..."

cat > /etc/systemd/system/cloud-portal.service <<SERVICE
[Unit]
Description=FET Private Cloud Portal (Flask)
After=network.target slapd.service
Wants=slapd.service

[Service]
Type=simple
User=$PORTAL_USER
WorkingDirectory=$PORTAL_DIR
EnvironmentFile=$PORTAL_DIR/.env
ExecStart=$PORTAL_DIR/venv/bin/python app.py
Restart=on-failure
RestartSec=5
StandardOutput=append:$PORTAL_DIR/logs/portal.log
StandardError=append:$PORTAL_DIR/logs/portal-error.log

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable  cloud-portal
systemctl start   cloud-portal
echo "    cloud-portal.service started."

# ══════════════════════════════════════════════════════════════
#  8. Nginx reverse proxy (port 80 → Flask :5000)
# ══════════════════════════════════════════════════════════════
echo "==> Configuring Nginx..."

cat > /etc/nginx/sites-available/cloud-portal <<NGINX
server {
    listen 80;
    server_name _;

    # Security headers
    add_header X-Frame-Options      SAMEORIGIN;
    add_header X-Content-Type-Options nosniff;

    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 120;
    }
}
NGINX

ln -sf /etc/nginx/sites-available/cloud-portal /etc/nginx/sites-enabled/cloud-portal
rm -f  /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx && systemctl enable nginx
echo "    Nginx configured — portal accessible on port 80."

# ══════════════════════════════════════════════════════════════
#  Done
# ══════════════════════════════════════════════════════════════
LXC_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "╔════════════════════════════════════════════════════╗"
echo "║   FET Cloud Portal — Setup Complete!              ║"
echo "╠════════════════════════════════════════════════════╣"
echo "║  Portal URL  : http://$LXC_IP                     ║"
echo "║  LDAP Base   : $LDAP_BASE                         ║"
echo "║  Admin login : it.admin / $IT_ADMIN_PASS          ║"
echo "║                                                    ║"
echo "║  NEXT STEPS:                                       ║"
echo "║  1. Edit $PORTAL_DIR/.env                         ║"
echo "║     → set PROXMOX_HOST, PROXMOX_PASSWORD          ║"
echo "║  2. Restart: systemctl restart cloud-portal       ║"
echo "║  3. Set VM template IDs in config.py              ║"
echo "╚════════════════════════════════════════════════════╝"
