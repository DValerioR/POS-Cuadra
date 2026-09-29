"""Agente de impresión para las computadoras de mostrador.

Recibe tickets del servidor del POS por la red y los manda a la impresora
USB de esta computadora a través de Windows, en modo RAW (los comandos
ESC/POS llegan tal cual a la impresora: texto, corte y apertura del cajón).

No necesita instalar nada: solo Python (biblioteca estándar).

Uso:
    python agente.py --impresora "EPSON TM-T20II Receipt" --token SECRETO
    python agente.py --archivo prueba.bin --token SECRETO     (sin impresora: guarda los bytes)

El nombre de la impresora es el que aparece en Windows (en PowerShell:
Get-Printer). En la caja del POS se configura:
    impresora_modo = "agente"
    impresora_direccion = "http://IP-DE-ESTA-PC:9110"
    impresora_token = el mismo SECRETO

Endpoints:
    POST /imprimir   cuerpo = bytes ESC/POS, encabezado X-Token
    GET  /estado     para verificar que el agente está vivo
"""

import argparse
import ctypes
import hmac
import json
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

MAX_BYTES = 1_000_000  # un ticket pesa unos pocos KB


# --- Impresión RAW en Windows (winspool) -----------------------------------

def imprimir_windows(nombre_impresora: str, datos: bytes) -> None:
    from ctypes import wintypes

    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)

    class DOC_INFO_1(ctypes.Structure):
        _fields_ = [("pDocName", wintypes.LPWSTR), ("pOutputFile", wintypes.LPWSTR), ("pDatatype", wintypes.LPWSTR)]

    winspool.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), wintypes.LPVOID]
    winspool.OpenPrinterW.restype = wintypes.BOOL
    winspool.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(DOC_INFO_1)]
    winspool.StartDocPrinterW.restype = wintypes.DWORD
    winspool.WritePrinter.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    winspool.WritePrinter.restype = wintypes.BOOL
    for nombre in ("StartPagePrinter", "EndPagePrinter", "EndDocPrinter", "ClosePrinter"):
        getattr(winspool, nombre).argtypes = [wintypes.HANDLE]
        getattr(winspool, nombre).restype = wintypes.BOOL

    def fallo(paso: str) -> OSError:
        return OSError(f"{paso}: {ctypes.FormatError(ctypes.get_last_error())}")

    handle = wintypes.HANDLE()
    if not winspool.OpenPrinterW(nombre_impresora, ctypes.byref(handle), None):
        raise fallo(f"No se encontró la impresora '{nombre_impresora}'")
    try:
        doc = DOC_INFO_1("Ticket POS", None, "RAW")
        if not winspool.StartDocPrinterW(handle, 1, ctypes.byref(doc)):
            raise fallo("No se pudo iniciar el trabajo de impresión")
        try:
            winspool.StartPagePrinter(handle)
            escritos = wintypes.DWORD()
            buffer = ctypes.create_string_buffer(datos, len(datos))
            if not winspool.WritePrinter(handle, buffer, len(datos), ctypes.byref(escritos)):
                raise fallo("No se pudo enviar el ticket a la impresora")
            winspool.EndPagePrinter(handle)
        finally:
            winspool.EndDocPrinter(handle)
    finally:
        winspool.ClosePrinter(handle)


# --- Servidor HTTP -----------------------------------------------------------

class Agente:
    def __init__(self, token: str, impresora: str | None = None, archivo: Path | None = None):
        if not token:
            raise ValueError("El token es obligatorio")
        if bool(impresora) == bool(archivo):
            raise ValueError("Indica --impresora o --archivo (uno de los dos)")
        self.token = token
        self.impresora = impresora
        self.archivo = archivo
        self._candado = Lock()  # un ticket a la vez

    def imprimir(self, datos: bytes) -> None:
        with self._candado:
            if self.archivo:
                with open(self.archivo, "ab") as f:
                    f.write(datos)
            else:
                imprimir_windows(self.impresora, datos)

    def token_valido(self, recibido: str | None) -> bool:
        return hmac.compare_digest((recibido or "").encode(), self.token.encode())

    def crear_servidor(self, host: str, puerto: int) -> ThreadingHTTPServer:
        agente = self

        class Manejador(BaseHTTPRequestHandler):
            def _responder(self, codigo: int, cuerpo: dict) -> None:
                datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(datos)))
                self.end_headers()
                self.wfile.write(datos)

            def do_GET(self):
                if self.path == "/estado":
                    self._responder(200, {"ok": True, "impresora": agente.impresora or f"archivo {agente.archivo}"})
                else:
                    self._responder(404, {"error": "no existe"})

            def do_POST(self):
                if self.path != "/imprimir":
                    return self._responder(404, {"error": "no existe"})
                if not agente.token_valido(self.headers.get("X-Token")):
                    return self._responder(401, {"error": "token inválido"})
                largo = int(self.headers.get("Content-Length") or 0)
                if not 0 < largo <= MAX_BYTES:
                    return self._responder(400, {"error": "ticket vacío o demasiado grande"})
                try:
                    agente.imprimir(self.rfile.read(largo))
                except OSError as e:
                    return self._responder(500, {"error": str(e)})
                self._responder(200, {"ok": True})

            def log_message(self, formato, *args):
                print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {self.client_address[0]} {formato % args}")

        return ThreadingHTTPServer((host, puerto), Manejador)


def main() -> None:
    parser = argparse.ArgumentParser(description="Agente de impresión del POS")
    parser.add_argument("--impresora", help="nombre de la impresora en Windows (Get-Printer)")
    parser.add_argument("--archivo", type=Path, help="en lugar de imprimir, guardar los bytes aquí (pruebas)")
    parser.add_argument("--token", required=True, help="secreto compartido con el servidor")
    parser.add_argument("--puerto", type=int, default=9110)
    parser.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = aceptar conexiones de la red")
    args = parser.parse_args()

    try:
        agente = Agente(args.token, args.impresora, args.archivo)
    except ValueError as e:
        sys.exit(str(e))
    servidor = agente.crear_servidor(args.host, args.puerto)
    print(f"Agente de impresión escuchando en el puerto {args.puerto} -> {args.impresora or args.archivo}")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
