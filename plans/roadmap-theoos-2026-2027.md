# Roadmap ThéoOS — 2026-2027

> Sequência priorizada de trabalho após os 3 sprints de cleanup (Sprint 1-3, June 2026).
> Veja `plano-de-melhorias-theoos.md` para o que já foi feito.

## Premissas

- Single-user LAN (Leandro + esposa)
- Sem urgência de SaaS ou multi-user
- ~1-2 horas por semana disponíveis
- Já tem CI verde, 119 testes, design system maduro
- Cada fase = 1-2 sprints de 3-5 dias

---

## Fase 1 — Confiabilidade (Sprint 4-5, ~2 semanas)

**Por que primeiro**: Bloqueia tudo. Sem isso, mudanças futuras podem quebrar a casa sem você saber.

| # | Item | Esforço | Valor | Status |
|---|------|---------|-------|--------|
| 79 | Healthcheck real (checa DB + Gemini + bot) | 1h | Alto | ⬜ |
| 80 | Backup automático diário + verificação de restore | 4h | Crítico | ⬜ |
| 81 | Sentry (free tier) para error tracking | 1h | Alto | ⬜ |
| 82 | CI: pip cache + matrix (Python 3.11, 3.12, 3.13) | 2h | Médio | ⬜ |
| 83 | Testes de POSTs destrutivos (delete conta, limpar lista) | 4h | Alto | ⬜ |
| 84 | Cobertura 0→60% nos blueprints (`contas`, `receber`, `orcamento`) | 1 dia | Alto | ⬜ |
| 85 | Documentar `.env.example` com todas as vars | 30min | Médio | ⬜ |

**Resultado esperado**: Casa não quebra silenciosamente. Você sabe se algo falhou, mesmo dormindo.

### Primeiro tríptico (1 dia)
1. **Healthcheck real** — `/health` checa DB, ping Gemini API, ping Telegram bot
2. **Backup automático verificado** — script que cria ZIP e tenta restaurar em DB temporário
3. **Sentry** — capturar unhandled exceptions e enviar para dashboard Sentry.io

---

## Fase 2 — UX polimento (Sprint 6-7, ~2 semanas)

**Por que segundo**: Depois de confiável, melhore o uso diário. Você vai usar todo dia.

| # | Item | Esforço | Valor | Status |
|---|------|---------|-------|--------|
| 86 | Modal de confirmação estilizado (substituir `confirm()` JS) | 4h | Alto | ⬜ |
| 87 | Atalhos de teclado (g+d dashboard, g+l lista, ? ajuda) | 1 dia | Alto | ⬜ |
| 88 | Busca global no header (filtre qualquer coisa) | 1 dia | Alto | ⬜ |
| 89 | Paginação de tabelas longas (lista, contas) | 4h | Médio | ⬜ |
| 90 | Histórico de edições (não só deleções) no audit_log | 4h | Médio | ⬜ |
| 91 | Cache de queries com Flask-Caching (`/api/dashboard/week` 60s) | 4h | Alto | ⬜ |
| 92 | Lazy load do Chart.js + minify do CSS | 4h | Médio | ⬜ |

**Resultado esperado**: App fica gostoso de usar. Menos clicks, mais velocidade.

---

## Fase 3 — Negócio familiar (Sprint 8-9, ~2 semanas)

**Por que terceiro**: Features que a esposa vai usar, alinhadas com o dia-a-dia.

| # | Item | Esforço | Valor | Status |
|---|------|---------|-------|--------|
| 93 | Drag-and-drop na lista de compras (reordenar) | 1 dia | Alto | ⬜ |
| 94 | Saldos de conta corrente (não só contas a pagar) | 1 dia | Alto | ⬜ |
| 95 | Detecção de duplicatas melhorada (mesmo cupom, fotos diferentes) | 4h | Médio | ⬜ |
| 96 | OCR multi-idioma (prompt Gemini com idioma explícito) | 2h | Médio | ⬜ |
| 97 | Export Excel além de CSV (para planilha da esposa) | 4h | Médio | ⬜ |
| 98 | Modo "família" — perfil esposa com permissões | 2 dias | Alto | ⬜ |

**Resultado esperado**: A esposa consegue usar sem te chamar. Mais autonomia, menos interrupções.

> **Nota**: Se o app for só para você, pule para Fase 4.

---

## Fase 4 — Robustez operacional (Sprint 10-11, ~2 semanas)

**Por que quarto**: Casa está ficando mais dependente do app. Resiliência.

| # | Item | Esforço | Valor | Status |
|---|------|---------|-------|--------|
| 99 | HTTPS com Caddy reverse proxy (self-signed ou Let's Encrypt) | 1 dia | Crítico | ⬜ |
| 100 | Watchdog do Telegram (alerta se bot crashar) | 4h | Alto | ⬜ |
| 101 | Retry de OCR com fallback offline (Tesseract se Gemini falhar) | 2 dias | Alto | ⬜ |
| 102 | Migração Alembic substituir db_migrate.py | 1 dia | Médio | ⬜ |
| 103 | Mypy strict + arrumar 37 erros pré-existentes | 2 dias | Médio | ⬜ |
| 104 | Refator de funções longas (PLR0915) em OCR/insights | 1 dia | Baixo | ⬜ |

**Resultado esperado**: App aguenta queda de internet, restart, e mais uso sem drama.

---

## Fase 5 — Mobile + PWA (Sprint 12-14, ~3 semanas)

**Por que quinto**: Você vai querer usar no celular eventualmente.

| # | Item | Esforço | Valor | Status |
|---|------|---------|-------|--------|
| 105 | PWA offline completo (service worker + IndexedDB) | 1 semana | Alto | ⬜ |
| 106 | Camera capture direto no PWA (substituir upload) | 3 dias | Alto | ⬜ |
| 107 | Push notifications funcionais na LAN (com HTTPS) | 2 dias | Médio | ⬜ |
| 108 | App shell installable (manifest.json otimizado) | 1 dia | Médio | ⬜ |

**Resultado esperado**: Cupom escaneado no celular, sincroniza com desktop. Sem precisar de app nativo.

---

## Fase 6 — Inteligência (Sprint 15+, opcional)

**Por que último**: Features "nice to have", não essenciais.

| # | Item | Esforço | Valor | Status |
|---|------|---------|-------|--------|
| 109 | Categorização automática (modelo local treinado nos seus dados) | 2 semanas | Médio | ⬜ |
| 110 | Previsão de gastos (já tem `forecast_next_month`, falta UI) | 1 semana | Alto | ⬜ |
| 111 | Comparação de preços online (API tipo ZoomPreço) | 1 semana | Médio | ⬜ |
| 112 | Open Banking (PSD2) para importar extrato automaticamente | 2 semanas | Alto | ⬜ |
| 113 | Chat com Gemini sobre seus dados ("quanto gastei em farmácia em maio?") | 1 semana | Alto | ⬜ |

**Resultado esperado**: App vira "smart assistant" de finanças familiares.

---

## Resumo por valor/esforço

| Fase | Tempo | Quick wins | Trabalhos grandes | ROI |
|------|-------|-----------|-------------------|-----|
| 1 | 2 sem | Healthcheck, Sentry, .env.example | Backup verificado, cobertura | ⭐⭐⭐⭐ |
| 2 | 2 sem | Atalhos, cache, paginação | Busca global, histórico | ⭐⭐⭐⭐ |
| 3 | 2 sem | OCR multi-idioma, Excel export | Drag-drop, modo família | ⭐⭐⭐ |
| 4 | 2 sem | Watchdog, mypy strict | HTTPS, OCR fallback | ⭐⭐⭐ |
| 5 | 3 sem | — | PWA offline, camera | ⭐⭐ |
| 6 | open | — | Tudo é trabalho grande | ⭐⭐ |

---

## Recomendação de execução

**Comece pela Fase 1** (bloqueante). O tríptico de 1 dia é:
1. **Healthcheck real** — `/health` checa DB, ping Gemini, ping bot
2. **Backup verificado** — script que cria ZIP e tenta restaurar em DB temp
3. **Sentry** — capturar unhandled exceptions

Depois **Fase 2** (alto ROI no dia-a-dia). Pule Fase 3 se a esposa não usar. Fases 5-6 só quando o app for indispensável.

---

## Métricas de sucesso

- **Fase 1**: 0 alertas Sentry não-resolvidos / backup <24h
- **Fase 2**: tempo para encontrar uma transação < 5s
- **Fase 3**: esposa usa o app sem pedir ajuda
- **Fase 4**: app aguenta restart sem perder dados / zero downtime
- **Fase 5**: cupom escaneado em <10s do celular
- **Fase 6**: insights aparecem antes de você perguntar

---

## Numeração

Os itens continuam a numeração do `plano-de-melhorias-theoos.md` (que ia até 78), começando em 79. Isso permite referenciar entre documentos.

---

*Criado em 2026-06-28 após os 3 sprints de cleanup. Próxima atualização: ao final da Fase 1.*
