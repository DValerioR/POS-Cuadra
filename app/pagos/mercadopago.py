"""Cobro con tarjeta en una terminal Mercado Pago Point (API de órdenes).

El POS crea una "orden" con el monto y la terminal de la caja; la terminal
la muestra, el cliente pasa la tarjeta y la orden queda `processed` (o se
cancela, falla o expira). El POS consulta la orden hasta saber cómo terminó:
en la farmacia el servidor no es público, así que no hay webhooks.

Documentación: https://www.mercadopago.com.mx/developers/es/docs/mp-point
- POST /v1/orders                 crear la orden (type "point")
- GET  /v1/orders/{id}            consultar
- POST /v1/orders/{id}/cancel     cancelar (solo si aún no llega a la terminal)
- POST /v1/orders/{id}/refund     reembolsar (total o parcial, hasta 90 días)
- GET  /terminals/v1/list         terminales de la cuenta
- PATCH /terminals/v1/setup       poner una terminal en modo PDV (integrada)

Hay dos clientes con los mismos métodos: `ClienteReal` (httpx) y
`ClienteSimulado` (en memoria, para el demo y las pruebas; no cobra nada).
"""

import itertools
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

import httpx

URL = "https://api.mercadopago.com"

# Estados de la orden en Mercado Pago.
CREADA = "created"
EN_TERMINAL = "at_terminal"
PAGADA = "processed"
CANCELADA = "canceled"
EXPIRADA = "expired"
FALLIDA = "failed"
REEMBOLSADA = "refunded"
FINALES = {PAGADA, CANCELADA, EXPIRADA, FALLIDA, REEMBOLSADA}


class ErrorMercadoPago(Exception):
    """Mercado Pago rechazó la operación o no respondió. `mensaje` es para el usuario."""

    def __init__(self, mensaje: str):
        super().__init__(mensaje)
        self.mensaje = mensaje


@dataclass
class Terminal:
    id: str
    modo: str  # PDV, STANDALONE o UNDEFINED
    tienda_id: str | None = None
    caja_id: str | None = None


@dataclass
class Orden:
    id: str
    estado: str
    detalle: str | None = None
    monto: Decimal = Decimal(0)
    pago_id: str | None = None
    tarjeta: str | None = None  # p. ej. "visa ****1234", si Mercado Pago lo da


def _orden(datos: dict) -> Orden:
    pagos = (datos.get("transactions") or {}).get("payments") or [{}]
    pago = pagos[0]
    metodo = pago.get("payment_method") or {}
    tarjeta = " ".join(x for x in (
        metodo.get("id"), f"****{metodo['last_four_digits']}" if metodo.get("last_four_digits") else None,
    ) if x) or None
    return Orden(
        id=datos["id"], estado=datos.get("status", ""), detalle=datos.get("status_detail"),
        monto=Decimal(str(pago.get("amount") or 0)), pago_id=pago.get("id"), tarjeta=tarjeta,
    )


class ClienteReal:
    def __init__(self, token: str, timeout: float = 15.0):
        self._http = httpx.Client(base_url=URL, timeout=timeout, headers={"Authorization": f"Bearer {token}"})

    def _pedir(self, metodo: str, ruta: str, idempotencia: str | None = None, **kwargs) -> dict:
        headers = {"X-Idempotency-Key": idempotencia} if idempotencia else {}
        try:
            r = self._http.request(metodo, ruta, headers=headers, **kwargs)
        except httpx.HTTPError:
            raise ErrorMercadoPago("No hay conexión con Mercado Pago. ¿Hay internet?")
        if r.status_code in (401, 403):
            raise ErrorMercadoPago("Mercado Pago no aceptó el token (Configuración → Terminal Mercado Pago).")
        if r.status_code >= 400:
            try:
                datos = r.json()
                detalle = datos.get("message") or (datos.get("errors") or [{}])[0].get("message")
            except ValueError:
                detalle = None
            raise ErrorMercadoPago(f"Mercado Pago respondió con un error ({r.status_code})" + (f": {detalle}" if detalle else ""))
        return r.json() if r.content else {}

    def terminales(self) -> list[Terminal]:
        datos = self._pedir("GET", "/terminals/v1/list", params={"limit": 50, "offset": 0})
        lista = (datos.get("data") or {}).get("terminals") or datos.get("terminals") or []
        return [Terminal(t["id"], t.get("operating_mode", "UNDEFINED"), t.get("store_id"), t.get("pos_id")) for t in lista]

    def modo_pdv(self, terminal_id: str) -> None:
        self._pedir("PATCH", "/terminals/v1/setup", json={"terminals": [{"id": terminal_id, "operating_mode": "PDV"}]})

    def crear_orden(self, terminal_id: str, monto: Decimal, referencia: str, idempotencia: str) -> Orden:
        return _orden(self._pedir("POST", "/v1/orders", idempotencia, json={
            "type": "point",
            "external_reference": referencia,
            "expiration_time": "PT5M",
            "transactions": {"payments": [{"amount": f"{monto:.2f}"}]},
            "config": {"point": {"terminal_id": terminal_id, "print_on_terminal": "no_ticket"}},
            "description": "Venta en mostrador",
        }))

    def consultar(self, orden_id: str) -> Orden:
        return _orden(self._pedir("GET", f"/v1/orders/{orden_id}"))

    def cancelar(self, orden_id: str, idempotencia: str) -> Orden:
        return _orden(self._pedir("POST", f"/v1/orders/{orden_id}/cancel", idempotencia))

    def reembolsar(self, orden_id: str, pago_id: str, monto: Decimal, idempotencia: str) -> None:
        self._pedir("POST", f"/v1/orders/{orden_id}/refund", idempotencia,
                    json={"amount": f"{monto:.2f}", "transaction_id": pago_id})


@dataclass
class _OrdenSimulada:
    orden: Orden
    final: str  # cómo terminará
    consultas: int = 0


@dataclass
class ClienteSimulado:
    """Terminal de mentira: la orden llega a la terminal en la primera
    consulta y se paga en la segunda (unos segundos en pantalla). Las pruebas
    pueden decidir cómo termina con `siguiente`."""

    terminales_simuladas: list[Terminal] = field(default_factory=lambda: [
        Terminal("SIMULADA__TERMINAL1", "PDV"), Terminal("SIMULADA__TERMINAL2", "STANDALONE"),
    ])
    # Cómo terminará la próxima orden: PAGADA, FALLIDA, EXPIRADA o CANCELADA (en la terminal).
    siguiente: str = PAGADA
    ordenes: dict[str, _OrdenSimulada] = field(default_factory=dict)
    reembolsos: list[tuple[str, Decimal]] = field(default_factory=list)
    _contador: itertools.count = field(default_factory=lambda: itertools.count(1))

    def terminales(self) -> list[Terminal]:
        return self.terminales_simuladas

    def modo_pdv(self, terminal_id: str) -> None:
        for t in self.terminales_simuladas:
            if t.id == terminal_id:
                t.modo = "PDV"

    def crear_orden(self, terminal_id: str, monto: Decimal, referencia: str, idempotencia: str) -> Orden:
        orden = Orden(f"ORDSIM{next(self._contador):06d}", CREADA, CREADA, monto, f"PAYSIM{uuid.uuid4().hex[:8]}")
        self.ordenes[orden.id] = _OrdenSimulada(orden, self.siguiente)
        return Orden(orden.id, CREADA, CREADA, monto, orden.pago_id)

    def consultar(self, orden_id: str) -> Orden:
        s = self.ordenes[orden_id]
        o = s.orden
        if o.estado not in FINALES:
            s.consultas += 1
            if s.consultas == 1:
                o.estado = EN_TERMINAL
            else:
                o.estado = s.final
                if o.estado == PAGADA:
                    o.tarjeta = "visa ****4242"
        return Orden(o.id, o.estado, o.estado, o.monto, o.pago_id, o.tarjeta)

    def cancelar(self, orden_id: str, idempotencia: str) -> Orden:
        o = self.ordenes[orden_id].orden
        if o.estado != CREADA:
            raise ErrorMercadoPago("El cobro ya está en la terminal: cancélalo en la terminal.")
        o.estado = CANCELADA
        return Orden(o.id, o.estado, o.estado, o.monto, o.pago_id)

    def reembolsar(self, orden_id: str, pago_id: str, monto: Decimal, idempotencia: str) -> None:
        self.reembolsos.append((orden_id, monto))


# El cliente simulado se activa en el demo y en las pruebas (ver `activar_simulado`).
_simulado: ClienteSimulado | None = None


def activar_simulado() -> ClienteSimulado:
    global _simulado
    _simulado = ClienteSimulado()
    return _simulado


def desactivar_simulado() -> None:
    global _simulado
    _simulado = None


def cliente(token: str | None) -> "ClienteReal | ClienteSimulado":
    if _simulado is not None:
        return _simulado
    if not token:
        raise ErrorMercadoPago("Falta el token de Mercado Pago (Configuración → Terminal Mercado Pago).")
    return ClienteReal(token)


def nueva_idempotencia() -> str:
    return str(uuid.uuid4())
