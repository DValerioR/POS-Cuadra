"""Usuarios del negocio (solo administradores): alta, cambios de nombre y
rol, activar/desactivar y restablecer contraseña. Además, cualquier usuario
puede cambiar su propia contraseña.

Reglas:
- El nombre de usuario no se repite en el negocio (sin distinguir mayúsculas).
- Siempre queda al menos un administrador activo.
- Nadie se desactiva ni se quita el rol de administrador a sí mismo.
- Desactivar a alguien o cambiarle la contraseña cierra sus sesiones abiertas,
  para que deje de entrar de inmediato.
- Los usuarios no se borran (sus ventas y turnos los siguen nombrando).
"""

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.seguridad import MAX_BYTES_PASSWORD, hashear_password, verificar_password
from app.models import RolUsuario, Sesion, Usuario
from app.services.errores import NoEncontrado, OperacionInvalida

MIN_PASSWORD = 6


def _validar_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise OperacionInvalida(f"La contraseña debe tener al menos {MIN_PASSWORD} caracteres")
    if len(password.encode("utf-8")) > MAX_BYTES_PASSWORD:
        raise OperacionInvalida("La contraseña es demasiado larga")


def _nombre_usuario(texto: str) -> str:
    nombre = (texto or "").strip()
    if not nombre:
        raise OperacionInvalida("Falta el nombre de usuario")
    if len(nombre) > 40 or any(c.isspace() for c in nombre):
        raise OperacionInvalida("El nombre de usuario va sin espacios y con máximo 40 caracteres")
    return nombre


def _nombre_completo(texto: str) -> str:
    nombre = " ".join((texto or "").split())
    if not nombre:
        raise OperacionInvalida("Falta el nombre completo")
    return nombre[:80]


def _cerrar_sesiones(db: Session, usuario_id: int) -> None:
    db.execute(update(Sesion).where(Sesion.usuario_id == usuario_id, Sesion.cerrada.is_(None))
               .values(cerrada=datetime.now(timezone.utc)))


def obtener(db: Session, admin: Usuario, usuario_id: int) -> Usuario:
    u = db.get(Usuario, usuario_id)
    if u is None or u.negocio_id != admin.negocio_id:
        raise NoEncontrado("Usuario no encontrado")
    return u


def listar(db: Session, admin: Usuario) -> list[dict]:
    ultimo = (select(Sesion.usuario_id, func.max(Sesion.created_at).label("ultimo"))
              .group_by(Sesion.usuario_id).subquery())
    filas = db.execute(
        select(Usuario, ultimo.c.ultimo).outerjoin(ultimo, ultimo.c.usuario_id == Usuario.id)
        .where(Usuario.negocio_id == admin.negocio_id)
        .order_by(Usuario.activo.desc(), Usuario.nombre_completo)
    ).all()
    return [{"id": u.id, "nombre_usuario": u.nombre_usuario, "nombre_completo": u.nombre_completo,
             "rol": u.rol.value, "activo": u.activo, "ultimo_acceso": ultimo_acceso, "created_at": u.created_at,
             "soy_yo": u.id == admin.id}
            for u, ultimo_acceso in filas]


def crear(db: Session, admin: Usuario, nombre_usuario: str, nombre_completo: str, rol: str, password: str) -> Usuario:
    nombre = _nombre_usuario(nombre_usuario)
    if db.scalar(select(Usuario.id).where(Usuario.negocio_id == admin.negocio_id,
                                          func.lower(Usuario.nombre_usuario) == nombre.lower())):
        raise OperacionInvalida(f"Ya existe el usuario «{nombre}»")
    _validar_password(password)
    u = Usuario(negocio_id=admin.negocio_id, nombre_usuario=nombre, nombre_completo=_nombre_completo(nombre_completo),
                rol=_rol(rol), password_hash=hashear_password(password))
    db.add(u)
    db.flush()
    return u


def _rol(texto: str) -> RolUsuario:
    try:
        return RolUsuario(texto)
    except ValueError:
        raise OperacionInvalida("Rol inválido")


def _admins_activos(db: Session, negocio_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Usuario).where(
        Usuario.negocio_id == negocio_id, Usuario.rol == RolUsuario.ADMIN, Usuario.activo.is_(True)))


def actualizar(db: Session, admin: Usuario, usuario_id: int, nombre_completo: str | None = None,
               rol: str | None = None, activo: bool | None = None) -> Usuario:
    u = obtener(db, admin, usuario_id)
    if nombre_completo is not None:
        u.nombre_completo = _nombre_completo(nombre_completo)
    quita_admin = u.rol == RolUsuario.ADMIN and u.activo and (
        (rol is not None and _rol(rol) != RolUsuario.ADMIN) or activo is False)
    if u.id == admin.id and quita_admin:
        raise OperacionInvalida("No puedes quitarte el rol de administrador ni desactivarte a ti mismo")
    if quita_admin and _admins_activos(db, admin.negocio_id) <= 1:
        raise OperacionInvalida("Debe quedar al menos un administrador activo")
    if rol is not None:
        u.rol = _rol(rol)
    if activo is not None and activo != u.activo:
        u.activo = activo
        if not activo:
            _cerrar_sesiones(db, u.id)
    return u


def restablecer_password(db: Session, admin: Usuario, usuario_id: int, password: str) -> Usuario:
    """El administrador le pone una contraseña nueva (por ejemplo, si la olvidó)."""
    u = obtener(db, admin, usuario_id)
    _validar_password(password)
    u.password_hash = hashear_password(password)
    if u.id != admin.id:
        _cerrar_sesiones(db, u.id)
    return u


def cambiar_mi_password(db: Session, usuario: Usuario, actual: str, nueva: str) -> None:
    if not verificar_password(actual or "", usuario.password_hash):
        raise OperacionInvalida("La contraseña actual no es correcta")
    _validar_password(nueva)
    if actual == nueva:
        raise OperacionInvalida("La contraseña nueva debe ser distinta de la actual")
    usuario.password_hash = hashear_password(nueva)
