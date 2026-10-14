"""Sincronización unidireccional: Drive -> OpenAI Vector Store.
Nota: eliminar archivos de un vector store puede tener consistencia eventual.
"""
import json
import os
import re
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from openai import OpenAI
from app.core.config import settings
from app.services.drive_service import DriveService

MANIFEST = Path(__file__).resolve().parents[2] / "data" / "manifest.json"
PUBLIC_MANIFEST = Path(__file__).resolve().parents[2] / "data" / "manifest.public.json"
KV_KEY = "archivo-tic:manifest"
_LOCK = threading.Lock()
SUPPORTED = {"application/pdf", "text/plain", "application/vnd.google-apps.document"}

class SyncService:
    def __init__(self, client=None, drive=None):
        self.client = client or OpenAI(api_key=settings.openai_api_key)
        self.drive = drive or DriveService()

    @staticmethod
    def load_manifest() -> dict:
        remote = SyncService._kv_command("GET", KV_KEY)
        if remote:
            try:
                return json.loads(remote)
            except (TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError("El manifiesto guardado en Upstash no es JSON válido.") from exc
        if MANIFEST.exists():
            manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        elif PUBLIC_MANIFEST.exists():
            public = json.loads(PUBLIC_MANIFEST.read_text(encoding="utf-8"))
            manifest = {
                "vector_store_id": settings.vector_store_id,
                "documents": {
                    doc.get("drive_id") or doc.get("openai_file_id"): doc
                    for doc in public.get("documents", [])
                    if doc.get("openai_file_id")
                },
            }
        else:
            manifest = {"vector_store_id": "", "documents": {}}
        if isinstance(manifest.get("documents"), list):
            manifest["documents"] = {
                doc.get("drive_id") or doc.get("openai_file_id"): doc
                for doc in manifest["documents"]
                if doc.get("openai_file_id")
            }
        return manifest

    @staticmethod
    def _kv_credentials():
        url = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")
        token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
        return url, token

    @staticmethod
    def _kv_command(command: str, *args):
        url, token = SyncService._kv_credentials()
        if not url or not token:
            return None
        body = json.dumps([command, *args]).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError("No se pudo acceder al almacenamiento persistente de Upstash.") from exc
        if "error" in result:
            raise RuntimeError("Upstash rechazó la operación del manifiesto.")
        return result.get("result")

    @staticmethod
    def save_manifest(data: dict):
        url, token = SyncService._kv_credentials()
        if url and token:
            serialized = json.dumps(data, indent=2, ensure_ascii=False)
            SyncService._kv_command("SET", KV_KEY, serialized)
            return
        if os.getenv("VERCEL"):
            raise RuntimeError(
                "Configura UPSTASH_REDIS_REST_URL y UPSTASH_REDIS_REST_TOKEN en Vercel para guardar el índice."
            )
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        tmp = MANIFEST.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, MANIFEST)

    def get_store(self, manifest):
        vector_id = settings.vector_store_id or manifest.get("vector_store_id")
        if not vector_id:
            vector_id = self.client.vector_stores.create(name="Archivo TIC IA - Documentos").id
        manifest["vector_store_id"] = vector_id
        return vector_id

    def sync(self, folder_id: str | None = None):
        if not _LOCK.acquire(blocking=False):
            raise RuntimeError("Ya existe una sincronización en curso")
        try:
            manifest = self.load_manifest()
            docs = manifest.setdefault("documents", {})
            folder_id = (folder_id or manifest.get("active_folder_id") or settings.drive_folder_id).strip()
            if not folder_id:
                raise ValueError("Pega el ID o el enlace de una carpeta de Google Drive.")
            # Accept either the folder ID or its usual Drive URL.
            if "drive.google.com" in folder_id or "docs.google.com" in folder_id:
                parsed = urllib.parse.urlparse(folder_id)
                parts = [part for part in parsed.path.split("/") if part]
                if "folders" in parts:
                    folder_id = parts[parts.index("folders") + 1]
                else:
                    raise ValueError("El enlace no parece corresponder a una carpeta de Drive.")
            if not re.fullmatch(r"[A-Za-z0-9_-]{5,256}", folder_id):
                raise ValueError("El ID de carpeta de Drive no tiene un formato válido.")
            if os.getenv("VERCEL") and not all(self._kv_credentials()):
                raise RuntimeError(
                    "Configura UPSTASH_REDIS_REST_URL y UPSTASH_REDIS_REST_TOKEN en Vercel antes de sincronizar."
                )
            store = self.get_store(manifest)
            previous_folder_id = manifest.get("active_folder_id", settings.drive_folder_id)
            switched_folder = bool(docs) and previous_folder_id != folder_id
            self.save_manifest(manifest)
            source = self.drive.list_files(folder_id)
            eligible = {x["id"]: x for x in source if x["mimeType"] in SUPPORTED}
            stats = {"added": 0, "updated": 0, "removed": 0, "unchanged": 0, "errors": []}
            for drive_id, item in eligible.items():
                previous = docs.get(drive_id)
                previous_folder = previous.get("folder_id", previous_folder_id) if previous else folder_id
                if previous and previous_folder == folder_id and previous.get("modified_time") == item.get("modifiedTime"):
                    stats["unchanged"] += 1
                    continue
                try:
                    raw, filename, _ = self.drive.get_bytes(item)
                    if not raw: raise ValueError("El archivo está vacío")
                    suffix = ".pdf" if filename.lower().endswith(".pdf") else ".txt"
                    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp:
                        temp.write(raw)
                        path = Path(temp.name)
                    try:
                        with path.open("rb") as fh:
                            upload = self.client.vector_stores.files.upload_and_poll(vector_store_id=store, file=fh)
                    finally:
                        path.unlink(missing_ok=True)
                    if upload.status != "completed": raise RuntimeError("Indexación no completada: " + upload.status)
                    # Solo se elimina la versión antigua después de indexar exitosamente la nueva.
                    if previous:
                        self.client.vector_stores.files.delete(vector_store_id=store, file_id=previous["openai_file_id"])
                    docs[drive_id] = {
                        "name": item["name"], "modified_time": item.get("modifiedTime"),
                        "mime_type": item["mimeType"], "openai_file_id": upload.id,
                        "folder_id": folder_id,
                        "url": item.get("webViewLink") or (
                            "https://docs.google.com/document/d/" + drive_id + "/edit" if item["mimeType"] == "application/vnd.google-apps.document" else "https://drive.google.com/file/d/" + drive_id + "/view")
                    }
                    self.save_manifest(manifest)
                    stats["updated" if previous else "added"] += 1
                except Exception as exc:
                    stats["errors"].append({"file": item["name"], "error": str(exc)})
            stale_ids = set()
            if not (switched_folder and stats["errors"]):
                stale_ids = {
                    drive_id for drive_id, doc in docs.items()
                    if drive_id not in eligible
                    or doc.get("folder_id", previous_folder_id) != folder_id
                }
            for drive_id in stale_ids:
                try:
                    self.client.vector_stores.files.delete(vector_store_id=store, file_id=docs[drive_id]["openai_file_id"])
                    del docs[drive_id]
                    self.save_manifest(manifest)
                    stats["removed"] += 1
                except Exception as exc:
                    stats["errors"].append({"file": drive_id, "error": str(exc)})
            if not (switched_folder and stats["errors"]):
                manifest["active_folder_id"] = folder_id
                self.save_manifest(manifest)
            return {"vector_store_id": store, "folder_id": folder_id, "stats": stats, "documents": list(docs.values())}
        finally:
            _LOCK.release()
