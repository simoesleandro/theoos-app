# ThéoOS — Deploy e rede local

## Requisitos

- Python 3.10+
- Windows: WinSW opcional (`theoos-web.xml`, `theoos-bot.xml`)
- Variáveis em `.env` (veja `.env.example`)

## Variáveis importantes

```env
SECRET_KEY=chave-longa-aleatoria
WEB_PIN=1234
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=
GEMINI_API_KEY=
```

`WEB_PIN` protege o painel na LAN. Também é possível definir PIN em **Configurações** no site.

## Executar manualmente

```bash
python app.py          # painel :5000
python bot.py          # Telegram (processo separado)
```

## Iniciar com o Windows (WinSW)

Arquivos na raiz do projeto:

| Arquivo | Serviço |
|---------|---------|
| `theoos-web.xml` + `theoos-web.exe` | Painel Flask (:5000) |
| `theoos-bot.xml` + `theoos-bot.exe` | Bot Telegram |

Scripts de arranque: `scripts/winsw-web.cmd` e `scripts/winsw-bot.cmd` (leem `.env` da pasta do projeto).

### Instalação rápida (PowerShell como Administrador)

```powershell
cd C:\Users\Leand\OneDrive\Desktop\appfamiliar
powershell -ExecutionPolicy Bypass -File scripts\install-winsw.ps1
```

O script baixa o WinSW (se faltar), instala os dois serviços e inicia.

### Instalação manual

1. Baixe [WinSW x64](https://github.com/winsw/winsw/releases) e copie duas vezes na pasta do projeto:
   - `theoos-web.exe` (ao lado de `theoos-web.xml`)
   - `theoos-bot.exe` (ao lado de `theoos-bot.xml`)
2. Ajuste o caminho do Python em `theoos-web.xml` e `theoos-bot.xml` (`THEOOS_PYTHON`) se não for Python 3.13 no caminho padrão.
3. Em **Prompt de Administrador**:

```cmd
cd C:\Users\Leand\OneDrive\Desktop\appfamiliar
theoos-web.exe install
theoos-web.exe start
theoos-bot.exe install
theoos-bot.exe start
```

### Comportamento configurado

- **Início automático** ao ligar o PC (`Automatic` + atraso leve para a rede subir).
- **Dependência** de rede (`Tcpip`, `Dnscache`).
- **Reinício** automático se o processo cair (até 3 tentativas por hora).
- **Logs** em `logs/` (WinSW + saída do serviço).
- Painel em modo **produção** (`THEOOS_SERVICE=1` desliga debug/reloader do Flask).

### Comandos úteis

```cmd
theoos-web.exe status
theoos-web.exe stop
theoos-web.exe restart
theoos-web.exe uninstall
```

(idem com `theoos-bot.exe`)

Ver também em `services.msc` → **ThéoOS - Painel Web** / **ThéoOS - Bot Telegram**.

### Antes de instalar

- Arquivo `.env` preenchido na pasta do projeto.
- `pip install -r requirements.txt` no mesmo Python usado em `THEOOS_PYTHON`.
- Pare instâncias manuais (`python app.py` / `python bot.py`) para não duplicar porta 5000 ou o bot.

## Acesso na rede

1. Descubra o IP local (`ipconfig` no Windows).
2. Acesse `http://<IP>:5000` de outro dispositivo na mesma Wi‑Fi.
3. No celular: “Adicionar à tela inicial” (PWA via `manifest.json`).

## Backup

- Painel → **Configurações** → **Baixar backup**
- Ou copie `instance/theoos.db` e `static/uploads/boletos/`

## CI

GitHub Actions em `.github/workflows/ci.yml` executa `pytest tests/`.

## Tailscale / VPN (opcional)

Para acesso fora de casa sem expor porta na internet, use [Tailscale](https://tailscale.com/) na máquina que roda o Flask e acesse o IP Tailscale na porta 5000.
