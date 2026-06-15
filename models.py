"""Modelos SQLAlchemy do ThéoOS.

`db` é criado não-inicializado aqui e bindado em `app.py` via `db.init_app(app)`,
para que os modelos possam ser importados sem app context (útil em testes e
blueprints). Models re-exportados de `app.py` para preservar `from app import
Financas, ...` em `bot.py` e em outros lugares legados.
"""
from __future__ import annotations

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class ListaCompras(db.Model):
    __tablename__ = "lista_compras"

    id = db.Column(db.Integer, primary_key=True)
    item = db.Column(db.String(100), nullable=False)
    quantidade = db.Column(db.Float, default=1.0)
    unidade = db.Column(db.String(20), default="un")
    categoria = db.Column(db.String(50), default="Outros")
    marca = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(20), default="pendente")
    marcado = db.Column(db.Boolean, default=False)
    criado_por = db.Column(db.String(50), nullable=True)


class Financas(db.Model):
    __tablename__ = "financas"

    id = db.Column(db.Integer, primary_key=True)
    valor = db.Column(db.Float, nullable=False)
    descricao = db.Column(db.String(100), nullable=False)
    data = db.Column(db.DateTime, server_default=db.func.now())
    foto_hash = db.Column(db.String(32), nullable=True)
    foto_path = db.Column(db.String(200), nullable=True)
    tipo = db.Column(
        db.String(10), nullable=False, server_default="debito", default="debito"
    )
    criado_por = db.Column(db.String(50), nullable=True)
    itens = db.relationship("ItemGasto", backref="nota", lazy=True)


class Produto(db.Model):
    __tablename__ = "produto"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    marca = db.Column(db.String(50), nullable=True)
    unidade = db.Column(db.String(20), default="un")
    categoria = db.Column(db.String(50), default="Outros")
    aliases = db.Column(db.Text, nullable=True)
    criado_em = db.Column(db.DateTime, server_default=db.func.now())


class ItemGasto(db.Model):
    __tablename__ = "item_gasto"

    id = db.Column(db.Integer, primary_key=True)
    financa_id = db.Column(db.Integer, db.ForeignKey("financas.id"), nullable=False)
    produto_id = db.Column(db.Integer, db.ForeignKey("produto.id"), nullable=True)
    nome = db.Column(db.String(100), nullable=False)
    nome_normalizado = db.Column(db.String(100), nullable=True)
    marca = db.Column(db.String(50), nullable=True)
    quantidade = db.Column(db.Float, nullable=False)
    valor_unitario = db.Column(db.Float, nullable=False)
    valor_total = db.Column(db.Float, nullable=False)
    categoria = db.Column(db.String(50), default="Outros")
    unidade = db.Column(db.String(20), default="un")
    mercado = db.Column(db.String(80), nullable=True)
    produto = db.relationship("Produto", backref="lancamentos", lazy=True)


class Conta(db.Model):
    __tablename__ = "conta"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    data_vencimento = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default="pendente")
    foto_path = db.Column(db.String(200), nullable=True)
    categoria = db.Column(db.String(50), nullable=False, default="Outros")
    criado_por = db.Column(db.String(50), nullable=True)


class ContaReceber(db.Model):
    __tablename__ = "conta_receber"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    data_esperada = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default="pendente")
    foto_path = db.Column(db.String(200), nullable=True)
    categoria = db.Column(db.String(50), nullable=False, default="Outros")
    criado_por = db.Column(db.String(50), nullable=True)


class Orcamento(db.Model):
    __tablename__ = "orcamento"

    id = db.Column(db.Integer, primary_key=True)
    categoria = db.Column(db.String(50), unique=True, nullable=False)
    limite_mensal = db.Column(db.Float, nullable=False)
    meta_economia = db.Column(db.Float, nullable=True)
    saldo_mes_anterior = db.Column(db.Float, nullable=False, default=0.0)


class Categoria(db.Model):
    __tablename__ = "categoria"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), unique=True, nullable=False)


__all__ = [
    "db",
    "ListaCompras",
    "Financas",
    "Produto",
    "ItemGasto",
    "Conta",
    "ContaReceber",
    "Orcamento",
    "Categoria",
]
