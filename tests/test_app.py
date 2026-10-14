from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from types import SimpleNamespace
import app.main as main_module

client = TestClient(app)

def test_home():
    r = client.get("/")
    assert r.status_code == 200
    assert "Archivo TIC" in r.text

def test_health():
    assert client.get("/api/health").status_code == 200

def test_documents():
    r = client.get("/api/documents")
    assert r.status_code == 200
    assert isinstance(r.json()["documents"], list)



def test_question_validation(monkeypatch):
    import app.main as main_module
    from types import SimpleNamespace
    from itsdangerous import URLSafeTimedSerializer

    monkeypatch.setattr(
        main_module,
        "settings",
        SimpleNamespace(
            local_admin_key="clave-de-prueba",
            openai_api_key="",
            vector_store_id=""
        )
    )
    monkeypatch.setenv("SESSION_SECRET", "secreto-temporal-para-pruebas")

    serializer = URLSafeTimedSerializer(
        "secreto-temporal-para-pruebas",
        salt="archivo-tic-session"
    )
    token = serializer.dumps({"authenticated": True})

    r = client.post(
        "/api/ask",
        json={"question": "a"},
        cookies={"tic_session": token}
    )

    assert r.status_code == 422



def test_sync_not_public():
    # FastAPI TestClient IP ficticia no loopback: bloqueado por diseño.
    r = client.post("/api/sync")
    assert r.status_code == 403

def test_auth_requires_key():
    r = client.post("/api/ask", json={"question": "Pregunta válida"})
    assert r.status_code in (401, 503)