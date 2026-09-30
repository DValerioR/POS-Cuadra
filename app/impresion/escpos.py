"""Generador mínimo de comandos ESC/POS para impresoras térmicas de tickets.

Las dos impresoras de la farmacia (Bixolon SRP-330II y Epson TM-T20II)
hablan ESC/POS; solo se usa lo que ambas entienden igual. No se usa la
librería python-escpos para no cargar dependencias (pyusb...) que no hacen
falta; el logo se convierte a puntos en impresion/logo.py.

Además de los bytes, se arma una versión en texto plano del mismo ticket,
para verlo en pantalla o en pruebas sin impresora.
"""

import textwrap

ESC, GS = b"\x1b", b"\x1d"

INICIALIZAR = ESC + b"@"
# Tabla de caracteres PC850 (acentos y Ñ); en ambas impresoras es la 2.
TABLA_PC850 = ESC + b"t\x02"
CORTE_PARCIAL = GS + b"V\x42\x00"  # avanza el papel y corta
# Pulso al conector del cajón (pin 2): 25×2 ms encendido, 250×2 ms apagado.
PULSO_CAJON = ESC + b"p\x00\x19\xfa"

_ALINEACION = {"izquierda": 0, "centro": 1, "derecha": 2}


class Ticket:
    def __init__(self, columnas: int = 48):
        # 48 columnas = papel de 80 mm con la fuente normal.
        self.columnas = columnas
        self._bytes = bytearray(INICIALIZAR + TABLA_PC850)
        self._texto: list[str] = []

    # --- Texto ------------------------------------------------------------

    def _escribir(self, linea: str, alineacion: str = "izquierda", negrita: bool = False, doble: bool = False) -> None:
        self._bytes += ESC + b"a" + bytes([_ALINEACION[alineacion]])
        if negrita:
            self._bytes += ESC + b"E\x01"
        if doble:
            self._bytes += GS + b"!\x11"  # doble alto y ancho
        self._bytes += linea.encode("cp850", errors="replace") + b"\n"
        if doble:
            self._bytes += GS + b"!\x00"
        if negrita:
            self._bytes += ESC + b"E\x00"

        # En el texto plano el tamaño doble se ve normal; se alinea al ancho completo.
        visible = {"centro": linea.center(self.columnas), "derecha": linea.rjust(self.columnas)}.get(alineacion, linea)
        self._texto.append(visible.rstrip())

    def linea(self, texto: str = "", alineacion: str = "izquierda", negrita: bool = False, doble: bool = False) -> "Ticket":
        """Escribe texto; si no cabe, lo parte en varios renglones."""
        ancho = self.columnas // 2 if doble else self.columnas
        for parte in textwrap.wrap(texto, ancho) or [""]:
            self._escribir(parte, alineacion, negrita, doble)
        return self

    def columnas_izq_der(self, izquierda: str, derecha: str, negrita: bool = False) -> "Ticket":
        """Texto a la izquierda e importe pegado a la derecha en el mismo renglón."""
        espacio = self.columnas - len(derecha) - 1
        partes = textwrap.wrap(izquierda, espacio) or [""]
        for parte in partes[:-1]:
            self._escribir(parte, negrita=negrita)
        self._escribir(partes[-1].ljust(espacio) + " " + derecha, negrita=negrita)
        return self

    def imagen(self, bytes_renglon: int, alto: int, bits: bytes) -> "Ticket":
        """Imagen en puntos (GS v 0), por ejemplo el logo. `bits`: un bit por
        punto, 1 = negro, `bytes_renglon` bytes por renglón."""
        self._bytes += ESC + b"a\x00" + GS + b"v0\x00" + bytes([
            bytes_renglon % 256, bytes_renglon // 256, alto % 256, alto // 256,
        ]) + bits + b"\n"
        self._texto.append("[logo]".center(self.columnas).rstrip())
        return self

    def separador(self, caracter: str = "-") -> "Ticket":
        self._escribir(caracter * self.columnas)
        return self

    # --- Control ----------------------------------------------------------

    def cortar(self) -> "Ticket":
        self._bytes += b"\n" * 4 + CORTE_PARCIAL
        return self

    def abrir_cajon(self) -> "Ticket":
        self._bytes += PULSO_CAJON
        return self

    # --- Resultado --------------------------------------------------------

    def bytes(self) -> bytes:
        return bytes(self._bytes)

    def texto(self) -> str:
        return "\n".join(self._texto)
