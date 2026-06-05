"""Smoke tests — rotas principais do ThéoOS."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, chip_class  # noqa: E402


def test_health():
    c = app.test_client()
    r = c.get("/health")
    assert r.status_code == 200
    assert r.get_json().get("ok") is True


def test_dashboard():
    c = app.test_client()
    assert c.get("/").status_code == 200


def test_core_pages():
    c = app.test_client()
    for path in (
        "/pesquisa",
        "/lista",
        "/contas",
        "/receber",
        "/orcamento",
        "/relatorios",
        "/upload_nota",
        "/categorias",
    ):
        assert c.get(path).status_code == 200, path


def test_chip_class():
    assert chip_class("Suplemento Alimentar") == "chip-info"
    assert chip_class("Hortifruti") == "chip-success"


def test_api_insights():
    c = app.test_client()
    r = c.get("/api/insights")
    assert r.status_code == 200
    data = r.get_json()
    assert "cesta" in data
    assert "alertas_preco" in data


def test_api_vencimentos():
    c = app.test_client()
    r = c.get("/api/vencimentos")
    assert r.status_code == 200
    data = r.get_json()
    assert "enabled" in data
    assert "contas" in data


def test_exportar_pdf():
    c = app.test_client()
    r = c.get("/exportar/pdf")
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"
    assert len(r.data) > 200


def test_pesquisa_mercado_page():
    c = app.test_client()
    assert c.get("/pesquisa").status_code == 200
    assert c.get("/pesquisa?q=leite").status_code == 200


def test_api_sugerir_produtos():
    c = app.test_client()
    r = c.get("/api/sugerir_produtos?q=ab")
    assert r.status_code == 200
    data = r.get_json()
    assert "itens" in data
    assert isinstance(data["itens"], list)
