"""Aplicación del agente documental."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.models.documento import AskRequest, AskResponse, SyncRequest
from app.services.agent_service import AgentService
from app.services.sync_service import SyncService


ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title="Archivo TIC IA", version="1.0.0")
app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")


@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "configured": bool(settings.openai_api_key),
    }


@app.get("/api/documents")
def documents():
    manifest = SyncService.load_manifest()
    indexed = manifest.get("documents", {})
    documents_list = list(indexed.values()) if isinstance(indexed, dict) else indexed
    return {
        "documents": documents_list,
        "indexed": len(documents_list),
        "active_folder_id": manifest.get("active_folder_id") or settings.drive_folder_id,
        "vector_store_configured": bool(
            settings.vector_store_id or manifest.get("vector_store_id")
        ),
    }


@app.post("/api/ask", response_model=AskResponse)
def ask(payload: AskRequest):
    try:
        if not settings.openai_api_key:
            raise ValueError("Falta OPENAI_API_KEY")
        return AgentService().ask(payload.question, payload.use_search)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Error al consultar OpenAI. Revisa el registro del servidor.",
        )


@app.post("/api/sync")
def sync(payload: SyncRequest):
    try:
        if not settings.openai_api_key:
            raise ValueError("Falta OPENAI_API_KEY")
        return SyncService().sync(payload.folder_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Sincronización fallida: {exc}")
