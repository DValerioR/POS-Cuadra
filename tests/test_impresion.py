"""Tickets e impresión: formato ESC/POS, contenido del ticket, envío por red
y por agente, cajón solo con efectivo, fallas que no pierden la venta."""

import socket
import sys
import threading
from decimal import Decimal as D

import pytest

from agente_impresion.agente import Agente, imprimir_windows
from app.impresion.escpos import CORTE_PARCIAL, INICIALIZAR, PULSO_CAJON, TABLA_PC850, Ticket
from app.models import ModoImpresora
from tests.test_ventas import amoxicilina, caja, r, shampoo, vender  # noqa: F401  (fixtures)


# --- Impresoras falsas ------------------------------------------------------------

class ImpresoraDeRed:
    """Escucha como una impresora Ethernet (puerto raw) y guarda lo recibido."""

    def __init__(self):
        self.servidor = socket.create_server(("127.0.0.1", 0))
        self.direccion = f"127.0.0.1:{self.servidor.getsockname()[1]}"
        self.recibido: list[bytes] = []
        self._hilo = threading.Thread(target=self._atender, daemon=True)
        self._hilo.start()

    def _atender(self):
        while True:
            try:
                conexion, _ = self.servidor.accept()
            except OSError:
                return
            with conexion:
                datos = b""
                while parte := conexion.recv(4096):
                    datos += parte
                self.recibido.append(datos)

    def ultimo(self) -> bytes:
        for _ in range(100):  # el hilo puede tardar un instante en terminar de leer
            if self.recibido:
                return self.recibido[-1]
            threading.Event().wait(0.01)
        raise AssertionError("La impresora no recibió nada")

    def cerrar(self):
        self.servidor.close()


@pytest.fixture
def impresora_red():
    i = ImpresoraDeRed()
    yield i
    i.cerrar()


@pytest.fixture
def agente(tmp_path):
    """El agente real, guardando en un archivo en lugar de imprimir."""
    archivo = tmp_path / "ticket.bin"
    a = Agente(token="secreto", archivo=archivo)
    servidor = a.crear_servidor("127.0.0.1", 0)
    threading.Thread(target=servidor.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield f"http://127.0.0.1:{servidor.server_address[1]}", archivo
    servidor.shutdown()


def configurar(db, caja, modo, direccion, token=None):
    caja.impresora_modo, caja.impresora_direccion, caja.impresora_token = modo, direccion, token
    db.commit()


# --- ESC/POS -----------------------------------------------------------------------

def test_ticket_inicia_con_tabla_de_acentos_y_corta():
    datos = Ticket().linea("Hola").cortar().bytes()
    assert datos.startswith(INICIALIZAR + TABLA_PC850)
    assert datos.endswith(CORTE_PARCIAL)
    assert PULSO_CAJON not in datos


def test_acentos_y_enie_en_pc850():
    datos = Ticket().linea("Ñoño árbol").bytes()
    assert "Ñoño árbol".encode("cp850") in datos


def test_columnas_izquierda_derecha_alineadas():
    t = Ticket(columnas=20).columnas_izq_der("Total", "$10.00")
    assert t.texto() == "Total" + " " * 9 + "$10.00"
    assert len(t.texto()) == 20


def test_texto_largo_se_parte_en_renglones():
    t = Ticket(columnas=10).linea("uno dos tres cuatro")
    assert t.texto().splitlines() == ["uno dos", "tres", "cuatro"]


def test_columnas_largas_conservan_la_sangria():
    t = Ticket(columnas=20).columnas_izq_der("  Paquete con crema", "-$5.00")
    assert t.texto().splitlines() == ["  Paquete con", "  crema       -$5.00"]


# --- Contenido del ticket ------------------------------------------------------------

def test_contenido_del_ticket(como_admin, db, negocio, caja, amoxicilina):
    negocio.nombre = "FARMACIA LA FE"
    negocio.ticket_encabezado = "Calle Falsa 123\nTel. 555-1234"
    negocio.ticket_pie = "¡Gracias por su compra!"
    db.commit()
    v = vender(como_admin, caja, [r(amoxicilina, 3)], efectivo="300").json()  # 2 del lote A + 1 del B
    texto = como_admin.get(f"/ventas/{v['id']}/ticket").text
    for esperado in [
        "FARMACIA LA FE", "Calle Falsa 123", "Tel. 555-1234", f"Folio: {v['folio']}", "Caja: Mostrador 1",
        "AMOXICILINA 500MG", "3 x $85.50", "$256.50", "Lote A  Cad 01/2027  (2)", "Lote B  Cad 06/2027  (1)",
        "Efectivo", "$300.00", "Cambio", "$43.50", "¡Gracias por su compra!",
    ]:
        assert esperado in texto, esperado
    assert "REIMPRESIÓN" not in texto


def test_ticket_con_ieps_e_iva(como_admin, db, caja, shampoo):
    shampoo.ieps_porcentaje = D(8)
    db.commit()
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    texto = como_admin.get(f"/ventas/{v['id']}/ticket").text
    assert "IEPS" in texto and "IVA" in texto


def test_ticket_de_venta_cancelada(como_admin, caja, shampoo):
    v = vender(como_admin, caja, [r(shampoo, 1)], efectivo="116").json()
    como_admin.post(f"/ventas/{v['id']}/cancelar", json={"caja_id": caja.id, "motivo": "error"})
    assert "VENTA CANCELADA" in como_admin.get(f"/ventas/{v['id']}/ticket").text


# --- Envío -------------------------------------------------------------------------

def test_sin_impresora_la_venta_se_guarda_igual(como_mostrador, caja, shampoo):
    res = vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116")
    assert res.status_code == 201
    assert res.json()["impresion"] == {"impreso": False, "error": "La caja 'Mostrador 1' no tiene impresora configurada"}


def test_imprime_por_red_y_abre_cajon_con_efectivo(como_mostrador, db, caja, shampoo, impresora_red):
    configurar(db, caja, ModoImpresora.RED, impresora_red.direccion)
    res = vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="200").json()
    assert res["impresion"] == {"impreso": True, "error": None}
    datos = impresora_red.ultimo()
    assert b"SHAMPOO 400ML" in datos
    assert datos.endswith(PULSO_CAJON)


def test_con_tarjeta_no_abre_cajon(como_mostrador, db, caja, shampoo, impresora_red):
    configurar(db, caja, ModoImpresora.RED, impresora_red.direccion)
    vender(como_mostrador, caja, [r(shampoo, 1)], tarjeta="116")
    assert PULSO_CAJON not in impresora_red.ultimo()


def test_reimpresion_no_abre_cajon(como_mostrador, db, caja, shampoo, impresora_red):
    configurar(db, caja, ModoImpresora.RED, impresora_red.direccion)
    v = vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116").json()
    res = como_mostrador.post(f"/ventas/{v['id']}/imprimir", json={}).json()
    assert res == {"impreso": True, "error": None}
    datos = impresora_red.ultimo()
    assert "REIMPRESIÓN".encode("cp850") in datos
    assert PULSO_CAJON not in datos


def test_impresora_apagada_no_pierde_la_venta(como_mostrador, db, caja, shampoo):
    apagada = socket.create_server(("127.0.0.1", 0))
    direccion = f"127.0.0.1:{apagada.getsockname()[1]}"
    apagada.close()  # nadie escucha en ese puerto
    configurar(db, caja, ModoImpresora.RED, direccion)
    res = vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116")
    assert res.status_code == 201
    assert res.json()["impresion"]["impreso"] is False
    assert "No se pudo conectar con la impresora" in res.json()["impresion"]["error"]
    assert como_mostrador.get(f"/ventas/{res.json()['id']}").status_code == 200


def test_imprime_por_agente_usb(como_mostrador, db, caja, shampoo, agente):
    url, archivo = agente
    configurar(db, caja, ModoImpresora.AGENTE, url, token="secreto")
    res = vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116").json()
    assert res["impresion"] == {"impreso": True, "error": None}
    assert b"SHAMPOO 400ML" in archivo.read_bytes()


def test_agente_rechaza_token_incorrecto(como_mostrador, db, caja, shampoo, agente):
    url, archivo = agente
    configurar(db, caja, ModoImpresora.AGENTE, url, token="otro")
    res = vender(como_mostrador, caja, [r(shampoo, 1)], efectivo="116").json()
    assert res["impresion"]["impreso"] is False
    assert "401" in res["impresion"]["error"]
    assert not archivo.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="solo Windows")
def test_agente_impresora_inexistente_da_error_claro():
    with pytest.raises(OSError, match="No se encontró la impresora"):
        imprimir_windows("IMPRESORA QUE NO EXISTE", b"hola")


# --- Configuración de cajas ---------------------------------------------------------

def test_token_nunca_se_regresa(como_admin, caja):
    res = como_admin.put(f"/cajas/{caja.id}", json={
        "impresora_modo": "agente", "impresora_direccion": "http://192.168.1.21:9110", "impresora_token": "secreto",
    }).json()
    assert "impresora_token" not in res
    assert res["impresora_tiene_token"] is True
    assert "secreto" not in como_admin.get("/cajas").text


def test_prueba_de_impresion(como_admin, como_mostrador, db, caja, impresora_red):
    configurar(db, caja, ModoImpresora.RED, impresora_red.direccion)
    assert como_mostrador.post(f"/cajas/{caja.id}/prueba-impresion", json={}).status_code == 403
    res = como_admin.post(f"/cajas/{caja.id}/prueba-impresion", json={"abrir_cajon": True}).json()
    assert res["impreso"] is True
    assert impresora_red.ultimo().endswith(PULSO_CAJON)
