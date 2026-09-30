"""Las partes de los catálogos del SAT que usa una farmacia."""

# Régimen fiscal del receptor: (descripción, aplica a persona física, aplica a moral).
REGIMENES = {
    "601": ("General de Ley Personas Morales", False, True),
    "603": ("Personas Morales con Fines no Lucrativos", False, True),
    "605": ("Sueldos y Salarios e Ingresos Asimilados a Salarios", True, False),
    "606": ("Arrendamiento", True, False),
    "608": ("Demás ingresos", True, False),
    "612": ("Personas Físicas con Actividades Empresariales y Profesionales", True, False),
    "616": ("Sin obligaciones fiscales", True, False),
    "621": ("Incorporación Fiscal", True, False),
    "625": ("Actividades Empresariales con ingresos a través de Plataformas Tecnológicas", True, False),
    "626": ("Régimen Simplificado de Confianza", True, True),
}

# Uso del CFDI: (descripción, regímenes que lo pueden usar; None = todos menos 616).
USOS_CFDI = {
    "G01": ("Adquisición de mercancías", {"601", "603", "606", "612", "621", "625", "626"}),
    "G03": ("Gastos en general", {"601", "603", "606", "612", "621", "625", "626"}),
    "D01": ("Honorarios médicos, dentales y gastos hospitalarios", {"605", "606", "608", "612", "621", "625", "626"}),
    "S01": ("Sin efectos fiscales", None),
}

FORMAS_PAGO = {
    "01": "Efectivo",
    "04": "Tarjeta de crédito",
    "28": "Tarjeta de débito",
    "03": "Transferencia electrónica",
}

CLAVE_GENERICA = "01010101"  # "No existe en el catálogo": se usa si el producto no tiene clave SAT
CLAVE_UNIDAD = "H87"  # pieza
RFC_GENERICO = "XAXX010101000"  # público en general (no se usa en facturas a un cliente)


def es_persona_moral(rfc: str) -> bool:
    return len(rfc) == 12


def validar_receptor(rfc: str, regimen: str, uso: str) -> str | None:
    """Mensaje de error si la combinación no la acepta el SAT; None si está bien."""
    if regimen not in REGIMENES:
        return "Régimen fiscal no reconocido"
    if uso not in USOS_CFDI:
        return "Uso del CFDI no reconocido"
    if rfc == RFC_GENERICO:
        return "Para facturar a un cliente se necesita su RFC (el genérico es para la factura global)"
    _, fisica, moral = REGIMENES[regimen]
    if es_persona_moral(rfc) and not moral:
        return f"El régimen {regimen} es de personas físicas y el RFC es de una persona moral"
    if not es_persona_moral(rfc) and not fisica:
        return f"El régimen {regimen} es de personas morales y el RFC es de una persona física"
    permitidos = USOS_CFDI[uso][1]
    if regimen == "616" and uso != "S01":
        return "Con régimen 616 (sin obligaciones fiscales) el uso del CFDI debe ser S01"
    if permitidos is not None and regimen not in permitidos:
        return f"El uso {uso} no se puede usar con el régimen {regimen}"
    return None
