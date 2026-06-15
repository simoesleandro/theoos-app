# ThéoOS — Agent & project memory

Persistent context for AI assistants and developers working on this repo.

**Repo:** https://github.com/simoesleandro/theoos-app.git  
**Last major update:** June 2026 — multi-user + HTMX dashboard + OCR offline fallback + PWA + service stability fix.

---

## What this project is

**ThéoOS** is a family household “OS”: Flask web panel on LAN (:5000) + Telegram bot. SQLite stores finances, shopping list, bills, budgets, and receipt OCR (Gemini). Runs on Windows at home; optional WinSW services start web + bot on boot.

**Author:** Leandro Simões (FIAP). **Language:** UI in Brazilian Portuguese; **commit messages in English** (Conventional Commits).

---

## Architecture (current)

```
app.py              # Main Flask app, SQLAlchemy models, most routes
bot.py              # Telegram bot (polling), schedulers, Gemini OCR/NLP
theoos/             # Service modules (imported by app + bot)
  auth.py           # WEB_PIN / session PIN
  db_migrate.py     # Schema v3, app_setting KV, incremental migrations
  backup.py         # ZIP backup (DB + uploads)
  audit.py          # Deletion audit log
  insights.py       # week_agenda, budget_status, price alerts, pesquisa, unit price
  recurring.py      # Monthly fixed bills templates
  reconcile.py      # Bank CSV import
  pdf_report.py     # Monthly PDF (fpdf2, ThéoOS layout)
  telegram_lista.py # Telegram shopping list HTML + inline keyboard
  telegram_format.py # Telegram HTML cards, /start /ajuda menus, alertas
  produtos.py       # Product catalog, OCR matching, merge
  routes.py         # login, config, backup, /api/*, /exportar/*
templates/
  base.html         # Shell, Chart.js, PWA, notifications JS
  macros/ui.html    # chips, empty_state, flash_messages
  macros/bills.html # bill_row_pagar, bill_row_receber (dashboard pattern)
static/css/theoos.css   # Design system v2 (slate + teal, light theme via data-theme)
static/js/theoos-notify.js
scripts/winsw-*.cmd # WinSW launchers
theoos-web.xml / theoos-bot.xml
```

**Do not** put secrets in git (`.env` only). DB: `instance/theoos.db`. Uploads: `static/uploads/boletos/`.

---

## Session work log (what was built)

### Phase 1–3 — UX/UI redesign
- Full design system in `static/css/theoos.css` (tokens, components, responsive).
- Refactored templates: dashboard, pesquisa, contas, lista, receber, upload, orçamento, relatórios, categorias.
- `macros/ui.html`: `empty_state`, chips, pagination; skeleton on OCR upload.
- Relatórios: `tx-row` grid aligned with dashboard.
- Focus trap on modals; theme light/dark via `app_setting` + `data-theme`.

### Platform package (`theoos/`)
- PIN auth (`WEB_PIN` or config), login template.
- Backup/restore ZIP, DB migrations (schema v3, `meta_economia`, `mercado` on items).
- Dashboard: week agenda (7 days), budget bars, price alerts, “missing habit” products.
- Insights API `/api/insights`, bank CSV `/importar/cartao`, cashflow CSV export.
- CI: `.github/workflows/ci.yml`, `tests/test_smoke.py` (8 tests).
- Docs: `docs/API.md`, `docs/DEPLOY.md`.

### Dashboard polish (user mockups)
- Replaced large “Esta semana” panel with **side-by-side compact cards**: “Contas a vencer” / “Receitas a receber”.
- Max 3 rows + **expand in place** (“+ Ver mais”) + link to full pages.
- `week_agenda` includes **overdue** pending bills (not only future dates).
- Buttons **Pagar/Receber**: `btn-outline` (teal border).
- Removed duplicate `contas_proximas` queries from `index()`.

### Feature batch (all five options)
1. **Budget meta** — `meta_economia` progress bar on `/orcamento` and dashboard.
2. **Web notifications** — `/api/vencimentos`, `theoos-notify.js`, config toggle; requires HTTPS or localhost.
3. **PDF export** — `/exportar/pdf?mes=YYYY-MM` (fpdf2).
4. **Market comparator** — charts on `/pesquisa` (global ranking + per-product by store).
5. **Telegram** — `/semana`, `/orcamento` commands.

### Bug fixes
- Dropdown **Mais / Mais ações** behind KPIs/panels: `z-index` on `.page-header` and `.actions-overflow[open]`.
- Notification button feedback (secure context, denied permission messages).

### WinSW (Windows auto-start)
- `theoos-web.xml` / `theoos-bot.xml`: Automatic, delayed start, network deps, restart on failure.
- `scripts/winsw-web.cmd`, `scripts/winsw-bot.cmd`, `scripts/install-winsw.ps1`.
- `app.py`: `THEOOS_SERVICE=1` disables Flask debug/reloader for services.

### Git
- Commit `c976d9a`: `feat: redesign UI and expand core platform capabilities` pushed to `main`.

### Phase 4 — Lista, detetive e PDF (June 2026)

#### Lista de compras (web + Telegram)
- **Web `/lista`:** removida edição inline; botão **Editar** abre modal (`data-payload` + listener; evita `tojson` em `onclick`).
- **Autocomplete:** `GET /api/sugerir_produtos?q=...` ao digitar no modal.
- **Telegram `/lista`:** `theoos/telegram_lista.py` — mensagem HTML formatada, botões inline (adicionar, atualizar, sugestão, riscar, abrir app).
- **Riscar sem baixa:** campo `ListaCompras.marcado` (schema v4); toggle `lista_toggle:{id}` no bot; baixa (`comprado`) só via cupom OCR ou “Dar baixa” na web.
- **URL Telegram:** `telegram_url_ok()` — não envia botão com `localhost`; fallback callback se `THEOOS_WEB_URL` inválido.

#### Detetive de preços (`/pesquisa`, relatórios)
- Preço justo: **R$/un = valor_total ÷ quantidade**; comparar só mesma unidade (`kg`, `un`, etc.).
- `pesquisa_resultados()` + `_collapse_pesquisa_rows()` — agrupa mesma compra (data+loja+produto+marca+unidade); badge **“Nx no cupom”** e faixa **R$ min – R$ max/un**.
- `minmax_por_unidade()` considera `preco_max` em linhas agrupadas.
- Colunas na tabela: Qtd, Un., R$/un, Total; KPI relatórios com `white-space: nowrap`.
- Testes: `tests/test_insights.py`.

#### PDF mensal (`/exportar/pdf`)
- Layout alinhado ao design ThéoOS: header teal, 4 KPI cards largura igual (`TABLE_W=182mm`).
- Tabelas categorias / contas / transações mesma largura; cabeçalho repetido em quebra de página (`_ensure_table_space`).
- Download: `bytes(pdf.output())` para Werkzeug.
- Label KPI **“LANCAM.”**; valores monetários fonte 8pt alinhados à direita.

#### Fixes
- WinSW: reinstalar de `%OneDrive%\Desktop\appfamiliar` se serviço apontar path antigo.
- Removida rota `/lista/salvar_tudo` (cache do browser pode dar 404 até hard refresh).

### Phase 0–3 — Hardening & refactor (June 2026)

**Architecture rewrite** — 17 commits, ~50 files touched.

- **Phase 0 (hygiene/security):** pinned `requirements.txt` + `requirements-dev.txt`; `pyproject.toml` (ruff/mypy/pytest); pre-commit; CI; `theoos/logging_setup.py` replaces 25 `print()` calls (rotating handler, 5×10MB); auto-gen `SECRET_KEY`; Flask-WTF CSRF on 27 forms; 7 destructive routes → POST-only; HEIC→JPEG (`theoos/image_utils.py`); SQLite WAL + `foreign_keys=ON`.
- **Phase 1 (refactor):** `models.py` extracted (8 models + uninitialized `db`); `app.py` shrank 2152→286 lines; 11 blueprints covering 50 routes; `wsgi.py` with Waitress; `bot.py:19` `datetime` import fixed.
- **Phase 2 (robustness):** bot polling backoff (`ApiTelegramException`, exponential cap 60s); `theoos/extensions.py` (limiter + csrf uninitialized); rate-limits on `/login`, `/upload_nota`, `/api/*`; global error handler (no stack exposure); `scripts/backup.py` with `--keep`.
- **Phase 3 (features):** PDF UTF-8 (`theoos/pdf_report.py`); multi-cupom OCR; Febraban boleto parser; OFX 1.x export; PWA icons + service worker v2; sparklines + forecast (`theoos/insights.py`); envelope budgeting with rollover (schema v6); Tesseract offline OCR fallback; CSV import with auto-detect delimiter/encoding/bank format; HTMX dashboard auto-refresh; **multi-user** with `Usuario` model (schema v7), `theoos/auth.py` rewrite, admin/viewer roles, `@admin_required` on 24 destructive routes, `/config/usuarios` page. Default admin auto-creates on first boot (password from `THEOOS_ADMIN_PASSWORD` env or random + logged warning).

**Test count:** 62/62 passing.

### Phase 5 — Catálogo, Telegram pro, lembretes (June 2026)

#### Catálogo de produtos (anti-duplicação OCR)
- **Schema v5:** tabela `Produto`, coluna `ItemGasto.produto_id`.
- **`theoos/produtos.py`:** matcher pós-OCR (similaridade), catálogo implícito, `normalize_itens_ocr()`, `seed_catalog_from_history()`, `merge_produtos()`.
- **Web `/categorias`:** catálogo agrupado + fusão manual de duplicatas; rotas salvar/fusão/deletar produto.
- **OCR web + Telegram:** prompt Gemini enriquecido com produtos conhecidos; matching após extração.
- Testes: `tests/test_produtos.py`.

#### Telegram — formatação e menu interativo
- **`theoos/telegram_format.py`:** HTML + blockquote expandível (cards) para todas as mensagens automáticas.
- **`/start` e `/ajuda`:** menu com **10 botões inline** (`menu:{cmd}`) que **executam** a ação real (lista, semana, orçamento, relatório, lembretes, etc.).
- **`/ajuda` e `/help`:** guia completo; cupom/texto mostram instrução; comprar ativa modo adicionar item.
- Callbacks: `menu:*` (compat `help_cmd:*`); lista mantém `lista_*`.
- **Singleton:** lock socket porta 48721 em `bot.py` — evita erro 409 (duas instâncias polling).
- Testes: `tests/test_telegram_format.py`.

#### Lembretes de contas
- Alertas diários de **contas vencidas** + vencimentos próximos (`reminder_days` configurável).
- Scheduler robusto (≥10h, 1×/dia) + catch-up ao reiniciar bot.
- **`/lembretes`:** teste manual; API `/api/vencimentos` inclui vencidas.
- Testes: `tests/test_reminders.py`.

---

## Conventions for future changes

- **Minimal diffs** — match existing patterns; reuse `theoos/` and macros before duplicating Jinja.
- **No commits** unless the user asks; messages in **English**, Conventional Commits (`feat:`, `fix:`, `docs:`).
- **No** `git config` changes; no force-push to `main`.
- **Tests:** `python -m pytest tests/ -q` after substantive Python changes.
- **Manual dev:** `python app.py` (port 5000). **Production:** WinSW services, not debug mode.
- **UI copy:** Portuguese (pt-BR). **CSS:** extend `theoos.css`, avoid inline styles in new work.
- **Bill rows:** use `macros/bills.html` for pay/receive list pattern.
- **Cost calibration** (lessons from the Phase 0–3 session): avoid re-reading large files (`app.py` was 2152 lines × 5+ reads = ~$0.10 wasted per re-read); keep thinking blocks ~2k tokens, not 20k; prefer 1 commit per phase over 5 small ones; respond in PT-BR but commit messages in English; do not regenerate boilerplate that already exists. Typical commit cost ~$0.10–0.20 once calibrated; first-time exploration of an unknown codebase can run $3+ without these constraints.

---

### Phase 6 — Service stability + template fix (June 2026)

Web service restart-looped every ~10s and bot never started. Two independent root causes plus one template bug:

#### WinSW launcher Python path
- `scripts/winsw-{web,bot}.cmd` had `C:\Users\Leand\...\Python313\python.exe` hardcoded (author's dev machine). The actual host user is `stife` with `Python312`. Bot never started (`logs/service-error.log`: 215 × "Python nao encontrado" since 14/06 17:11). Web only "worked" because `app.py` was started manually before the broken `flask_wtf` import was added.
- Always point `THEOOS_PYTHON` at the real host's Python; verify with `sc.exe qc theoos-web` after install.
- `theoos-bot.xml` used hardcoded lowercase `C:\meus_projetos\theoos-app` while `theoos-web.xml` used `%BASE%`. Standardized on `%BASE%` for both.

#### Missing pip deps after refactor
- `app.py:12` added `from flask_wtf.csrf import CSRFProtect` (Phase 0) but `flask-wtf==1.2.1` (in `requirements.txt`) was never `pip install`-ed in `Python312`. `pip list` showed only `Flask`, `Flask-SQLAlchemy`, `waitress`. Fix: `python -m pip install -r requirements.txt`.
- Lesson: after adding any new import to `app.py` / `bot.py`, run `pip install -r requirements.txt` and restart the service. The restart-loop symptom is a `ModuleNotFoundError` repeating in `theoos-web.err.log`.

#### `url_for` namespace in templates
- `templates/config.html` had `url_for('config_backup')`, `url_for('exportar')` etc. without the blueprint prefix. Flask's `BuildError` is **not** an `HTTPException`, so the global handler in `app.py:66` swallows it and silently redirects to `/` — user sees "Configurações" link → bounce to dashboard with no message.
- Always write `url_for('config.config_backup')` (or `url_for('relatorios.exportar')`, etc.). The error message includes the correct suggestion: `Did you mean 'config.config_backup' instead?`.
- Audit rule: `grep -n "url_for('" templates/*.html` and cross-check each endpoint against the blueprint's `@bp.route` lines.

#### Jinja caches templates in production
- `THEOOS_SERVICE=1` disables Flask debug, so `TEMPLATES_AUTO_RELOAD=False`. Edits to `templates/*.html` are **not** picked up until `.\theoos-web.exe restart`. A clean `/health` + 200 OK on `/config` after an edit is *not* proof the fix worked — must check the rendered body (`curl -s http://localhost:5000/login -b cookies.txt | grep "panel-title"`).
- Same applies to blueprint changes (which need a full restart anyway).

#### Admin auto-bootstrap leaks password to log
- `theoos/auth.py:105` uses `secrets.token_urlsafe(12)` when `THEOOS_ADMIN_PASSWORD` is unset, then logs the cleartext password as WARNING. The line lives forever in `logs/theoos.log` and will be committed if the log ever gets versioned. Define `THEOOS_ADMIN_PASSWORD` in `.env` before first boot, or rotate the password and `> logs/theoos.log` after first login.

#### WinSW reinstall without admin
- Non-admin sessions can't run `sc.exe delete` (Access Denied) but `theoos-web.exe uninstall` + `install` *do* work, because WinSW talks to SCM with the original installer's privileges. Path: `.\theoos-web.exe uninstall ; Start-Sleep 5 ; .\theoos-web.exe install ; .\theoos-web.exe start`. Orphan python processes from the restart loop are SYSTEM-owned and survive — only `taskkill /F /T /PID <pid>` from an elevated shell, or a reboot, removes them.

---

## Key routes & files

| Area | Route / file |
|------|----------------|
| Dashboard | `/` → `index.html`, `semana` from `insights.week_agenda` |
| Config | `/config` → PIN, reminders, theme, backup, recurring, web notify |
| Health | `/health` |
| PDF | `/exportar/pdf` |
| Lista Telegram | `/lista` no bot → `theoos/telegram_lista.py` |
| Menu Telegram | `/start`, `/ajuda` → `theoos/telegram_format.py` (botões `menu:*`) |
| Catálogo produtos | `/categorias` → `theoos/produtos.py` |
| Autocomplete lista | `/api/sugerir_produtos?q=` |
| Detetive preços | `/pesquisa` → `insights.pesquisa_resultados` |
| Notifications API | `/api/vencimentos` |
| WinSW install | `scripts/install-winsw.ps1` (Admin) |

---

## Known limitations

- Browser notifications blocked on `http://<LAN-IP>` — use `localhost` or HTTPS.
- PWA service worker only caches `/static/*` (scope under `/static/`).
- PDF uses Latin-1 safe text (accents may simplify).
- Detetive: nomes OCR distintos no mesmo cupom (ex. “Requeijão” vs “Requeijão Cremoso”) ficam em linhas separadas; mesma linha lógica agrupa por nome exato.
- Telegram botão “Abrir no app” precisa `THEOOS_WEB_URL` com IP LAN (não `localhost`).
- OneDrive path for project — WinSW `workingdirectory` is `%BASE%` (project root).
- **Não** rodar `python bot.py` manualmente com WinSW ativo — causa conflito 409 e respostas antigas.
- Bot Telegram: serviço correto é `theoos-bot.exe` (não `theoss-bot.exe`).

---

## When stuck

1. Read `docs/DEPLOY.md` for env, WinSW, network access.
2. Read `docs/API.md` for JSON routes.
3. Check `logs/` for WinSW service output.
4. Transcript of the redesign session may exist under Cursor agent transcripts (uuid `44a6012e-...`).
