"""Servidor de demostración para ver las pantallas sin tocar datos reales.

Uso:  python -m app.scripts.servidor_demo
Abre: http://127.0.0.1:8001/login  (admin: demo / demo1234; mostrador: cajero / cajero1234)

Usa la base de pruebas (la de .env con "_test" al final), la BORRA y la llena
con 60 productos tomados de la base real (solo nombres, claves e IVA; se
leen, nunca se modifican) con precios inventados y algunos lotes. Las
pruebas automáticas vuelven a borrar esa base al correr, así que no importa.
"""
import random
import tempfile
from datetime import date
from decimal import Decimal as D
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core import config
from app.core.config import settings

# El demo nunca escribe en el .env real (ej. al guardar la clave de IA).
config.ENV_PATH = Path(tempfile.gettempdir()) / "pos_demo.env"
settings.anthropic_api_key = None

real = make_url(settings.database_url)
prueba = real.set(database=real.database + "_test")
assert prueba.database.endswith("_test"), "el demo solo corre sobre una base *_test"
settings.database_url = prueba.render_as_string(hide_password=False)

import uvicorn  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.seguridad import hashear_password  # noqa: E402
from app.models import Caja, Lote, Negocio, Producto, RolUsuario, Usuario  # noqa: E402

with engine.begin() as c:
    c.execute(text("DROP SCHEMA public CASCADE"))
    c.execute(text("CREATE SCHEMA public"))
RAIZ = Path(__file__).resolve().parents[2]
cfg = Config(str(RAIZ / "alembic.ini"))
cfg.set_main_option("script_location", str(RAIZ / "alembic"))
command.upgrade(cfg, "head")

# Nombres reales de la base de producción (solo lectura), precios inventados.
lectura = create_engine(real)
with lectura.connect() as con:
    nombres = con.execute(text(
        "SELECT clave, nombre, iva_porcentaje FROM productos"
        " WHERE negocio_id = 1 AND clave ~ '^[0-9]{13}$' ORDER BY random() LIMIT 60"
    )).all()
lectura.dispose()

random.seed(1)
with SessionLocal() as db:
    negocio = Negocio(
        nombre="Farmacia La Fe",
        redondeo_precio_venta=D(1),
        ticket_encabezado="Iturbide Norte #2\nMagdalena, Jalisco, México\nTel. 386 744 0175",
        ticket_pie="Gracias por su compra, tenga buen día!",
    )
    db.add(negocio)
    db.flush()
    db.add_all([
        Usuario(negocio_id=negocio.id, nombre_usuario="demo", nombre_completo="Usuario Demo",
                password_hash=hashear_password("demo1234"), rol=RolUsuario.ADMIN),
        Usuario(negocio_id=negocio.id, nombre_usuario="cajero", nombre_completo="Cajero Demo",
                password_hash=hashear_password("cajero1234"), rol=RolUsuario.MOSTRADOR),
        Caja(negocio_id=negocio.id, nombre="Mostrador 1"),
        Caja(negocio_id=negocio.id, nombre="Mostrador 2"),
    ])
    for i, (clave, nombre, iva) in enumerate(nombres):
        producto = Producto(
            negocio_id=negocio.id, clave=clave, nombre=nombre, iva_porcentaje=iva,
            precio_venta=D(random.randint(25, 450)), requiere_receta=(i % 7 == 0),
        )
        db.add(producto)
        db.flush()
        if i % 3 == 0:  # algunos con lotes y caducidades, para ver FEFO
            for letra, anio, piezas in (("A", 2027, 3), ("B", 2028, 5)):
                db.add(Lote(negocio_id=negocio.id, producto_id=producto.id, numero_lote=f"{letra}{i}",
                            caducidad=date(anio, 1 + i % 12, 28), cantidad=D(piezas)))
        db.add(Lote(negocio_id=negocio.id, producto_id=producto.id, cantidad=D(random.randint(2, 15))))
    db.commit()
    settings.negocio_predeterminado = negocio.id
    print(f"Demo lista: {len(nombres)} productos. Abre http://127.0.0.1:8001/login (demo / demo1234, cajero / cajero1234)")

uvicorn.run("app.main:app", host="127.0.0.1", port=8001)
