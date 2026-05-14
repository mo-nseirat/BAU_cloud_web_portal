import sqlite3
from config import Config

def get_db():
    conn = sqlite3.connect(Config.DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # better concurrency
    return conn

def init_db():
    conn = get_db()
    # Main schema (idempotent)
    conn.executescript('''

        -- VM provisioning requests submitted by Drs
        CREATE TABLE IF NOT EXISTS requests (
            id            TEXT    PRIMARY KEY,
            owner_uid     TEXT    NOT NULL,
            vm_name       TEXT    NOT NULL,
            os            TEXT    NOT NULL,
            vcpu          INTEGER NOT NULL,
            ram_gb        INTEGER NOT NULL,
            disk_gb       INTEGER NOT NULL,
            purpose       TEXT    DEFAULT '',
            notes         TEXT    DEFAULT '',
            status        TEXT    DEFAULT 'pending',   -- pending|approved|rejected
            it_note       TEXT    DEFAULT '',
            proxmox_vmid  INTEGER,
            created_at    DATETIME DEFAULT (datetime('now')),
            updated_at    DATETIME DEFAULT (datetime('now'))
        );

        -- VMs that have been provisioned on Proxmox
        CREATE TABLE IF NOT EXISTS vms (
            proxmox_vmid  INTEGER PRIMARY KEY,
            name          TEXT    NOT NULL,
            owner_uid     TEXT    NOT NULL,
            vlan          INTEGER NOT NULL,
            department    TEXT    DEFAULT '',
            os            TEXT    DEFAULT '',
            vcpu          INTEGER DEFAULT 1,
            ram_gb        INTEGER DEFAULT 1,
            disk_gb       INTEGER DEFAULT 20,
            ip_address    TEXT    DEFAULT 'Assigning...',
            status        TEXT    DEFAULT 'building',
            -- VM login credentials set via Cloud-Init at provisioning time
            vm_username   TEXT    DEFAULT '',
            vm_password   TEXT    DEFAULT '',
            conn_type     TEXT    DEFAULT 'ssh',   -- 'ssh' | 'rdp'
            created_at    DATETIME DEFAULT (datetime('now'))
        );

        -- Per-user settings managed by IT Admin
        CREATE TABLE IF NOT EXISTS user_settings (
            uid                  TEXT    PRIMARY KEY,
            active               INTEGER DEFAULT 1,
            must_change_password INTEGER DEFAULT 1,
            created_at           DATETIME DEFAULT (datetime('now'))
        );

    ''')
    conn.commit()

    # Migrations: add new columns to existing DBs — tried individually so a
    # "duplicate column" error on one doesn't block the rest.
    migrations = [
        "ALTER TABLE vms ADD COLUMN vm_username TEXT DEFAULT ''",
        "ALTER TABLE vms ADD COLUMN vm_password TEXT DEFAULT ''",
        "ALTER TABLE vms ADD COLUMN conn_type   TEXT DEFAULT 'ssh'",
        "ALTER TABLE user_settings ADD COLUMN must_change_password INTEGER DEFAULT 1",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass   # column already exists — safe to ignore

    conn.close()
    print("[DB] Database initialised.")
