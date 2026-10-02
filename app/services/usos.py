"""Usos de los servicios que se pagan por consumo (la API de Claude y las
facturas reales) y los topes mensuales del plan de Cuadra.

Cada acción con IA cuenta como un uso aunque por dentro haga varias llamadas
(una pregunta al asistente, una factura de proveedor leída, una foto, una
respuesta del bot...). Las facturas cuentan solo si son reales: las de prueba
no cuestan. El mes es el del calendario en la zona horaria del negocio.

Quien llama hace `revisar` antes de usar el servicio y `registrar` solo si
salió bien; el registro se guarda con el commit de la misma operación, así
que lo que falla no se cobra. Dos usos al mismo tiempo pueden pasarse del
tope por uno: no importa, el tope es para que no se dispare el gasto.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import TipoUso, UsoServicio
from app.services.errores import OperacionInvalida

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")
# Desde qué porcentaje del tope se avisa que se está acabando.
AVISO_DESDE = 80


def tope(tipo: TipoUso) -> int | None:
    return settings.tope_ia_mes if tipo == TipoUso.IA else settings.tope_facturas_mes


def _ahora() -> datetime:
    return datetime.now(ZoneInfo(settings.zona_horaria))


def inicio_del_mes(ahora: datetime | None = None) -> datetime:
    ahora = ahora or _ahora()
    return ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def siguiente_mes(ahora: datetime | None = None) -> date:
    hoy = (ahora or _ahora()).date()
    return date(hoy.year + 1, 1, 1) if hoy.month == 12 else date(hoy.year, hoy.month + 1, 1)


def usados(db: Session, negocio_id: int, tipo: TipoUso) -> int:
    return db.scalar(select(func.count()).select_from(UsoServicio).where(
        UsoServicio.negocio_id == negocio_id, UsoServicio.tipo == tipo,
        UsoServicio.created_at >= inicio_del_mes())) or 0


def agotado(db: Session, negocio_id: int, tipo: TipoUso) -> bool:
    limite = tope(tipo)
    return limite is not None and usados(db, negocio_id, tipo) >= limite


def revisar(db: Session, negocio_id: int, tipo: TipoUso) -> None:
    """Lanza OperacionInvalida si ya se llegó al tope del mes."""
    if not agotado(db, negocio_id, tipo):
        return
    limite = tope(tipo)
    renueva = siguiente_mes()
    que = f"los {limite} usos de IA" if tipo == TipoUso.IA else f"las {limite} facturas"
    raise OperacionInvalida(
        f"Ya se usaron {que} que incluye tu plan este mes. Se renuevan el 1 de {MESES[renueva.month - 1]}. "
        "Si necesitas más, pide a tu proveedor de Cuadra que amplíe tu plan."
    )


def registrar(db: Session, negocio_id: int, tipo: TipoUso, origen: str) -> None:
    db.add(UsoServicio(negocio_id=negocio_id, tipo=tipo, origen=origen))
    db.flush()


def resumen(db: Session, negocio_id: int) -> dict:
    """Lo usado este mes de cada servicio contra su tope, para mostrarlo."""
    renueva = siguiente_mes()
    datos = {"renueva": renueva, "renueva_texto": f"1 de {MESES[renueva.month - 1]}"}
    for tipo in TipoUso:
        n, limite = usados(db, negocio_id, tipo), tope(tipo)
        datos[tipo.value] = {
            "usados": n,
            "tope": limite,
            "restantes": None if limite is None else max(limite - n, 0),
            "porcentaje": None if not limite else min(round(n * 100 / limite), 100),
            "estado": "sin_tope" if limite is None else
                      "agotado" if n >= limite else
                      "por_acabarse" if n * 100 >= limite * AVISO_DESDE else "bien",
        }
    return datos
