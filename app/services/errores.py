"""Errores de reglas de negocio, compartidos por todos los servicios. Los
endpoints los traducen a HTTP con `a_http`."""

from fastapi import HTTPException


class NoEncontrado(Exception):
    pass


class OperacionInvalida(Exception):
    pass


class SinPermiso(Exception):
    pass


ERRORES_NEGOCIO = (NoEncontrado, SinPermiso, OperacionInvalida)


def a_http(error: Exception) -> HTTPException:
    codigo = {NoEncontrado: 404, SinPermiso: 403, OperacionInvalida: 409}[type(error)]
    return HTTPException(status_code=codigo, detail=str(error))
