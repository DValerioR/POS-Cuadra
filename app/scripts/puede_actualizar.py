"""¿Se puede instalar una actualización ahora? Lo pregunta instalador\\actualizar.ps1
(la tarea "Cuadra - actualizar") antes de reiniciar el servidor.

Sale con 0 si la farmacia está cerrada ahora y seguirá cerrada al menos 30
minutos (horario de Datos del negocio); sin horario capturado, solo de 1 a 5
de la mañana. Sale con 1 si no.
"""

import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import Negocio
from app.services import horario

MARGEN = timedelta(minutes=30)


def puede(horarios: list[dict | None], ahora: datetime) -> bool:
    if not any(horarios):
        return 1 <= ahora.hour < 5
    for h in horarios:
        if h and (horario.esta_abierto(h, ahora) or horario.esta_abierto(h, ahora + MARGEN)):
            return False
    return True


def main() -> None:
    with SessionLocal() as db:
        horarios = list(db.scalars(select(Negocio.horario)))
    ahora = datetime.now(ZoneInfo(settings.zona_horaria))
    si = puede(horarios, ahora)
    print("si" if si else "no")
    sys.exit(0 if si else 1)


if __name__ == "__main__":
    main()
