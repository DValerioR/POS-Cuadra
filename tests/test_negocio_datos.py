"""Datos del negocio: fiscales, ticket y redondeo."""


def test_guardar_datos_fiscales(como_admin):
    r = como_admin.put("/negocio", json={"razon_social": "  Zaida   Valerio Barrantes ", "rfc": "vabz611024rw3",
                                         "regimen_fiscal": "612", "codigo_postal": "46470"})
    assert r.status_code == 200, r.text
    n = como_admin.get("/negocio").json()
    assert (n["razon_social"], n["rfc"], n["regimen_fiscal"], n["codigo_postal"]) == \
        ("Zaida Valerio Barrantes", "VABZ611024RW3", "612", "46470")
    # Vaciar un dato
    assert como_admin.put("/negocio", json={"rfc": None}).json()["rfc"] is None


def test_validaciones(como_admin):
    for datos in ({"rfc": "ABC"}, {"regimen_fiscal": "999"}, {"codigo_postal": "4647"}, {"nombre": ""}):
        assert como_admin.put("/negocio", json=datos).status_code == 422, datos


def test_solo_admin(como_mostrador):
    assert como_mostrador.put("/negocio", json={"rfc": "VABZ611024RW3"}).status_code == 403
