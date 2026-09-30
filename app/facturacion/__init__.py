"""Facturación CFDI 4.0 a clientes.

El sistema arma los datos de la factura (emisor, receptor, conceptos con sus
impuestos y totales) a partir del ticket, y un PAC la sella y timbra. El PAC
es intercambiable (pac.py): mientras no se elige uno real se usa el
"simulado", que genera facturas marcadas como PRUEBA, sin validez fiscal.
"""
