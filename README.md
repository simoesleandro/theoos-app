# 🏠 ThéoOS

> Sistema operacional doméstico — controle financeiro familiar, lista de compras inteligente e leitura de cupom fiscal com IA.

---

## 📌 Sobre o Projeto

**ThéoOS** é um sistema de gestão doméstica desenvolvido para uso familiar no dia a dia. O nome é uma homenagem ao Théo — e o "OS" reflete exatamente o que o sistema faz: opera a casa.

Desenvolvido como projeto de portfólio durante minha transição de carreira para a área de tecnologia, com foco em Análise e Desenvolvimento de Sistemas (FIAP).

O sistema roda localmente em rede doméstica, com um bot Telegram como interface mobile — permitindo adicionar itens à lista de compras por voz, texto ou foto de cupom fiscal direto do celular.

---

## 🧠 Funcionalidades

- **Lista de compras inteligente** — adicione itens pelo dashboard, por texto livre ou por mensagem de voz via bot Telegram
- **Leitura de cupom fiscal com IA** — envie foto do cupom no Telegram → Gemini Vision extrai todos os itens, valores e categorias automaticamente
- **Controle de contas** — cadastro de contas a pagar e a receber com alertas automáticos de vencimento via Telegram
- **Controle de orçamento** — defina limites mensais por categoria e receba alertas quando atingir 80% do limite
- **Detetive de Preços** — rastreie o histórico de preços de qualquer produto com comparador de menor e maior preço entre compras
- **Relatórios financeiros** — visão consolidada de tudo que foi registrado com gráficos e filtros por período
- **Deduplicação de notas** — sistema identifica cupons já registrados por hash MD5, evitando lançamentos duplicados

---

## 🛠️ Stack

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3 |
| Web Framework | Flask + Jinja2 |
| Banco de dados | SQLite (Flask-SQLAlchemy) |
| IA | Google Gemini 2.5 Flash (Vision + NLP) |
| Bot | pyTelegramBotAPI |
| Frontend | HTML + CSS + JavaScript (vanilla) |
| Serviço Windows | WinSW (theoos-bot.xml / theoos-web.xml) |

---

## 🚀 Como Executar Localmente

### Pré-requisitos

- Python 3.10+
- Bot Telegram criado via [@BotFather](https://t.me/BotFather)
- Chave de API do [Google AI Studio](https://aistudio.google.com/)

### Instalação

```bash
# 1. Clone o repositório
git clone https://github.com/simoesleandro/theoos.git
cd theoos

# 2. Crie e ative o ambiente virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Configure as variáveis de ambiente
cp .env.example .env
# Edite o .env com suas credenciais
```

### Variáveis de ambiente

```env
# Telegram
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=

# Google Gemini
GEMINI_API_KEY=

# Flask
SECRET_KEY=
```

### Executando

```bash
# Dashboard web
python app.py

# Bot Telegram (em outro terminal)
python bot.py
```

Acesse o dashboard em `http://localhost:5000`

### Rodando como serviço Windows (opcional)

Os arquivos `theoos-web.xml` e `theoos-bot.xml` permitem instalar o dashboard e o bot como serviços Windows via [WinSW](https://github.com/winsw/winsw), iniciando automaticamente com o sistema.

---

## 📂 Estrutura do Projeto

```
theoos/
├── app.py               # Flask app — rotas, models e lógica principal
├── bot.py               # Telegram bot com Gemini NLP e Vision
├── requirements.txt
├── theoos-web.xml       # Config WinSW — serviço do dashboard
├── theoos-bot.xml       # Config WinSW — serviço do bot
├── .env.example
├── .gitignore
├── templates/           # Templates Jinja2
│   ├── base.html
│   ├── index.html
│   ├── lista.html
│   ├── contas.html
│   ├── orcamento.html
│   ├── pesquisa.html
│   ├── relatorios.html
│   └── upload_nota.html
└── static/              # CSS, JS e uploads
```

---

## 💡 Decisões de Arquitetura

**Por que Flask em vez de Django ou FastAPI?**
O sistema roda em rede local em uma máquina doméstica com recursos limitados. Flask tem footprint mínimo, sem overhead de ORM complexo ou servidor ASGI — ideal para um projeto pessoal que precisa ser simples de manter e reiniciar.

**Por que SQLite em vez de PostgreSQL?**
Banco local, uso exclusivamente familiar, sem necessidade de acesso concorrente por múltiplos usuários simultâneos. SQLite elimina a necessidade de um servidor de banco de dados separado — zero configuração, zero manutenção.

**Por que hash MD5 para deduplicação de cupons?**
O mesmo cupom pode ser fotografado mais de uma vez. O hash MD5 dos bytes da imagem garante que a mesma nota fiscal nunca seja lançada duas vezes — sem precisar armazenar a imagem original.

**Por que WinSW para o deploy local?**
O sistema precisa iniciar automaticamente com o Windows e sobreviver a reinicializações. O WinSW transforma scripts Python em serviços nativos do Windows — sem depender de terminal aberto ou task scheduler.

---

## 👤 Autor

**Leandro Simões** — Desenvolvedor em transição de carreira, estudante de Análise e Desenvolvimento de Sistemas (FIAP 2026).

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Leandro%20Sim%C3%B5es-blue?logo=linkedin)](https://www.linkedin.com/in/leandro-sim%C3%B5es-7a0b3537b/)
[![GitHub](https://img.shields.io/badge/GitHub-simoesleandro-black?logo=github)](https://github.com/simoesleandro)

---

## ⚠️ Aviso

Este projeto foi desenvolvido para uso pessoal e familiar. Os dados financeiros são privados e não são compartilhados com terceiros.
