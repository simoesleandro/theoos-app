"""Testes do detetive de preços."""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from theoos import insights  # noqa: E402


class _FakeNota:
    def __init__(self, dt):
        self.data = dt


class _FakeItem:
    def __init__(self, nome, qtd, total, unidade="kg", dt=None):
        self.nome = nome
        self.nome_normalizado = nome
        self.quantidade = qtd
        self.valor_total = total
        self.valor_unitario = total / qtd if qtd else 0
        self.unidade = unidade
        self.nota = _FakeNota(dt or datetime(2026, 5, 23))


def test_unit_price_from_total_and_quantity():
    item = _FakeItem("Batata Baroa", 3.4, 16.90)
    assert round(insights._unit_price(item), 2) == 4.97


def test_price_variation_entry_same_unit():
    recente = _FakeItem("Batata Baroa", 3.4, 16.90, dt=datetime(2026, 5, 30))
    anterior = _FakeItem("Batata Baroa", 1.0, 4.98, dt=datetime(2026, 5, 23))
    entry = insights._price_variation_entry("Batata Baroa", recente, anterior)
    assert entry is not None
    assert abs(entry["percentual"]) < 5


def test_price_variation_skips_different_units():
    recente = _FakeItem("Batata", 1, 10, unidade="kg")
    anterior = _FakeItem("Batata", 1, 5, unidade="un")
    assert insights._price_variation_entry("Batata", recente, anterior) is None


def test_collapse_pesquisa_rows_merges_same_day():
    from datetime import datetime as dt

    nota = _FakeNota(dt(2026, 5, 10))
    rows = [
        {
            "id": 1,
            "nome_normalizado": "Requeijao Cremoso",
            "marca": "Elege",
            "mercado": "Loja A",
            "unidade": "un",
            "quantidade": 1.0,
            "valor_total": 18.99,
            "preco_unitario": 18.99,
            "nota": nota,
            "categoria": "Supermercado",
            "nome": "Requeijao",
        },
        {
            "id": 2,
            "nome_normalizado": "Requeijao Cremoso",
            "marca": "Elege",
            "mercado": "Loja A",
            "unidade": "un",
            "quantidade": 1.0,
            "valor_total": 8.99,
            "preco_unitario": 8.99,
            "nota": nota,
            "categoria": "Supermercado",
            "nome": "Requeijao",
        },
    ]
    out = insights._collapse_pesquisa_rows(rows)
    assert len(out) == 1
    assert out[0]["agrupado"] is True
    assert out[0]["preco_min"] == 8.99
    assert out[0]["preco_max"] == 18.99


def test_minmax_por_unidade_groups_correctly():
    rows = [
        {"unidade": "un", "preco_unitario": 8.99},
        {"unidade": "un", "preco_unitario": 18.99},
        {"unidade": "kg", "preco_unitario": 4.50},
    ]
    mm = insights.minmax_por_unidade(rows)
    assert mm["un"]["min"] == 8.99
    assert mm["un"]["max"] == 18.99
    assert mm["kg"]["min"] == mm["kg"]["max"]
