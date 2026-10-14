"""Aplicación del agente documental."""
from pathlib import Path
import hmac
import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings
from app.models.documento import AskRequest, AskResponse, LoginRequest, SyncRequest
from app.services.agent_service import AgentService
from app.services.sync_service import SyncService


ROOT = Path(__file__).resolve().parents[1]
SESSION_COOKIE = "tic_session"
SESSION_MAX_AGE = 30 * 24 * 60 * 60

app = FastAPI(title="Archivo TIC IA", version="1.0.0")
app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")


def get_session_serializer():
    secret = os.getenv("SESSION_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="Falta configurar SESSION_SECRET.")
    return URLSafeTimedSerializer(secret, salt="archivo-tic-session")


def require_api_key(request: Request):
    if not settings.local_admin_key:
        raise HTTPException(status_code=503, detail="Falta configurar LOCAL_ADMIN_KEY.")
    token = request.cookies.get(SESSION_COOKIE, "")
    try:
        session = get_session_serializer().loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=401, detail="Inicia sesión para usar el agente.")
    if session.get("authenticated") is not True:
        raise HTTPException(status_code=401, detail="Sesión no válida.")


@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "configured": bool(
            settings.openai_api_key
            and settings.local_admin_key
            and os.getenv("SESSION_SECRET")
        ),
    }


@app.get("/api/session")
def session_status(request: Request):
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token or not settings.local_admin_key or not os.getenv("SESSION_SECRET"):
        return {"authenticated": False}
    try:
        session = get_session_serializer().loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return {"authenticated": False}
    return {"authenticated": session.get("authenticated") is True}


@app.post("/api/login")
def login(payload: LoginRequest):
    expected_key = settings.local_admin_key
    if not expected_key:
        raise HTTPException(status_code=503, detail="Falta configurar LOCAL_ADMIN_KEY.")
    if not hmac.compare_digest(payload.key, expected_key):
        raise HTTPException(status_code=401, detail="Clave incorrecta.")

    token = get_session_serializer().dumps({"authenticated": True})
    response = JSONResponse({"success": True})
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=bool(os.getenv("VERCEL")),
        samesite="strict",
        max_age=SESSION_MAX_AGE,
        path="/",
    )
    return response


@app.post("/api/logout")
def logout():
    response = JSONResponse({"success": True})
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict")
    return response


@app.get("/api/documents", dependencies=[Depends(require_api_key)])
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


@app.post(
    "/api/ask",
    response_model=AskResponse,
    dependencies=[Depends(require_api_key)],
)
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


@app.post("/api/sync", dependencies=[Depends(require_api_key)])
def sync(payload: SyncRequest):
    try:
        if not settings.openai_api_key:
            raise ValueError("Falta OPENAI_API_KEY")
        return SyncService().sync(payload.folder_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Sincronización fallida: {exc}")
