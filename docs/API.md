# ThéoOS — API interna

Rotas JSON e utilitárias usadas pelo painel web.

## Saúde

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/health` | `{ "ok": true, "app": "ThéoOS" }` |

## Insights

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/insights` | Cesta por loja, alertas de preço, hábitos, status do orçamento |
| GET | `/api/vencimentos` | Contas/recebíveis para lembrete web (`enabled`, `contas`, `receber`) |

## Exportação PDF

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/exportar/pdf` | PDF do mês atual; `?mes=2026-06` opcional |

## Categorias

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/api/categorias` | Body JSON `{ "nome": "..." }` — cria categoria |

## Contas (bulk)

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/api/contas/bulk_actions` | Ações em lote nas contas pendentes |

## Sugestão de produto

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/sugerir_produto?nome=...` | `{ categoria, ultimo_preco }` |

## Upload cupom (editor)

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/upload_nota/salvar_tudo/<id>` | JSON com cabeçalho e itens |
| POST | `/upload_nota/item/editar/<id>` | FormData do item |
| POST | `/upload_nota/item/deletar/<id>` | Remove item |

## Configuração e backup

| Método | Rota | Descrição |
|--------|------|-----------|
| GET/POST | `/config` | PIN, lembretes, tema, contas fixas |
| GET | `/config/backup` | Download ZIP (banco + uploads) |
| POST | `/config/restore` | Restaura ZIP |

## Exportação

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/exportar` | CSV de itens |
| GET | `/exportar/fluxo_caixa` | CSV 12 meses (despesa/receita/saldo) |

## Importação

| Método | Rota | Descrição |
|--------|------|-----------|
| GET/POST | `/importar/cartao` | CSV bancário — conciliação simples |
