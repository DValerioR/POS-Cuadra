"""Respaldos: pg_dump de la base (aquí, la de pruebas) a una carpeta temporal,
automáticos que se limpian, aviso si falla y descarga solo para admin."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.services import respaldos


@pytest.fixture(autouse=True)
def carpeta_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "carpeta_respaldos", str(tmp_path / "respaldos"))
    monkeypatch.setattr(settings, "carpeta_respaldos_copia", None)
    return tmp_path / "respaldos"


def test_respaldar_ahora_y_descargar(como_admin, como_mostrador, carpeta_temporal):
    assert como_mostrador.post("/respaldos").status_code == 403
    r = como_admin.post("/respaldos")
    assert r.status_code == 201, r.text
    nombre = r.json()["nombre"]
    assert nombre.endswith("_manual.dump") and r.json()["tamano"] > 1000
    assert (carpeta_temporal / nombre).read_bytes()[:5] == b"PGDMP"  # formato de pg_dump
    estado = como_admin.get("/respaldos/estado").json()
    assert estado["ultimo_archivo"] == nombre and estado["error"] is None and not estado["atrasado"]
    assert [a["nombre"] for a in estado["archivos"]] == [nombre]
    assert estado["automaticos"] is False  # nunca sobre la base de pruebas
    d = como_admin.get(f"/respaldos/archivo/{nombre}")
    assert d.status_code == 200 and d.content[:5] == b"PGDMP"
    assert como_mostrador.get(f"/respaldos/archivo/{nombre}").status_code == 403
    # Solo nombres de respaldo, nada de rutas.
    assert como_admin.get("/respaldos/archivo/..%2F..%2F.env").status_code == 404


def test_copia_extra(carpeta_temporal, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "carpeta_respaldos_copia", str(tmp_path / "usb"))
    hecho = respaldos.hacer()
    assert hecho["copia_error"] is None
    assert (tmp_path / "usb" / hecho["nombre"]).exists()


def test_si_falla_queda_el_error(como_admin, monkeypatch):
    monkeypatch.setattr(respaldos, "_pg_dump", lambda: "no-existe-pg_dump.exe")
    r = como_admin.post("/respaldos")
    assert r.status_code == 409 and "No se pudo hacer el respaldo" in r.json()["detail"]
    estado = respaldos.estado()
    assert estado["error"] and estado["necesita_atencion"] and estado["archivos"] == []


def test_automaticos_se_limpian_y_toca_cada_dia(carpeta_temporal, monkeypatch):
    monkeypatch.setattr(settings, "respaldos_a_conservar", 2)
    assert respaldos.toca_respaldo()  # nunca se ha hecho
    carpeta_temporal.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (carpeta_temporal / f"pos_2026090{i + 1}_220000_auto.dump").write_bytes(b"PGDMP viejo")
    (carpeta_temporal / "pos_20260901_120000_manual.dump").write_bytes(b"PGDMP a mano")
    hecho = respaldos.hacer(automatico=True)
    nombres = [a["nombre"] for a in respaldos.archivos()]
    assert nombres == [hecho["nombre"], "pos_20260903_220000_auto.dump", "pos_20260901_120000_manual.dump"]
    assert not respaldos.toca_respaldo()  # recién hecho
    viejo = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    estado = json.loads((carpeta_temporal / "estado.json").read_text(encoding="utf-8"))
    (carpeta_temporal / "estado.json").write_text(json.dumps({**estado, "ultimo_ok": viejo}), encoding="utf-8")
    assert respaldos.toca_respaldo()


def test_campana_avisa_solo_si_hay_automaticos(como_admin, monkeypatch):
    assert como_admin.get("/notificaciones/pendientes").json()["respaldo"] == 0  # base de pruebas: no aplica
    monkeypatch.setattr(respaldos, "automaticos_activos", lambda: True)
    r = como_admin.get("/notificaciones/pendientes").json()
    assert r["respaldo"] == 1 and r["total"] >= 1  # no hay ningún respaldo
    respaldos.hacer()
    assert como_admin.get("/notificaciones/pendientes").json()["respaldo"] == 0
