"""Migrações incrementais SQLite (schema version em app_setting)."""
from sqlalchemy import text

SCHEMA_VERSION = 3

MIGRATIONS = [
    # v1 — auditoria, config, recorrência, criado_por
    """
    CREATE TABLE IF NOT EXISTS app_setting (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL,
        entity TEXT NOT NULL,
        entity_id INTEGER,
        detail TEXT,
        actor TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS recurring_template (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        valor REAL NOT NULL,
        categoria TEXT NOT NULL DEFAULT 'Outros',
        dia_vencimento INTEGER NOT NULL DEFAULT 1,
        tipo TEXT NOT NULL DEFAULT 'pagar',
        ativo INTEGER NOT NULL DEFAULT 1,
        ultimo_gerado TEXT
    );
    """,
    # v2 — colunas em tabelas existentes
    """
    ALTER TABLE lista_compras ADD COLUMN criado_por TEXT;
    ALTER TABLE financas ADD COLUMN criado_por TEXT;
    ALTER TABLE conta ADD COLUMN criado_por TEXT;
    ALTER TABLE conta_receber ADD COLUMN criado_por TEXT;
    ALTER TABLE orcamento ADD COLUMN meta_economia REAL;
    """,
    # v3 — loja no item (comparador por mercado)
    """
    ALTER TABLE item_gasto ADD COLUMN mercado TEXT;
    """,
]


def _table_exists(conn, name):
    r = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"),
        {"n": name},
    ).fetchone()
    return r is not None


def _column_exists(conn, table, column):
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def run_migrations(db):
    with db.engine.connect() as conn:
        if not _table_exists(conn, "app_setting"):
            for stmt in MIGRATIONS[0].strip().split(";"):
                s = stmt.strip()
                if s:
                    conn.execute(text(s))
            conn.commit()

        current = 0
        if _table_exists(conn, "app_setting"):
            row = conn.execute(
                text("SELECT value FROM app_setting WHERE key='schema_version'")
            ).fetchone()
            if row:
                current = int(row[0])

        while current < SCHEMA_VERSION:
            step = current + 1
            if step == 2:
                for stmt in MIGRATIONS[1].strip().split(";"):
                    s = stmt.strip()
                    if not s:
                        continue
                    parts = s.split()
                    if parts[0].upper() == "ALTER" and len(parts) >= 4:
                        table, col = parts[2], parts[5]
                        if _column_exists(conn, table, col):
                            continue
                    try:
                        conn.execute(text(s))
                        conn.commit()
                    except Exception:
                        pass
            elif step == 3:
                for stmt in MIGRATIONS[2].strip().split(";"):
                    s = stmt.strip()
                    if not s:
                        continue
                    if "item_gasto" in s and _column_exists(conn, "item_gasto", "mercado"):
                        continue
                    try:
                        conn.execute(text(s))
                        conn.commit()
                    except Exception:
                        pass

            conn.execute(
                text(
                    "INSERT OR REPLACE INTO app_setting (key, value) VALUES ('schema_version', :v)"
                ),
                {"v": str(step)},
            )
            conn.commit()
            current = step


def get_setting(db, key, default=None):
    from sqlalchemy import text

    with db.engine.connect() as conn:
        if not _table_exists(conn, "app_setting"):
            return default
        row = conn.execute(
            text("SELECT value FROM app_setting WHERE key=:k"), {"k": key}
        ).fetchone()
        return row[0] if row else default


def set_setting(db, key, value):
    from sqlalchemy import text

    with db.engine.connect() as conn:
        conn.execute(
            text("INSERT OR REPLACE INTO app_setting (key, value) VALUES (:k, :v)"),
            {"k": key, "v": str(value)},
        )
        conn.commit()
