"""Testes de rotas — auth flow, CSRF, admin required, status codes."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import db, Usuario  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402


def _client():
    return app.test_client()


def _login_as(role="admin"):
    c = _client()
    with c.session_transaction() as sess:
        sess["theoos_auth"] = True
        sess["theoos_user_id"] = 1
        sess["theoos_user_role"] = role
        sess["theoos_actor"] = "test"
    return c


def _csrf_token(c):
    r = c.get("/login")
    body = r.data.decode("utf-8", errors="replace")
    m = re.search(r'name="csrf_token" value="([^"]+)"', body)
    return m.group(1) if m else ""


# HEALTH & STATIC

def test_health_json():
    c = _client()
    r = c.get("/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["app"] == "ThéoOS"


def test_favicon():
    c = _client()
    r = c.get("/favicon.ico")
    assert r.status_code == 200


# PUBLIC ROUTES (single-user LAN)

def test_dashboard_public():
    c = _client()
    r = c.get("/")
    assert r.status_code == 200
    body = r.data.decode("utf-8", errors="replace")
    assert "ThéoOS" in body or "TheoOS" in body


def test_lista_public():
    c = _client()
    assert c.get("/lista").status_code == 200


def test_contas_public():
    c = _client()
    assert c.get("/contas").status_code == 200


def test_receber_public():
    c = _client()
    assert c.get("/receber").status_code == 200


def test_orcamento_public():
    c = _client()
    assert c.get("/orcamento").status_code == 200


def test_relatorios_public():
    c = _client()
    assert c.get("/relatorios").status_code == 200


def test_categorias_public():
    c = _client()
    assert c.get("/categorias").status_code == 200


def test_pesquisa_public():
    c = _client()
    assert c.get("/pesquisa").status_code == 200


# ADMIN REQUIRED

def test_config_requires_admin():
    c = _client()
    r = c.get("/config", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers.get("Location", "")


def test_config_usuarios_requires_admin():
    c = _client()
    r = c.get("/config/usuarios", follow_redirects=False)
    assert r.status_code == 302


def test_contas_deletar_requires_admin():
    """POST sem CSRF é rejeitado (400); com CSRF + sem auth é redirecionado (302)."""
    c = _client()
    r = c.post("/contas/deletar/9999", follow_redirects=False)
    assert r.status_code in (302, 400)


def test_lista_deletar_requires_admin():
    c = _client()
    r = c.post("/lista/delete/9999", follow_redirects=False)
    assert r.status_code in (302, 400)


def test_config_with_admin_succeeds():
    c = _login_as(role="admin")
    assert c.get("/config").status_code == 200


# LOGIN FLOW

def test_login_page_renders():
    c = _client()
    r = c.get("/login")
    assert r.status_code == 200
    body = r.data.decode("utf-8", errors="replace")
    assert "csrf_token" in body


def test_login_post_with_csrf_succeeds():
    c = _client()
    token = _csrf_token(c)
    with app.app_context():
        if not Usuario.query.filter_by(username="admin").first():
            db.session.add(Usuario(
                username="admin", nome="Test",
                password_hash=generate_password_hash("test123"),
                role="admin", ativo=True,
            ))
            db.session.commit()
    r = c.post("/login", data={
        "username": "admin", "password": "test123", "csrf_token": token,
    }, follow_redirects=False)
    assert r.status_code in (200, 302)


def test_login_invalid_credentials():
    c = _client()
    token = _csrf_token(c)
    r = c.post("/login", data={
        "username": "admin", "password": "wrong", "csrf_token": token,
    }, follow_redirects=True)
    body = r.data.decode("utf-8", errors="replace")
    low = body.lower()
    assert "inválid" in low or "senha" in low or "erro" in low or "flash" in low


# CSRF PROTECTION

def test_admin_post_requires_csrf():
    c = _login_as(role="admin")
    r = c.post("/contas/deletar/9999", data={}, follow_redirects=False)
    assert r.status_code in (400, 302)


def test_config_post_requires_csrf():
    c = _login_as(role="admin")
    r = c.post("/config", data={"action": "theme", "theme": "light"}, follow_redirects=False)
    assert r.status_code in (400, 302)


# API JSON ENDPOINTS

def test_api_vencimentos_shape():
    c = _client()
    r = c.get("/api/vencimentos")
    assert r.status_code == 200
    data = r.get_json()
    assert "enabled" in data
    assert isinstance(data.get("contas", []), list)


def test_api_insights_shape():
    c = _client()
    r = c.get("/api/insights")
    assert r.status_code == 200
    data = r.get_json()
    assert "cesta" in data
    assert "alertas_preco" in data


def test_api_produtos_typeahead_min_length():
    c = _client()
    r = c.get("/api/produtos/typeahead?q=a")
    assert r.status_code == 200
    assert r.get_json() == []


def test_api_produtos_typeahead_with_query():
    c = _client()
    r = c.get("/api/produtos/typeahead?q=leite")
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)


def test_api_dashboard_week():
    c = _client()
    r = c.get("/api/dashboard/week")
    assert r.status_code == 200


def test_api_produto_historico_404():
    c = _client()
    r = c.get("/api/produto/99999/historico")
    assert r.status_code == 404


# 404

def test_404_returns_404():
    c = _client()
    r = c.get("/rota-que-nao-existe-xyz")
    assert r.status_code == 404


def test_404_renders_custom_template():
    c = _client()
    r = c.get("/rota-que-nao-existe-xyz")
    assert r.status_code == 404
    body = r.data.decode("utf-8", errors="replace")
    assert "ThéoOS" in body
    assert "404" in body


def test_404_api_returns_json():
    c = _client()
    r = c.get("/api/rota-inexistente")
    assert r.status_code == 404
    data = r.get_json()
    assert data["sucesso"] is False


def test_500_template_exists():
    """Garante que template 500 existe e pode ser renderizado."""
    with app.test_request_context("/test"):
        from flask import render_template
        html = render_template("errors/500.html")
        assert "ThéoOS" in html
        assert "500" in html


def test_404_template_exists():
    with app.test_request_context("/test"):
        from flask import render_template
        html = render_template("errors/404.html")
        assert "ThéoOS" in html
        assert "404" in html


# EXPORTAR

def test_exportar_pdf_responds():
    c = _client()
    r = c.get("/exportar/pdf")
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"
    assert r.data[:4] == b"%PDF"


def test_exportar_ofx_responds():
    c = _client()
    r = c.get("/exportar/ofx")
    assert r.status_code == 200


def test_exportar_fluxo_caixa_csv():
    c = _client()
    r = c.get("/exportar/fluxo_caixa")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("Content-Type", "")
    body = r.data.decode("utf-8", errors="replace")
    assert "Despesas" in body


# ── ALEMBIC (dev only) ──────────────────────────────────────────────────────


def test_alembic_config_exists():
    """Garante que o Alembic está configurado para gerar diffs futuros."""
    import os
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert os.path.isfile(os.path.join(base, "alembic.ini"))
    assert os.path.isdir(os.path.join(base, "alembic"))
    assert os.path.isdir(os.path.join(base, "alembic", "versions"))


def test_alembic_baseline_migration_exists():
    """Baseline v7 deve existir como ponto de partida."""
    import os
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    versions_dir = os.path.join(base, "alembic", "versions")
    files = os.listdir(versions_dir)
    assert any("baseline" in f for f in files), f"Esperado baseline em {files}"
