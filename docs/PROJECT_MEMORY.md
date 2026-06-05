# ThéoOS — Project memory (detailed)

Chronological record of major work for humans and AI. Shorter agent summary: [AGENTS.md](../AGENTS.md).

---

## Timeline

### v1.0 (initial commit `c928ce7`)
- Core Flask app, Telegram bot, Gemini cupom OCR, lista, contas, orçamento, pesquisa, relatórios.
- WinSW XML stubs (basic python → app.py / bot.py).

### v2.0 — Redesign & platform (`c976d9a`, June 2026)

#### UX/UI
| Deliverable | Details |
|-------------|---------|
| Design system | `static/css/theoos.css` — tokens, buttons, panels, KPIs, tables, mobile |
| Base layout | `templates/base.html` — sidebar, PWA manifest, SW, Chart.js helpers |
| Macros | `empty_state`, chips, `bill_row_*` |
| Pages refactored | index, contas, receber, lista, pesquisa, relatorios, upload, orcamento, categorias |
| Relatórios | `tx-row` grid; KPI strips |
| A11y | Modal focus trap, 44px touch targets, `aria-*` on key controls |

#### Backend (`theoos/`)
| Module | Role |
|--------|------|
| `auth.py` | Session PIN; `WEB_PIN` env fallback |
| `db_migrate.py` | Schema version 3; `app_setting`; columns `meta_economia`, `mercado` |
| `backup.py` | ZIP export/import |
| `audit.py` | Transaction delete log |
| `insights.py` | `week_agenda`, `budget_status`, price alerts, habits, market charts data |
| `recurring.py` | Fixed monthly bill templates |
| `reconcile.py` | Bank CSV parse + match |
| `pdf_report.py` | Monthly PDF |
| `routes.py` | login, config, backup, APIs, exports |

#### Dashboard UX (user-requested mockup)
- Removed bulky dual-column “Esta semana” panel.
- Two cards: **Contas a vencer** / **Receitas a receber** (7-day totals in subtitle).
- Show 3 items; **+ Ver mais** expands rest inline; **Gerenciar** → `/contas` or `/receber`.
- `week_agenda`: pending items with `data_vencimento <= today+7` (includes **overdue**).
- Outline **Pagar** / **Receber** buttons.

#### Five features (single batch)
1. **Budget savings meta** — bar on `/orcamento` when `meta_economia` set.
2. **Web notifications** — `GET /api/vencimentos`, `static/js/theoos-notify.js`, config checkbox; needs secure context.
3. **PDF** — `GET /exportar/pdf`, `fpdf2` in requirements.
4. **Market charts** — `/pesquisa` horizontal bar charts (global + per search term).
5. **Bot** — `/semana`, `/orcamento` (+ scheduler for reminders/price alerts unchanged).

#### Fixes
- Dropdown z-index: `.page-header` z-index 50; `.actions-overflow[open]` z-index 200; menu z-index 300.
- Notify button: user-visible status + alerts for HTTP LAN / denied permission.

#### Windows services
- XML: Automatic, delayedAutoStart, Tcpip/Dnscache deps, restart on failure, rolling logs.
- CMD wrappers: `scripts/winsw-web.cmd`, `scripts/winsw-bot.cmd`.
- Installer: `scripts/install-winsw.ps1`.
- `app.py`: production mode when `THEOOS_SERVICE=1`.

#### Quality
- `tests/test_smoke.py` — 8 tests (health, pages, PDF, API).
- `.github/workflows/ci.yml`
- `.env.example` (no real `.env` in repo)

### v2.1 — Lista Telegram, detetive de preços, PDF v2 (June 2026)

#### Lista de compras
| Item | Details |
|------|---------|
| Web UI | `templates/lista.html` — tabela somente leitura; modal Editar (nome, marca, qtd, unidade, categoria); sem `salvar_tudo` inline |
| Autocomplete | `GET /api/sugerir_produtos?q=` — sugestões dinâmicas de produtos do histórico |
| DB | `ListaCompras.marcado` Boolean — schema **v4** em `theoos/db_migrate.py` |
| Telegram | `theoos/telegram_lista.py` + callbacks em `bot.py` / `app.py` |
| Botões TG | Adicionar item, Atualizar, Sugerir melhoria, Riscar/desriscar (`marcado`), Abrir app (URL LAN) |
| Baixa real | `status=comprado` apenas via OCR cupom ou botão “Dar baixa” web; riscar ≠ comprado |

#### Detetive de preços
| Item | Details |
|------|---------|
| Regra | `preco_unitario = valor_total / quantidade`; comparar só mesma `unidade` |
| Agrupamento | `_collapse_pesquisa_rows()` — data+loja+nome_normalizado+marca+unidade → uma linha com faixa de preço |
| UI | `templates/pesquisa.html` — colunas Qtd/Un/R$/un/Total; badge “Nx no cupom”; cards menor/maior por unidade |
| Relatórios | `templates/relatorios.html` + CSS KPI `nowrap` |
| Testes | `tests/test_insights.py` (dedupe, collapse, minmax, unit price) |

#### PDF mensal
| Item | Details |
|------|---------|
| Módulo | `theoos/pdf_report.py` — `TheoPDF`, paleta ThéoOS, KPI row 4 cards |
| Layout | `TABLE_W=182mm` fixo; `_ensure_table_space` repete header em nova página |
| Export | `theoos/routes.py` — `bytes` para resposta Flask |
| Seções | Gastos por categoria, contas pendentes, transações do mês |

#### Env
- `THEOOS_WEB_URL` no `.env` — URL LAN para botão Telegram “Abrir no app” (ex. `http://192.168.x.x:5000`).

---

## File map (post-v2)

```
appfamiliar/
├── app.py
├── bot.py
├── theoos/
│   ├── telegram_lista.py
│   └── …
├── templates/
│   ├── macros/{ui,bills}.html
│   ├── config.html, login.html, importar_cartao.html
│   └── … (pages)
├── static/
│   ├── css/theoos.css
│   ├── js/theoos-notify.js
│   ├── manifest.json, sw.js
│   └── icons/
├── scripts/          # WinSW + install
├── tests/
├── docs/             # API, DEPLOY, this file
├── AGENTS.md         # Agent quick reference
├── theoos-web.xml
└── theoos-bot.xml
```

---

## Environment variables

See `.env.example`: `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY`, `SECRET_KEY`, optional `WEB_PIN`, `THEOOS_WEB_URL`, `PORT`, `FLASK_DEBUG`.

---

## Operations cheat sheet

```bash
# Dev
python app.py
python bot.py

# Tests
python -m pytest tests/ -q

# WinSW (Admin PowerShell)
powershell -ExecutionPolicy Bypass -File scripts\install-winsw.ps1
```

---

## Open / future ideas (not implemented)

- HTTPS reverse proxy for LAN (notifications + PWA full SW scope).
- Expand service worker for offline dashboard shell.
- PDF Unicode font (DejaVu) for perfect pt-BR accents.
- Edit/delete on mobile bill cards (currently desktop table has full actions).
- Detetive: fundir nomes parecidos no mesmo cupom (ex. “Requeijão” + “Requeijão Cremoso”) sob o termo buscado.
- Exibir estado `marcado` (riscado) na lista web.

---

*Maintained after the Cursor redesign session; update this file when shipping major features.*
