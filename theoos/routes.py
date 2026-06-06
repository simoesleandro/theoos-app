"""Rotas extras: login, config, backup, importação, insights API."""
import os
from datetime import date, datetime, timedelta

from flask import (
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from theoos import audit, backup, insights, pdf_report, reconcile, recurring
from theoos.auth import clear_pin, pin_configured, set_pin, verify_pin
from theoos.db_migrate import get_setting, set_setting


def register(app, db, models):
    ListaCompras = models["ListaCompras"]
    Financas = models["Financas"]
    ItemGasto = models["ItemGasto"]
    Conta = models["Conta"]
    ContaReceber = models["ContaReceber"]
    Orcamento = models["Orcamento"]

    def actor():
        return session.get("theoos_actor") or "web"

    @app.route("/health")
    def health():
        return jsonify({"ok": True, "app": "ThéoOS"})

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            pin = request.form.get("pin", "")
            if verify_pin(db, pin):
                session["theoos_auth"] = True
                session["theoos_actor"] = request.form.get("nome", "").strip() or "web"
                flash("Acesso liberado.", "success")
                return redirect(request.args.get("next") or url_for("index"))
            flash("PIN incorreto.", "danger")
            return redirect(url_for("login"))
        if session.get("theoos_auth"):
            return redirect(request.args.get("next") or url_for("index"))
        return render_template("login.html", pin_enabled=pin_configured(db))

    @app.route("/logout")
    def logout():
        session.clear()
        flash("Sessão encerrada.", "info")
        return redirect(url_for("login"))

    @app.route("/config", methods=["GET", "POST"])
    def config_page():
        if request.method == "POST":
            action = request.form.get("action")
            if action == "set_pin":
                p1 = request.form.get("pin", "").strip()
                p2 = request.form.get("pin_confirm", "").strip()
                if len(p1) < 4:
                    flash("PIN deve ter pelo menos 4 caracteres.", "warning")
                elif p1 != p2:
                    flash("PINs não conferem.", "danger")
                else:
                    set_pin(db, p1)
                    flash("PIN configurado.", "success")
            elif action == "clear_pin":
                clear_pin(db)
                flash("PIN removido — painel aberto na rede local.", "info")
            elif action == "reminders":
                days = request.form.get("reminder_days", "2")
                set_setting(db, "reminder_days", days)
                flash("Lembretes atualizados.", "success")
            elif action == "theme":
                theme = request.form.get("theme", "dark")
                set_setting(db, "theme", theme)
                flash("Tema salvo.", "success")
            elif action == "web_notify":
                on = "1" if request.form.get("web_notify") == "on" else "0"
                set_setting(db, "web_notify", on)
                flash("Notificações no navegador atualizadas.", "success")
            elif action == "recurring_add":
                recurring.add_template(
                    db,
                    request.form.get("nome", "").strip(),
                    float(request.form.get("valor", "0").replace(",", ".")),
                    request.form.get("categoria", "Outros"),
                    int(request.form.get("dia", 1)),
                    request.form.get("tipo", "pagar"),
                )
                flash("Conta fixa cadastrada.", "success")
            elif action == "recurring_run":
                n = recurring.run_monthly_generation(db, Conta, ContaReceber)
                flash(f"{n} lançamento(s) gerado(s) para este mês.", "success")
            return redirect(url_for("config_page"))

        reminder_days = get_setting(db, "reminder_days", "0,1,2,3,7")
        theme = get_setting(db, "theme", "dark")
        web_notify = get_setting(db, "web_notify", "1") == "1"
        templates = recurring.list_templates(db)
        logs = audit.recent_logs(db, 20)
        return render_template(
            "config.html",
            pin_enabled=pin_configured(db),
            reminder_days=reminder_days,
            theme=theme,
            web_notify=web_notify,
            recurring_templates=templates,
            audit_logs=logs,
            actor=actor(),
        )

    @app.route("/config/backup")
    def config_backup():
        buf = backup.create_backup_zip(app)
        fname = f"theoos-backup-{datetime.now().strftime('%Y%m%d-%H%M')}.zip"
        return send_zip(buf, fname)

    @app.route("/config/restore", methods=["POST"])
    def config_restore():
        f = request.files.get("backup")
        if not f:
            flash("Selecione um arquivo .zip de backup.", "danger")
            return redirect(url_for("config_page"))
        try:
            backup.restore_from_zip(app, f.read())
            flash("Backup restaurado. Reinicie o serviço se necessário.", "success")
        except Exception as e:
            flash(f"Erro ao restaurar: {e}", "danger")
        return redirect(url_for("config_page"))

    @app.route("/exportar/fluxo_caixa")
    def exportar_fluxo_caixa():
        import csv
        from io import StringIO

        hoje = date.today()
        rows = []
        for m in range(12):
            month = hoje.month - m
            year = hoje.year
            while month < 1:
                month += 12
                year -= 1
            primeiro = datetime(year, month, 1)
            if month == 12:
                ultimo = datetime(year, 12, 31, 23, 59, 59)
            else:
                ultimo = datetime(year, month + 1, 1) - timedelta(seconds=1)
            deb = (
                db.session.query(db.func.sum(Financas.valor))
                .filter(
                    Financas.tipo == "debito",
                    Financas.data >= primeiro,
                    Financas.data <= ultimo,
                )
                .scalar()
                or 0
            )
            cred = (
                db.session.query(db.func.sum(Financas.valor))
                .filter(
                    Financas.tipo == "credito",
                    Financas.data >= primeiro,
                    Financas.data <= ultimo,
                )
                .scalar()
                or 0
            )
            rows.append((f"{month:02d}/{year}", deb, cred, cred - deb))

        buf = StringIO()
        w = csv.writer(buf)
        w.writerow(["Mes", "Despesas", "Receitas", "Saldo"])
        w.writerows(reversed(rows))
        resp = make_response(buf.getvalue())
        resp.headers["Content-Type"] = "text/csv; charset=utf-8"
        resp.headers["Content-Disposition"] = "attachment; filename=fluxo_caixa.csv"
        return resp

    @app.route("/importar/cartao", methods=["GET", "POST"])
    def importar_cartao():
        if request.method == "GET":
            return render_template("importar_cartao.html")
        f = request.files.get("csv")
        if not f:
            flash("Envie um arquivo CSV.", "danger")
            return redirect(url_for("importar_cartao"))
        lancamentos = reconcile.parse_bank_csv(f.read())
        matched = reconcile.match_against_financas(lancamentos, Financas)
        novos = [x for x in matched if x.get("novo")]
        for lan in novos[:50]:
            db.session.add(
                Financas(
                    valor=lan["valor"],
                    descricao=f"CSV: {lan['descricao'][:80]}",
                    tipo="debito",
                    data=datetime.combine(lan["data"], datetime.min.time()),
                    criado_por=actor(),
                )
            )
        db.session.commit()
        flash(
            f"{len(lancamentos)} linhas lidas — {len(novos)} novos lançamentos importados.",
            "success",
        )
        return render_template(
            "importar_cartao.html", lancamentos=matched, importados=len(novos)
        )

    @app.route("/api/vencimentos")
    def api_vencimentos():
        from theoos.recurring import (
            contas_due_for_reminder,
            contas_overdue,
            parse_reminder_days,
            receber_due_for_reminder,
        )

        hoje = date.today()
        enabled = get_setting(db, "web_notify", "1") == "1"
        days_str = get_setting(db, "reminder_days", "0,1,2,7") or "0,1,2,7"
        contas_out = []
        receber_out = []
        seen_c = set()
        seen_r = set()

        for c in contas_overdue(db, Conta):
            seen_c.add(c.id)
            dias_atraso = (hoje - c.data_vencimento).days
            contas_out.append(
                {
                    "id": c.id,
                    "nome": c.nome,
                    "valor": c.valor,
                    "vencimento": c.data_vencimento.isoformat(),
                    "dias": -dias_atraso,
                    "quando": f"vencida há {dias_atraso} dia(s)",
                }
            )

        for dias in parse_reminder_days(days_str):
            for c in contas_due_for_reminder(db, Conta, dias):
                if c.id in seen_c:
                    continue
                seen_c.add(c.id)
                contas_out.append(
                    {
                        "id": c.id,
                        "nome": c.nome,
                        "valor": c.valor,
                        "vencimento": c.data_vencimento.isoformat(),
                        "dias": dias,
                        "quando": "hoje" if dias == 0 else f"em {dias} dia(s)",
                    }
                )
            for r in receber_due_for_reminder(db, ContaReceber, dias):
                if r.id in seen_r:
                    continue
                seen_r.add(r.id)
                receber_out.append(
                    {
                        "id": r.id,
                        "nome": r.nome,
                        "valor": r.valor,
                        "data": r.data_esperada.isoformat(),
                        "dias": dias,
                    }
                )

        contas_out.sort(key=lambda x: x["vencimento"])
        receber_out.sort(key=lambda x: x["data"])
        return jsonify(
            {
                "enabled": enabled,
                "hoje": hoje.isoformat(),
                "contas": contas_out,
                "receber": receber_out,
            }
        )

    @app.route("/exportar/pdf")
    def exportar_pdf():
        hoje = date.today()
        mes_param = request.args.get("mes", "")
        if mes_param and len(mes_param) == 7:
            try:
                y, m = mes_param.split("-")
                year, month = int(y), int(m)
            except ValueError:
                year, month = hoje.year, hoje.month
        else:
            year, month = hoje.year, hoje.month

        primeiro, ultimo = pdf_report.month_bounds(year, month)
        debitos = (
            db.session.query(db.func.sum(Financas.valor))
            .filter(
                Financas.tipo == "debito",
                Financas.data >= primeiro,
                Financas.data <= ultimo,
            )
            .scalar()
            or 0.0
        )
        creditos = (
            db.session.query(db.func.sum(Financas.valor))
            .filter(
                Financas.tipo == "credito",
                Financas.data >= primeiro,
                Financas.data <= ultimo,
            )
            .scalar()
            or 0.0
        )
        transacoes = []
        for n in (
            Financas.query.filter(Financas.data >= primeiro, Financas.data <= ultimo)
            .order_by(Financas.data.desc())
            .all()
        ):
            transacoes.append(
                {
                    "data": n.data.strftime("%d/%m/%Y"),
                    "descricao": n.descricao,
                    "valor": n.valor,
                    "tipo": n.tipo or "debito",
                }
            )

        gastos_cat = []
        cat_map = {}
        for item in (
            ItemGasto.query.join(Financas)
            .filter(
                Financas.data >= primeiro,
                Financas.data <= ultimo,
                Financas.tipo == "debito",
            )
            .all()
        ):
            cat = item.categoria or "Outros"
            cat_map[cat] = cat_map.get(cat, 0.0) + item.valor_total
        gastos_cat = sorted(cat_map.items(), key=lambda x: -x[1])

        contas_pendentes = []
        for c in Conta.query.filter_by(status="pendente").order_by(Conta.data_vencimento).all():
            if c.data_vencimento.year == year and c.data_vencimento.month == month:
                contas_pendentes.append(
                    {
                        "nome": c.nome,
                        "vencimento": c.data_vencimento.strftime("%d/%m/%Y"),
                        "valor": c.valor,
                    }
                )

        pdf_bytes = pdf_report.build_monthly_pdf(
            year,
            month,
            debitos,
            creditos,
            transacoes,
            gastos_cat,
            contas_pendentes,
        )
        fname = f"theoos-{year}-{month:02d}.pdf"
        if isinstance(pdf_bytes, bytearray):
            pdf_bytes = bytes(pdf_bytes)
        resp = make_response(pdf_bytes)
        resp.headers["Content-Type"] = "application/pdf"
        resp.headers["Content-Length"] = str(len(pdf_bytes))
        resp.headers["Content-Disposition"] = f'attachment; filename="{fname}"'
        return resp

    @app.route("/api/insights")
    def api_insights():
        return jsonify(
            {
                "cesta": insights.basket_estimates_by_store(
                    db, ListaCompras, ItemGasto, Financas
                ),
                "alertas_preco": insights.price_spike_alerts(
                    db, ItemGasto, Financas
                ),
                "habitos": insights.missing_habit_products(
                    db, ItemGasto, Financas
                ),
                "orcamento": insights.budget_status(
                    db, Orcamento, ItemGasto, Financas
                ),
            }
        )


def send_zip(buf, filename):
    from flask import send_file

    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename,
    )
