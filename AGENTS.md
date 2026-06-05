# ThéoOS — Agent & project memory

Persistent context for AI assistants and developers working on this repo.

**Repo:** https://github.com/simoesleandro/theoos-app.git  
**Last major update:** June 2026 — lista Telegram, detetive de preços, PDF mensal v2.

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

---

## Conventions for future changes

- **Minimal diffs** — match existing patterns; reuse `theoos/` and macros before duplicating Jinja.
- **No commits** unless the user asks; messages in **English**, Conventional Commits (`feat:`, `fix:`, `docs:`).
- **No** `git config` changes; no force-push to `main`.
- **Tests:** `python -m pytest tests/ -q` after substantive Python changes.
- **Manual dev:** `python app.py` (port 5000). **Production:** WinSW services, not debug mode.
- **UI copy:** Portuguese (pt-BR). **CSS:** extend `theoos.css`, avoid inline styles in new work.
- **Bill rows:** use `macros/bills.html` for pay/receive list pattern.

---

## Key routes & files

| Area | Route / file |
|------|----------------|
| Dashboard | `/` → `index.html`, `semana` from `insights.week_agenda` |
| Config | `/config` → PIN, reminders, theme, backup, recurring, web notify |
| Health | `/health` |
| PDF | `/exportar/pdf` |
| Lista Telegram | `/lista` no bot → `theoos/telegram_lista.py` |
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

---

## When stuck

1. Read `docs/DEPLOY.md` for env, WinSW, network access.
2. Read `docs/API.md` for JSON routes.
3. Check `logs/` for WinSW service output.
4. Transcript of the redesign session may exist under Cursor agent transcripts (uuid `44a6012e-...`).
