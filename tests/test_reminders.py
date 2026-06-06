"""Testes de lembretes de vencimento."""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from theoos import recurring  # noqa: E402


def test_parse_reminder_days_dedupes_and_sorts():
    assert recurring.parse_reminder_days("2, 0, 2, 7") == [0, 2, 7]


def test_parse_reminder_days_fallback():
    assert recurring.parse_reminder_days("") == [0, 1, 2, 7]


def test_contas_due_for_reminder_exact_offset():
    from app import app, db, Conta

    with app.app_context():
        hoje = date.today()
        alvo = hoje + timedelta(days=2)
        c = Conta(
            nome="Teste Lembrete",
            valor=10.0,
            data_vencimento=alvo,
            status="pendente",
            categoria="Outros",
        )
        db.session.add(c)
        db.session.commit()
        cid = c.id
        try:
            found = recurring.contas_due_for_reminder(db, Conta, 2)
            assert any(x.id == cid for x in found)
        finally:
            db.session.delete(db.session.get(Conta, cid))
            db.session.commit()


def test_contas_overdue():
    from app import app, db, Conta

    with app.app_context():
        ontem = date.today() - timedelta(days=1)
        c = Conta(
            nome="Teste Vencida",
            valor=5.0,
            data_vencimento=ontem,
            status="pendente",
            categoria="Outros",
        )
        db.session.add(c)
        db.session.commit()
        cid = c.id
        try:
            found = recurring.contas_overdue(db, Conta)
            assert any(x.id == cid for x in found)
        finally:
            db.session.delete(db.session.get(Conta, cid))
            db.session.commit()
