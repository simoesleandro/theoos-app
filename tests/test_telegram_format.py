"""Testes de formatação Telegram."""
import os
import sys
from datetime import date
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from theoos import telegram_format as tf  # noqa: E402


def test_format_cupom_groups_by_category():
    msg = tf.format_cupom_html(
        "Mercado Teste",
        [
            {"nome": "LEITE", "nome_normalizado": "Leite", "categoria": "Supermercado",
             "quantidade": 2, "unidade": "un", "valor_total": 10.0},
            {"nome": "BANANA", "categoria": "Hortifruti",
             "quantidade": 1, "unidade": "kg", "valor_total": 5.5},
        ],
        total=15.5,
    )
    assert "Cupom registrado" in msg
    assert "Supermercado" in msg
    assert "Hortifruti" in msg
    assert "R$ 15,50" in msg


def test_format_contas_vencidas_groups():
    contas = [
        SimpleNamespace(nome="Luz", categoria="Luz", valor=100.0, data_vencimento=date(2026, 6, 5)),
        SimpleNamespace(nome="Net", categoria="Internet", valor=80.0, data_vencimento=date(2026, 6, 4)),
    ]
    msg = tf.format_contas_vencidas_html(contas, hoje=date(2026, 6, 6))
    assert "Contas vencidas" in msg
    assert "Luz" in msg
    assert "R$ 180,00" in msg


def test_format_variacao_splits_up_down():
    msg = tf.format_variacao_precos_html([
        {"produto": "Arroz", "subiu": True, "pct": 10, "preco_anterior": 5, "preco_recente": 5.5},
        {"produto": "Feijão", "subiu": False, "pct": 8, "preco_anterior": 8, "preco_recente": 7.36},
    ])
    assert "blockquote expandable" in msg
    assert "Subiram" in msg
    assert "Baixaram" in msg


def test_format_orcamento_html():
    status = [
        {"categoria": "Supermercado", "pct": 90, "gasto": 900, "limite": 1000, "alerta": True},
        {"categoria": "Luz", "pct": 40, "gasto": 200, "limite": 500, "alerta": False},
    ]
    msg = tf.format_orcamento_html(status)
    assert "Orçamento" in msg
    assert "Supermercado" in msg
    assert "▓" in msg


def test_format_start_html():
    msg = tf.format_start_html()
    assert "ThéoOS" in msg
    assert "blockquote expandable" in msg
    assert "executar" in msg
    kb = tf.help_commands_keyboard()
    assert kb is not None
    assert kb.keyboard[0][0].callback_data.startswith("menu:")


def test_format_ajuda_html():
    msg = tf.format_ajuda_html()
    assert "Guia interativo" in msg
    assert "executar" in msg


def test_format_help_detail_html():
    msg = tf.format_help_detail_html("comprar", "start")
    assert "Adicionar à lista" in msg
    assert "/comprar Frango" in msg


def test_format_semana_cards_and_vencidas():
    from datetime import date

    contas = [
        SimpleNamespace(
            nome="Luz", categoria="Luz", valor=100.0,
            data_vencimento=date(2026, 6, 5),
        ),
        SimpleNamespace(
            nome="Internet", categoria="Internet", valor=80.0,
            data_vencimento=date(2026, 6, 10),
        ),
    ]
    semana = {"contas": contas, "receber": [], "total_pagar": 180.0, "total_receber": 0}
    msg = tf.format_semana_html(semana, hoje=date(2026, 6, 6))
    assert "Agenda financeira" in msg
    assert "blockquote expandable" in msg
    assert "Vencidas" in msg
    assert "10/06" in msg
    assert "R$ 180,00" in msg
