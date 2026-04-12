import sqlite3
from config import Config

def get_db():
    conn = sqlite3.connect(Config.DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # better concurrency
    return conn

def init_db():
    conn = get_db()
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
        -- Owner / VLAN metadata is stored here; live status is fetched from Proxmox
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
            created_at    DATETIME DEFAULT (datetime('now'))
        );

        -- Per-user settings (active/disabled) kept in SQLite
        -- because OpenLDAP enable/disable requires ppolicy overlay;
        -- this is simpler and fully controlled by IT Admin in the portal.
        CREATE TABLE IF NOT EXISTS user_settings (
            uid        TEXT    PRIMARY KEY,
            active     INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT (datetime('now'))
        );

    ''')
    conn.commit()
    conn.close()
    print("[DB] Database initialised.")
