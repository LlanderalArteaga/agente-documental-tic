"""Aplicación académica LOCAL. No desplegar públicamente sin autenticación de usuarios."""
from pathlib import Path
from ipaddress import ip_address
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.models.documento import AskRequest, AskResponse, LoginRequest
from app.services.sync_service import SyncService
from app.services.agent_service import AgentService
import os
import hmac
import secrets
from fastapi.responses import JSONResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title="Archivo TIC IA", version="1.0.0")
app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")

def local_only(request: Request):
    """Defensa básica para el laboratorio; no equivale a autenticación pública."""
    host = request.client.host if request.client else ""
    try:
        if not ip_address(host).is_loopback: raise ValueError()
    except ValueError:
        raise HTTPException(status_code=403, detail="Sincronización disponible solo desde localhost")
    key = settings.local_admin_key
    if key and request.headers.get("X-Admin-Key") != key:
        raise HTTPException(status_code=401, detail="Clave administrativa incorrecta")

@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")

@app.get("/api/health")
def health():
    return {"status": "ok", "configured": bool(settings.openai_api_key and settings.drive_folder_id)}


@app.post("/api/login")
def login(payload: LoginRequest):
    expected_key = settings.local_admin_key

    if not expected_key:
        raise HTTPException(
            status_code=503,
            detail="Falta configurar LOCAL_ADMIN_KEY."
        )

    if not hmac.compare_digest(payload.key, expected_key):
        raise HTTPException(
            status_code=401,
            detail="Clave incorrecta."
        )

    serializer = get_session_serializer()
    token = serializer.dumps({"authenticated": True})

    response = JSONResponse({"success": True})
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=bool(os.getenv("VERCEL")),
        samesite="strict",
        max_age=SESSION_MAX_AGE,
        path="/"
    )
    return response


@app.get("/api/documents")
def documents():
    import json

    public_manifest = ROOT / "data" / "manifest.public.json"

    if public_manifest.exists():
        with public_manifest.open("r", encoding="utf-8") as f:
            doc = json.load(f)
        documents_list = doc.get("documents", [])
    else:
        doc = SyncService.load_manifest()
        documents_list = list(doc.get("documents", {}).values())

    local_manifest = SyncService.load_manifest()

    return {
        "documents": documents_list,
        "indexed": len(documents_list),
        "vector_store_configured": bool(
            settings.vector_store_id or local_manifest.get("vector_store_id")
        )
    }


SESSION_COOKIE = "tic_session"
SESSION_MAX_AGE = 3600

def get_session_serializer():
    secret = os.getenv("SESSION_SECRET", "")
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Falta configurar SESSION_SECRET."
        )
    return URLSafeTimedSerializer(secret, salt="archivo-tic-session")

def require_api_key(request: Request):
    if not settings.local_admin_key:
        raise HTTPException(
            status_code=503,
            detail="Falta configurar LOCAL_ADMIN_KEY."
        )

    serializer = get_session_serializer()
    token = request.cookies.get(SESSION_COOKIE, "")

    try:
        session = serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        raise HTTPException(
            status_code=401,
            detail="Inicia sesión para consultar el agente."
        )

    if session.get("authenticated") is not True:
        raise HTTPException(status_code=401, detail="Sesión no válida.")


@app.post(
    "/api/ask",
    response_model=AskResponse,
    dependencies=[Depends(require_api_key)]
)
def ask(payload: AskRequest):
    try:
        if not settings.openai_api_key: raise ValueError("Falta OPENAI_API_KEY")
        return AgentService().ask(payload.question, payload.use_search)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=502, detail="Error al consultar OpenAI. Revisa el registro local.")

@app.post("/api/sync", dependencies=[Depends(local_only)])
def sync():
    try:
        if not settings.openai_api_key: raise ValueError("Falta OPENAI_API_KEY")
        return SyncService().sync()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Sincronización fallida: {exc}")
