"""Backup ZIP: SQLite + uploads."""
import io
import os
import zipfile
from datetime import datetime


def create_backup_zip(app):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        db_path = os.path.join(app.instance_path, "theoos.db")
        if os.path.isfile(db_path):
            zf.write(db_path, "theoos.db")
        upload_dir = app.config.get("UPLOAD_FOLDER", "")
        if upload_dir and os.path.isdir(upload_dir):
            for root, _, files in os.walk(upload_dir):
                for name in files:
                    full = os.path.join(root, name)
                    arc = os.path.join("uploads", os.path.relpath(full, upload_dir))
                    zf.write(full, arc.replace("\\", "/"))
        zf.writestr(
            "backup_meta.txt",
            f"ThéoOS backup\nGerado em: {datetime.now().isoformat()}\n",
        )
    buf.seek(0)
    return buf


def restore_from_zip(app, zip_bytes):
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        zpath = os.path.join(tmp, "restore.zip")
        with open(zpath, "wb") as f:
            f.write(zip_bytes)
        with zipfile.ZipFile(zpath, "r") as zf:
            zf.extractall(tmp)
        db_src = os.path.join(tmp, "theoos.db")
        if os.path.isfile(db_src):
            os.makedirs(app.instance_path, exist_ok=True)
            db_dest = os.path.join(app.instance_path, "theoos.db")
            shutil.copy2(db_src, db_dest)
        uploads_src = os.path.join(tmp, "uploads")
        if os.path.isdir(uploads_src):
            dest = app.config.get("UPLOAD_FOLDER", "")
            os.makedirs(dest, exist_ok=True)
            for root, _, files in os.walk(uploads_src):
                for name in files:
                    full = os.path.join(root, name)
                    rel = os.path.relpath(full, uploads_src)
                    out = os.path.join(dest, rel)
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    shutil.copy2(full, out)
    return True
