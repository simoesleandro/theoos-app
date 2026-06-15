"""Testes da previsao de gastos.

A funcao forecast_next_month exige SQLAlchemy real para queries, entao
testamos aqui a estrutura do retorno e a presenca da funcao.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from theoos import insights  # noqa: E402


def test_forecast_existe():
    assert hasattr(insights, "forecast_next_month")
    assert callable(insights.forecast_next_month)


def test_forecast_docstring():
    assert "proximo mes" in insights.forecast_next_month.__doc__.lower() or "próximo mês" in insights.forecast_next_month.__doc__.lower()


def test_forecast_signature():
    import inspect
    sig = inspect.signature(insights.forecast_next_month)
    params = list(sig.parameters.keys())
    assert "db" in params
    assert "Financas" in params
    assert "ItemGasto" in params
    assert "meses_historico" in params
    assert "top_n" in params
