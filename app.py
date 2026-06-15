import os
import io
import csv
import json
import hashlib
from io import StringIO
from datetime import datetime, date, timedelta
from collections import defaultdict
from werkzeug.utils import secure_filename
from flask import Flask, render_template, redirect, url_for, request, make_response, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import text, event
from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types

from models import db
from models import (
    ListaCompras,
    Financas,
    Produto,
    ItemGasto,
    Conta,
    ContaReceber,
    Orcamento,
    Categoria,
)
from theoos.logging_setup import configure as configure_logging, get_logger
from theoos.image_utils import HEIC_SUPPORTED, HEIC_MIME, detect_mime_from_filename, normalize_image_for_gemini

load_dotenv()
configure_logging()
log = get_logger(__name__)

load_dotenv()
configure_logging()
log = get_logger(__name__)

app = Flask(__name__)

_secret_key = os.getenv('SECRET_KEY', '').strip()
if not _secret_key:
    _secret_key_path = os.path.join(app.instance_path, 'secret_key')
    if os.path.isfile(_secret_key_path):
        with open(_secret_key_path, 'r', encoding='utf-8') as f:
            _secret_key = f.read().strip()
    else:
        import secrets as _secrets
        _secret_key = _secrets.token_hex(32)
        os.makedirs(app.instance_path, exist_ok=True)
        with open(_secret_key_path, 'w', encoding='utf-8') as f:
            f.write(_secret_key)
        log.warning("SECRET_KEY ausente no .env — gerada chave aleatória em %s", _secret_key_path)
app.secret_key = _secret_key

app.config['WTF_CSRF_TIME_LIMIT'] = 60 * 60 * 8
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024
app.config['WTF_CSRF_SSL_STRICT'] = False

csrf = CSRFProtect(app)

# Gemini client (compartilhado com bot.py)
_gemini_client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
GEMINI_MODEL = 'gemini-2.5-flash'

CATEGORIAS_LISTA = ['Hortifruti', 'Supermercado', 'Farmácia', 'Suplemento Alimentar', 'Outros']

CATEGORY_CHIP = {
    'Hortifruti': 'chip-success',
    'Supermercado': 'chip-brand',
    'Farmácia': 'chip-danger',
    'Suplemento Alimentar': 'chip-info',
    'Luz': 'chip-warning',
    'Internet': 'chip-info',
    'Condomínio': 'chip-warning',
    'Cartão de Crédito': 'chip-danger',
    'Atividades Théo': 'chip-brand',
    'Veterinário': 'chip-info',
    'Combustível': 'chip-warning',
    'Vacinas': 'chip-info',
    'Contas Fixas': 'chip-neutral',
    'Outros': 'chip-neutral',
}


def chip_class(categoria):
    if not categoria:
        return 'chip-neutral'
    return CATEGORY_CHIP.get(categoria.strip(), 'chip-neutral')


app.jinja_env.globals['chip_class'] = chip_class

UPLOAD_FOLDER = 'static/uploads/boletos'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///theoos.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)


def _set_sqlite_pragmas(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


from sqlalchemy.engine import Engine as _Engine

event.listen(_Engine, "connect", _set_sqlite_pragmas)


with app.app_context():
    db.create_all()
    # Pre-populate Categoria table if empty
    try:
        if not Categoria.query.first():
            default_categories = [
                'Hortifruti', 'Supermercado', 'Farmácia', 'Suplemento Alimentar',
                'Luz', 'Internet', 'Condomínio', 'Cartão de Crédito',
                'Atividades Théo', 'Veterinário', 'Combustível', 'Vacinas',
                'Contas Fixas', 'Outros'
            ]
            for cat_nome in default_categories:
                db.session.add(Categoria(nome=cat_nome))
            db.session.commit()
    except Exception as e:
        log.exception("Erro ao pre-popular categorias: %s", e)
    from theoos.db_migrate import run_migrations
    from theoos.recurring import run_monthly_generation
    run_migrations(db)
    try:
        from theoos import produtos as produtos_svc
        produtos_svc.seed_catalog_from_history(db, Produto, ItemGasto)
    except Exception as e:
        log.exception("Seed catálogo produtos: %s", e)
    try:
        run_monthly_generation(db, Conta, ContaReceber)
    except Exception as e:
        log.exception("Recorrência mensal: %s", e)
    # Migrations legadas para colunas antigas
    with db.engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE financas ADD COLUMN tipo TEXT DEFAULT 'debito'"))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text('ALTER TABLE financas ADD COLUMN foto_hash TEXT'))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text('ALTER TABLE financas ADD COLUMN foto_path TEXT'))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text('CREATE INDEX IF NOT EXISTS idx_item_gasto_nome ON item_gasto(nome)'))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text('ALTER TABLE item_gasto ADD COLUMN nome_normalizado TEXT'))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text('ALTER TABLE item_gasto ADD COLUMN marca TEXT'))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text('ALTER TABLE lista_compras ADD COLUMN marca TEXT'))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text('ALTER TABLE lista_compras ADD COLUMN marcado INTEGER NOT NULL DEFAULT 0'))
            conn.commit()
        except Exception:
            pass

from flask import session as flask_session
from theoos import auth as theoos_auth

theoos_auth.init_app(app, db)

# Blueprints
from blueprints.dashboard import bp as dashboard_bp  # noqa: E402
from blueprints.lista import bp as lista_bp  # noqa: E402
from blueprints.contas import bp as contas_bp  # noqa: E402
from blueprints.receber import bp as receber_bp  # noqa: E402
from blueprints.orcamento import bp as orcamento_bp  # noqa: E402
from blueprints.relatorios import bp as relatorios_bp  # noqa: E402
from blueprints.upload import bp as upload_bp  # noqa: E402
from blueprints.categorias import bp as categorias_bp  # noqa: E402
from blueprints.api import bp as api_bp  # noqa: E402
from blueprints.config import bp as config_bp  # noqa: E402
from blueprints.auth import bp as auth_bp  # noqa: E402

app.register_blueprint(dashboard_bp)
app.register_blueprint(lista_bp)
app.register_blueprint(contas_bp)
app.register_blueprint(receber_bp)
app.register_blueprint(orcamento_bp)
app.register_blueprint(relatorios_bp)
app.register_blueprint(upload_bp)
app.register_blueprint(categorias_bp)
app.register_blueprint(api_bp)
app.register_blueprint(config_bp)
app.register_blueprint(auth_bp)


def _actor():
    return flask_session.get("theoos_actor") or "web"


@app.template_filter('dinheiro')
def dinheiro_filter(val):
    if val is None:
        return "R$ 0,00"
    try:
        return f"R$ {float(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"R$ {val}"

@app.template_filter('numero')
def numero_filter(val, decimals=1):
    if val is None:
        return "0,0"
    try:
        return f"{float(val):,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"{val}"


# ── CONTEXT PROCESSOR ─────────────────────────────────────────────────────────

@app.context_processor
def inject_global_data():
    nav_pendentes = ListaCompras.query.filter_by(status='pendente').count()
    try:
        categorias_db = Categoria.query.order_by(Categoria.nome).all()
        categorias_nomes = [c.nome for c in categorias_db]
        if 'Outros' in categorias_nomes:
            categorias_nomes.remove('Outros')
            categorias_nomes.append('Outros')
    except Exception:
        categorias_nomes = ['Hortifruti', 'Supermercado', 'Farmácia', 'Suplemento Alimentar', 'Outros']
    try:
        from theoos.db_migrate import get_setting
        ui_theme = get_setting(db, 'theme', 'dark')
    except Exception:
        ui_theme = 'dark'
    return dict(
        nav_pendentes=nav_pendentes,
        categorias_sistema=categorias_nomes,
        chip_class=chip_class,
        CATEGORY_CHIP=CATEGORY_CHIP,
        ui_theme=ui_theme,
    )


# ── ROUTES ────────────────────────────────────────────────────────────────────
# Rotas via blueprints e theoos.routes. Veja blueprints/dashboard.py, etc.
# Health está em theoos/routes.py.





if __name__ == '__main__':
    port = int(os.getenv('PORT', '5000'))
    as_service = os.getenv('THEOOS_SERVICE', '').strip() in ('1', 'true', 'yes')
    debug = os.getenv('FLASK_DEBUG', '').lower() in ('1', 'true') and not as_service
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug,
        use_reloader=debug,
    )
