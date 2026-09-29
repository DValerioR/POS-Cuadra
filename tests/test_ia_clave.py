"""Clave de la API de Claude desde el programa: se guarda en el .env (aquí
uno temporal), nunca se regresa completa y solo la maneja un administrador."""

import pytest

from app.core import config
from app.core.config import settings

CLAVE = "sk-ant-api03-" + "a" * 40 + "WXYZ"


@pytest.fixture(autouse=True)
def env_temporal(tmp_path, monkeypatch):
    ruta = tmp_path / ".env"
    ruta.write_text("DATABASE_URL=postgresql+psycopg://x\nHORAS_SESION=12\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_PATH", ruta)
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    return ruta


def test_guardar_escribe_el_env_y_no_regresa_la_clave(como_admin, env_temporal):
    r = como_admin.put("/ia/clave", json={"clave": f"  {CLAVE}  "})
    assert r.status_code == 200
    assert r.json() == {"configurada": True, "termina_en": "WXYZ", "modelo": settings.modelo_ia}
    assert CLAVE not in r.text.replace("WXYZ", "")
    contenido = env_temporal.read_text(encoding="utf-8").splitlines()
    assert contenido == ["DATABASE_URL=postgresql+psycopg://x", "HORAS_SESION=12", f"ANTHROPIC_API_KEY={CLAVE}"]
    assert settings.anthropic_api_key == CLAVE  # se usa sin reiniciar


def test_reemplazar_y_quitar(como_admin, env_temporal):
    como_admin.put("/ia/clave", json={"clave": CLAVE})
    otra = CLAVE[:-4] + "1234"
    como_admin.put("/ia/clave", json={"clave": otra})
    assert env_temporal.read_text(encoding="utf-8").count("ANTHROPIC_API_KEY") == 1
    assert como_admin.delete("/ia/clave").json()["configurada"] is False
    assert "ANTHROPIC_API_KEY" not in env_temporal.read_text(encoding="utf-8")
    assert "HORAS_SESION=12" in env_temporal.read_text(encoding="utf-8")


@pytest.mark.parametrize("mala", ["hola", "sk-ant-corta", f"{CLAVE}\nOTRA=1", f"{CLAVE} extra", "sk-ant-" + "a" * 30 + "="])
def test_formato_invalido(como_admin, env_temporal, mala):
    assert como_admin.put("/ia/clave", json={"clave": mala}).status_code == 409
    assert "ANTHROPIC_API_KEY" not in env_temporal.read_text(encoding="utf-8")


def test_solo_admin(como_mostrador, como_bodega):
    for cliente in (como_mostrador, como_bodega):
        assert cliente.put("/ia/clave", json={"clave": CLAVE}).status_code == 403
        assert cliente.delete("/ia/clave").status_code == 403
        assert cliente.post("/ia/probar").status_code == 403


def test_estado_para_bodega_sin_los_ultimos_caracteres(como_admin, como_bodega):
    como_admin.put("/ia/clave", json={"clave": CLAVE})
    assert como_bodega.get("/ia/estado").json()["termina_en"] is None
    assert como_bodega.get("/ia/estado").json()["configurada"] is True


def test_probar_sin_clave(como_admin):
    assert como_admin.post("/ia/probar").status_code == 409


def test_probar_con_clave_mala(como_admin, monkeypatch):
    import anthropic
    import httpx2

    como_admin.put("/ia/clave", json={"clave": CLAVE})

    def falla(*a, **k):
        respuesta = httpx2.Response(401, request=httpx2.Request("GET", "https://api.anthropic.com/v1/models/x"))
        raise anthropic.AuthenticationError("invalid x-api-key", response=respuesta, body=None)

    monkeypatch.setattr(anthropic.resources.models.Models, "retrieve", falla)
    assert como_admin.post("/ia/probar").json() == {"ok": False, "mensaje": "La clave no es válida o fue revocada."}
