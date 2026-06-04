"""Contas fixas — geração automática mensal."""
import calendar
from datetime import date

from sqlalchemy import text

from theoos.db_migrate import _table_exists


def ensure_recurring_templates_table(db):
    with db.engine.connect() as conn:
        if _table_exists(conn, "recurring_template"):
            return
        conn.execute(
            text(
                """
                CREATE TABLE recurring_template (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL,
                    valor REAL NOT NULL,
                    categoria TEXT NOT NULL DEFAULT 'Outros',
                    dia_vencimento INTEGER NOT NULL DEFAULT 1,
                    tipo TEXT NOT NULL DEFAULT 'pagar',
                    ativo INTEGER NOT NULL DEFAULT 1,
                    ultimo_gerado TEXT
                )
                """
            )
        )
        conn.commit()


def list_templates(db):
    ensure_recurring_templates_table(db)
    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, nome, valor, categoria, dia_vencimento, tipo, ativo, ultimo_gerado "
                "FROM recurring_template ORDER BY nome"
            )
        ).fetchall()
        return [
            {
                "id": r[0],
                "nome": r[1],
                "valor": r[2],
                "categoria": r[3],
                "dia_vencimento": r[4],
                "tipo": r[5],
                "ativo": bool(r[6]),
                "ultimo_gerado": r[7],
            }
            for r in rows
        ]


def add_template(db, nome, valor, categoria, dia, tipo="pagar"):
    ensure_recurring_templates_table(db)
    dia = max(1, min(28, int(dia)))
    with db.engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO recurring_template (nome, valor, categoria, dia_vencimento, tipo) "
                "VALUES (:n, :v, :c, :d, :t)"
            ),
            {"n": nome, "v": valor, "c": categoria, "d": dia, "t": tipo},
        )
        conn.commit()


def run_monthly_generation(db, Conta, ContaReceber):
    """Cria contas do mês corrente a partir de templates ativos."""
    ensure_recurring_templates_table(db)
    hoje = date.today()
    mes_ref = f"{hoje.year}-{hoje.month:02d}"
    criados = 0

    with db.engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, nome, valor, categoria, dia_vencimento, tipo, ultimo_gerado "
                 "FROM recurring_template WHERE ativo=1")
        ).fetchall()

    for r in rows:
        tid, nome, valor, cat, dia, tipo, ultimo = r[0], r[1], r[2], r[3], r[4], r[5], r[6]
        if ultimo == mes_ref:
            continue
        year, month = hoje.year, hoje.month
        day = min(int(dia), calendar.monthrange(year, month)[1])
        venc = date(year, month, day)

        if tipo == "receber":
            exists = ContaReceber.query.filter(
                ContaReceber.nome == nome,
                ContaReceber.data_esperada == venc,
                ContaReceber.status == "pendente",
            ).first()
            if not exists:
                db.session.add(
                    ContaReceber(
                        nome=nome,
                        valor=valor,
                        data_esperada=venc,
                        categoria=cat,
                        criado_por="sistema-recorrente",
                    )
                )
                criados += 1
        else:
            exists = Conta.query.filter(
                Conta.nome == nome,
                Conta.data_vencimento == venc,
                Conta.status == "pendente",
            ).first()
            if not exists:
                db.session.add(
                    Conta(
                        nome=nome,
                        valor=valor,
                        data_vencimento=venc,
                        categoria=cat,
                        criado_por="sistema-recorrente",
                    )
                )
                criados += 1

        with db.engine.connect() as conn:
            conn.execute(
                text("UPDATE recurring_template SET ultimo_gerado=:m WHERE id=:id"),
                {"m": mes_ref, "id": tid},
            )
            conn.commit()

    if criados:
        db.session.commit()
    return criados


def contas_due_for_reminder(db, Conta, days_before):
    """Contas com vencimento em exatamente days_before dias."""
    from datetime import timedelta

    alvo = date.today() + timedelta(days=days_before)
    return Conta.query.filter(
        Conta.status == "pendente",
        Conta.data_vencimento == alvo,
    ).all()
