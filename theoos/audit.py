"""Log mínimo de ações destrutivas."""
from sqlalchemy import text

from theoos.db_migrate import _table_exists


def log_action(db, action, entity, entity_id=None, detail=None, actor=None):
    actor = actor or "web"
    with db.engine.connect() as conn:
        if not _table_exists(conn, "audit_log"):
            return
        conn.execute(
            text(
                "INSERT INTO audit_log (action, entity, entity_id, detail, actor) "
                "VALUES (:a, :e, :eid, :d, :actor)"
            ),
            {
                "a": action,
                "e": entity,
                "eid": entity_id,
                "d": detail,
                "actor": actor,
            },
        )
        conn.commit()


def recent_logs(db, limit=30):
    from sqlalchemy import text

    with db.engine.connect() as conn:
        if not _table_exists(conn, "audit_log"):
            return []
        rows = conn.execute(
            text(
                "SELECT action, entity, entity_id, detail, actor, created_at "
                "FROM audit_log ORDER BY id DESC LIMIT :lim"
            ),
            {"lim": limit},
        ).fetchall()
        return [
            {
                "action": r[0],
                "entity": r[1],
                "entity_id": r[2],
                "detail": r[3],
                "actor": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]
