r"""Backup automático do ThéoOS.

Uso manual:
    python scripts/backup.py
    python scripts/backup.py --output C:\backups\theoos

Agendamento Windows (Task Scheduler):
    1. Win+R → taskschd.msc
    2. Criar Tarefa Básica
    3. Trigger: Diariamente, 03:00
    4. Action: Iniciar Programa
       Programa: C:\Users\stife\AppData\Local\Programs\Python\Python312\python.exe
       Argumentos: C:\Meus_projetos\theoos-app\scripts\backup.py
       Iniciar em: C:\Meus_projetos\theoos-app
    5. Salvar

Agendamento Linux (cron):
    0 3 * * * cd /opt/theoos && /usr/bin/python3 scripts/backup.py >> logs/backup.log 2>&1
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from theoos import backup as backup_svc  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup do ThéoOS")
    parser.add_argument(
        "--output",
        "-o",
        default=str(ROOT / "backups"),
        help="Diretório de destino (default: ./backups)",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=14,
        help="Manter últimos N backups (0 = infinito, default: 14)",
    )
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    with app.app_context():
        buf = backup_svc.create_backup_zip(app)
    fname = f"theoos-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    fpath = out_dir / fname
    fpath.write_bytes(buf.read())
    print(f"OK backup gravado: {fpath} ({fpath.stat().st_size:,} bytes)")

    if args.keep > 0:
        backups = sorted(out_dir.glob("theoos-backup-*.zip"), reverse=True)
        for old in backups[args.keep:]:
            try:
                old.unlink()
                print(f"  removido backup antigo: {old.name}")
            except OSError as e:
                print(f"  não foi possível remover {old}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
