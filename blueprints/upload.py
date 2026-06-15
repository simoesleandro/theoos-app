"""Blueprint de upload de cupom e gestão de notas/itens."""
from __future__ import annotations
from theoos.auth import admin_required

import hashlib
import json
import os
from datetime import datetime

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.utils import secure_filename

from models import Categoria, Financas, ItemGasto, ListaCompras, db
from theoos import produtos as produtos_svc
from theoos.image_utils import (
    HEIC_SUPPORTED,
    HEIC_MIME,
    detect_mime_from_filename,
    normalize_image_for_gemini,
)
from theoos.extensions import limiter

bp = Blueprint("upload", __name__)


def _current_actor() -> str:
    from flask import session

    return session.get("theoos_actor") or "web"


@bp.route("/upload_nota", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def upload_nota():
    try:
        recentes = (
            Financas.query.filter(Financas.tipo == "debito")
            .join(ItemGasto)
            .group_by(Financas.id)
            .order_by(Financas.data.desc())
            .limit(15)
            .all()
        )
    except Exception as e:
        from theoos.logging_setup import get_logger

        get_logger(__name__).exception("Erro ao buscar cupons recentes: %s", e)
        recentes = []

    selected_cupom = None
    cupom_id = request.args.get("cupom_id", type=int)
    if cupom_id:
        selected_cupom = db.session.get(Financas, cupom_id)

    if request.method == "GET":
        return render_template("upload_nota.html", recentes=recentes, selected_cupom=selected_cupom)

    arquivo = request.files.get("nota")
    if not arquivo or not arquivo.filename:
        flash("Selecione um arquivo de imagem.", "danger")
        return redirect(url_for("upload.upload_nota"))

    img_bytes = arquivo.read()

    filename_original = arquivo.filename or ""
    mime_detectado = detect_mime_from_filename(filename_original)

    if mime_detectado in HEIC_MIME and HEIC_SUPPORTED:
        try:
            img_bytes, _ = normalize_image_for_gemini(img_bytes, filename_original)
        except Exception as e:
            from theoos.logging_setup import get_logger

            get_logger(__name__).exception("Falha ao converter HEIC: %s", e)
            flash("Não foi possível ler a imagem HEIC.", "danger")
            return redirect(url_for("upload.upload_nota"))
    elif mime_detectado == "image/heic" and not HEIC_SUPPORTED:
        flash(
            "Formato HEIC não suportado — instale pillow-heif ou use JPG/PNG.",
            "warning",
        )
        return redirect(url_for("upload.upload_nota"))

    foto_hash = hashlib.md5(img_bytes).hexdigest()
    try:
        if Financas.query.filter_by(foto_hash=foto_hash).first():
            flash("Este cupom já foi registrado anteriormente.", "warning")
            return redirect(url_for("upload.upload_nota"))
    except Exception:
        foto_hash = None

    pendentes = ListaCompras.query.filter_by(status="pendente").all()
    lista_str = ", ".join(f"[ID:{p.id} {p.item}]" for p in pendentes) or "Lista vazia."

    catalog = produtos_svc.build_catalog(db, ItemGasto, db) if False else produtos_svc.build_catalog(db, ItemGasto, None)
    catalog_block = produtos_svc.catalog_prompt_block(catalog)

    try:
        cats_db = Categoria.query.all()
        categorias_prompt = ", ".join(f"'{c.nome}'" for c in cats_db)
    except Exception:
        categorias_prompt = "'Hortifruti', 'Supermercado', 'Farmácia', 'Suplemento Alimentar', 'Outros'"

    ext = arquivo.filename.rsplit(".", 1)[-1].lower()
    mime = detect_mime_from_filename(arquivo.filename)
    if mime == "image/heic" and HEIC_SUPPORTED:
        img_bytes_normalized, mime = normalize_image_for_gemini(img_bytes, arquivo.filename)
        img_bytes = img_bytes_normalized
    elif mime == "image/heic":
        flash(
            "Formato HEIC não suportado — instale pillow-heif ou use JPG/PNG.",
            "warning",
        )
        return redirect(url_for("upload.upload_nota"))

    from google.genai import types as genai_types

    image_part = genai_types.Part.from_bytes(data=img_bytes, mime_type=mime)

    prompt = f"""
Analise a imagem e identifique TODOS os cupons fiscais visíveis (pode haver 1 ou varios).
Para CADA cupom, extraia os dados. Se houver apenas um cupom, retorne-o dentro do array "cupons" tambem.

Cruze com a lista de compras pendentes: {lista_str}
Se um item da lista foi comprado (mesmo com nome diferente), inclua o ID em ids_comprados do respectivo cupom.

Classifique cada item em UMA categoria do sistema: [{categorias_prompt}]. Escolha a que melhor se adapta.

Para cada item, além de extrair o nome original/bruto impresso no cupom (no campo "nome"), determine e inclua:
1. Um nome simplificado, limpo e padronizado em "nome_normalizado" (ex: se "LEITE UHT INT LIDER 1L", o nome_normalizado será "Leite Integral"; se "LJA PERA", será "Laranja Pera"; se "ARROZ T1 PRATO FINO 5KG", será "Arroz Branco").
2. A marca do produto no campo "marca" (ex: "Lider", "Prato Fino", "Nestlé"). Se não houver marca identificável, retorne null.
3. A unidade de medida do produto no campo "unidade" (use uma destas siglas: "un", "kg", "g", "l", "ml", "Cx"). Se não for evidente, use "un".
{catalog_block.strip()}
Retorne SOMENTE JSON puro, sem markdown:
{{"cupons":[{{"mercado":"Nome","data":"DD/MM/AAAA","total_nota":0.00,"itens":[{{"nome":"NOME ORIGINAL","nome_normalizado":"Nome Limpo","marca":"Marca ou null","quantidade":1.0,"valor_unitario":0.00,"valor_total":0.00,"categoria":"Supermercado","unidade":"un"}}],"ids_comprados":[]}}]}}
"""
    try:
        from app import _gemini_client, GEMINI_MODEL

        resposta = _gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[prompt, image_part],
        )
        texto = resposta.text.strip()
        if texto.startswith("```"):
            texto = texto.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        dados = json.loads(texto)
        _ocr_modo_usado = "gemini"
    except Exception as e:
        from theoos.ocr_offline import (
            OCRError,
            TesseractNotFoundError,
            is_available,
            parse_receipt_offline,
        )

        if is_available():
            try:
                dados = parse_receipt_offline(img_bytes)
                _ocr_modo_usado = "offline_fallback"
                from theoos.logging_setup import get_logger
                get_logger(__name__).warning("Gemini falhou (%s); usando Tesseract offline", e)
            except (TesseractNotFoundError, OCRError) as oe:
                flash(f"Erro ao processar imagem: Gemini e OCR offline indisponíveis. Detalhe: {e}", "danger")
                return redirect(url_for("upload.upload_nota"))
        else:
            flash(
                f"Erro Gemini e OCR offline não configurado. "
                f"Instale Tesseract e pip install pytesseract para fallback. Detalhe: {e}",
                "danger",
            )
            return redirect(url_for("upload.upload_nota"))

    # Normaliza resposta: aceita tanto {"cupons": [...]} quanto o formato legado
    # (objeto único com mercado/data/total_nota/itens) para retrocompatibilidade.
    if isinstance(dados, dict) and "cupons" in dados and isinstance(dados["cupons"], list):
        cupons = dados["cupons"]
    elif isinstance(dados, dict) and ("mercado" in dados or "itens" in dados):
        cupons = [dados]
    elif isinstance(dados, list):
        cupons = dados
    else:
        cupons = []

    if not cupons:
        flash("Nenhum cupom detectado na imagem.", "warning")
        return redirect(url_for("upload.upload_nota"))

    filename = secure_filename(
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_cupom_{foto_hash[:8]}.{ext}"
    )
    foto_path = None
    try:
        filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
        with open(filepath, "wb") as f:
            f.write(img_bytes)
        foto_path = filename
    except Exception as e:
        from theoos.logging_setup import get_logger

        get_logger(__name__).exception("Erro ao salvar arquivo de cupom: %s", e)

    agora = datetime.now()
    criados_ids: list[int] = []
    flash_msgs: list[str] = []

    for cupom in cupons:
        mercado = (cupom.get("mercado") or "Desconhecido").strip() or "Desconhecido"
        total = float(cupom.get("total_nota", 0.0) or 0.0)
        itens_lista = cupom.get("itens", []) or []
        ids_riscados = cupom.get("ids_comprados", []) or []

        itens_local = [dict(it) for it in itens_lista]
        produtos_svc.normalize_itens_ocr(db, ItemGasto, itens_local, None)

        data_str = (cupom.get("data") or "").strip()
        data_gasto = agora
        if data_str:
            for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
                try:
                    parsed_date = datetime.strptime(data_str, fmt)
                    data_gasto = datetime.combine(parsed_date.date(), agora.time())
                    break
                except ValueError:
                    continue

        novo_gasto = Financas(
            valor=total,
            descricao=f"IA: {mercado}",
            foto_hash=foto_hash if cupom is cupons[0] else None,
            foto_path=foto_path if cupom is cupons[0] else None,
            data=data_gasto,
            criado_por=_current_actor(),
        )
        db.session.add(novo_gasto)
        db.session.flush()

        for item in itens_local:
            cat = item.get("categoria", "Outros")
            db.session.add(
                ItemGasto(
                    financa_id=novo_gasto.id,
                    produto_id=item.get("produto_id"),
                    nome=item.get("nome", "Desconhecido"),
                    nome_normalizado=item.get("nome_normalizado"),
                    marca=item.get("marca"),
                    quantidade=float(item.get("quantidade", 1.0) or 1.0),
                    valor_unitario=float(item.get("valor_unitario", 0.0) or 0.0),
                    valor_total=float(item.get("valor_total", 0.0) or 0.0),
                    categoria=cat,
                    unidade=item.get("unidade", "un") or "un",
                    mercado=mercado[:80],
                )
            )

        for cid in ids_riscados:
            lc = db.session.get(ListaCompras, int(cid))
            if lc and lc.status == "pendente":
                lc.status = "comprado"
                lc.marcado = False

        criados_ids.append(novo_gasto.id)
        flash_msgs.append(f"{mercado} • R$ {total:.2f} ({len(itens_local)} itens)")

    db.session.commit()

    if len(cupons) == 1:
        flash(f"Cupom de {flash_msgs[0]} processado!", "success")
        return redirect(url_for("upload.upload_nota", cupom_id=criados_ids[0]))

    flash(
        f"{len(cupons)} cupons detectados: {' / '.join(flash_msgs)}",
        "success",
    )
    return redirect(url_for("upload.upload_nota"))


@bp.route("/upload_nota/editar/<int:cupom_id>", methods=["POST"])
@admin_required
def editar_cupom_header(cupom_id: int):
    cupom = db.session.get(Financas, cupom_id)
    if not cupom:
        flash("Cupom não encontrado.", "danger")
        return redirect(url_for("upload.upload_nota"))

    descricao = request.form.get("descricao", "").strip()
    data_str = request.form.get("data", "").strip()

    if not descricao:
        flash("A descrição do cupom não pode ser vazia.", "danger")
        return redirect(url_for("upload.upload_nota", cupom_id=cupom_id))

    try:
        cupom.descricao = descricao
        if data_str:
            cupom.data = datetime.strptime(data_str, "%Y-%m-%d")
        db.session.commit()
        flash("Cupom atualizado com sucesso!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao atualizar cupom: {e}", "danger")

    return redirect(url_for("upload.upload_nota", cupom_id=cupom_id))


@bp.route("/upload_nota/deletar/<int:cupom_id>", methods=["POST"])
@admin_required
def deletar_cupom(cupom_id: int):
    cupom = db.session.get(Financas, cupom_id)
    if cupom:
        if cupom.foto_path:
            caminho = os.path.join(current_app.config["UPLOAD_FOLDER"], cupom.foto_path)
            if os.path.exists(caminho):
                try:
                    os.remove(caminho)
                except Exception:
                    pass
        ItemGasto.query.filter_by(financa_id=cupom_id).delete()
        db.session.delete(cupom)
        db.session.commit()
        flash("Cupom e itens excluídos com sucesso!", "success")
    else:
        flash("Cupom não encontrado.", "danger")
    return redirect(url_for("upload.upload_nota"))


@bp.route("/upload_nota/item/editar/<int:item_id>", methods=["POST"])
@admin_required
def editar_item_cupom(item_id: int):
    item = db.session.get(ItemGasto, item_id)
    if not item:
        return jsonify({"sucesso": False, "erro": "Item não encontrado."}), 404

    nome = request.form.get("nome", "").strip()
    nome_normalizado = request.form.get("nome_normalizado", "").strip()
    marca = request.form.get("marca", "").strip()
    categoria = request.form.get("categoria", "").strip()
    unidade = request.form.get("unidade", "").strip()
    quantidade_str = request.form.get("quantidade", "").strip()

    if not nome:
        return jsonify({"sucesso": False, "erro": "O nome do produto não pode ser vazio."}), 400

    try:
        item.nome = nome
        item.nome_normalizado = nome_normalizado if nome_normalizado else None
        item.marca = marca if marca else None
        if categoria:
            item.categoria = categoria
        if unidade:
            item.unidade = unidade
        if quantidade_str:
            try:
                item.quantidade = float(quantidade_str.replace(",", "."))
                item.valor_total = item.valor_unitario * item.quantidade
            except ValueError:
                pass

        db.session.commit()

        cupom = item.nota
        if cupom:
            total_cupom = (
                db.session.query(db.func.sum(ItemGasto.valor_total))
                .filter(ItemGasto.financa_id == cupom.id)
                .scalar()
                or 0.0
            )
            cupom.valor = total_cupom
            db.session.commit()

        return jsonify(
            {
                "sucesso": True,
                "mensagem": "Item atualizado com sucesso!",
                "nome": item.nome,
                "nome_normalizado": item.nome_normalizado,
                "marca": item.marca,
                "categoria": item.categoria,
                "unidade": item.unidade,
                "quantidade": item.quantidade,
            }
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({"sucesso": False, "erro": f"Erro: {e}"}), 500


@bp.route("/upload_nota/salvar_tudo/<int:cupom_id>", methods=["POST"])
@admin_required
def salvar_tudo_cupom(cupom_id: int):
    cupom = db.session.get(Financas, cupom_id)
    if not cupom:
        return jsonify({"sucesso": False, "erro": "Cupom não encontrado."}), 404

    dados = request.get_json()
    if not dados:
        return jsonify({"sucesso": False, "erro": "Dados inválidos."}), 400

    descricao = dados.get("descricao", "").strip()
    data_str = dados.get("data", "").strip()
    itens_dados = dados.get("items", [])

    if not descricao:
        return jsonify({"sucesso": False, "erro": "A descrição do cupom não pode ser vazia."}), 400

    try:
        cupom.descricao = descricao
        if data_str:
            cupom.data = datetime.strptime(data_str, "%Y-%m-%d")

        for item_dado in itens_dados:
            item_id = item_dado.get("id")
            item = db.session.get(ItemGasto, item_id)
            if item and item.financa_id == cupom.id:
                nome = item_dado.get("nome", "").strip()
                nome_normalizado = item_dado.get("nome_normalizado", "").strip()
                marca = item_dado.get("marca", "").strip()
                categoria = item_dado.get("categoria", "").strip()
                unidade = item_dado.get("unidade", "").strip()
                quantidade = item_dado.get("quantidade")

                if nome:
                    item.nome = nome
                item.nome_normalizado = nome_normalizado if nome_normalizado else None
                item.marca = marca if marca else None
                if categoria:
                    item.categoria = categoria
                if unidade:
                    item.unidade = unidade
                if quantidade is not None:
                    try:
                        item.quantidade = float(quantidade)
                        item.valor_total = item.valor_unitario * item.quantidade
                    except (ValueError, TypeError):
                        pass

        db.session.commit()

        total_cupom = (
            db.session.query(db.func.sum(ItemGasto.valor_total))
            .filter(ItemGasto.financa_id == cupom.id)
            .scalar()
            or 0.0
        )
        cupom.valor = total_cupom
        db.session.commit()

        flash("Cupom e todos os seus itens foram atualizados com sucesso!", "success")
        return jsonify({"sucesso": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"sucesso": False, "erro": f"Erro ao salvar tudo: {e}"}), 500


@bp.route("/upload_nota/item/deletar/<int:item_id>", methods=["POST"])
@admin_required
def deletar_item_cupom(item_id: int):
    item = db.session.get(ItemGasto, item_id)
    if not item:
        return jsonify({"sucesso": False, "erro": "Item não encontrado."}), 404

    cupom = item.nota
    valor_total_item = item.valor_total

    try:
        db.session.delete(item)

        outros_itens_count = ItemGasto.query.filter_by(financa_id=cupom.id).count()
        if outros_itens_count == 0:
            if cupom.foto_path:
                caminho = os.path.join(current_app.config["UPLOAD_FOLDER"], cupom.foto_path)
                if os.path.exists(caminho):
                    try:
                        os.remove(caminho)
                    except Exception:
                        pass
            db.session.delete(cupom)
            db.session.commit()
            flash("Cupom removido por não conter mais itens.", "info")
            return jsonify(
                {
                    "sucesso": True,
                    "reload": True,
                    "mensagem": "Cupom removido por não conter mais itens.",
                }
            )
        else:
            cupom.valor = max(0.0, cupom.valor - valor_total_item)
            db.session.commit()
            return jsonify(
                {
                    "sucesso": True,
                    "reload": False,
                    "mensagem": "Item excluído com sucesso!",
                }
            )
    except Exception as e:
        db.session.rollback()
        return jsonify({"sucesso": False, "erro": f"Erro: {e}"}), 500
