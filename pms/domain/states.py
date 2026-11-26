"""Patrón de Comportamiento GoF: State para la Máquina de Estados de `UnidadHospedaje`.

Modela el ciclo de vida operativo de una Cabaña o Habitación en Turismo TUCHILE:
    DISPONIBLE -> OCUPADA (al hacer Check-in)
    OCUPADA    -> SUCIO (automáticamente al hacer Check-out)
    SUCIO      -> EN_LIMPIEZA (cuando Personal de Aseo inicia limpieza) o MANTENIMIENTO (si hay falla técnica)
    EN_LIMPIEZA -> DISPONIBLE (cuando Personal de Aseo finaliza y libera la unidad) o MANTENIMIENTO
    MANTENIMIENTO -> EN_LIMPIEZA / DISPONIBLE

Garantiza que no se pueda hacer Check-in sobre una unidad en estado SUCIO, EN_LIMPIEZA o MANTENIMIENTO.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from pms.models import UnidadHospedaje


class TransicionEstadoInvalidaError(ValueError):
    """Excepción de dominio lanzada cuando se intenta una transición de estado no permitida."""


class EstadoUnidadState(ABC):
    """Estado Abstracto (State GoF) para una unidad de hospedaje."""

    @property
    @abstractmethod
    def codigo_estado(self) -> str:
        """Código persistido en base de datos."""

    @abstractmethod
    def puede_recibir_checkin(self) -> bool:
        """Indica si la unidad está apta para entregar llaves a un huésped."""

    def ocupar_por_checkin(self, unidad: UnidadHospedaje) -> str:
        raise TransicionEstadoInvalidaError(
            f"No se puede realizar Check-in: la unidad {unidad.codigo_numero} está en estado {self.codigo_estado}."
        )

    def marcar_sucia_por_checkout(self, unidad: UnidadHospedaje) -> str:
        raise TransicionEstadoInvalidaError(
            f"No se puede hacer Check-out sobre una unidad en estado {self.codigo_estado}."
        )

    def iniciar_limpieza(self, unidad: UnidadHospedaje) -> str:
        raise TransicionEstadoInvalidaError(
            f"La unidad {unidad.codigo_numero} ({self.codigo_estado}) no puede iniciar limpieza directamente."
        )

    def habilitar_disponible(self, unidad: UnidadHospedaje) -> str:
        raise TransicionEstadoInvalidaError(
            f"La unidad {unidad.codigo_numero} ({self.codigo_estado}) requiere pasar por limpieza antes de quedar disponible."
        )

    def enviar_a_mantenimiento(self, unidad: UnidadHospedaje) -> str:
        unidad.estado_unidad = "MANTENIMIENTO"
        unidad.save(update_fields=["estado_unidad"])
        return unidad.estado_unidad


class EstadoDisponible(EstadoUnidadState):
    """Unidad limpia, inspeccionada y lista para recibir huéspedes."""

    @property
    def codigo_estado(self) -> str:
        return "DISPONIBLE"

    def puede_recibir_checkin(self) -> bool:
        return True

    def ocupar_por_checkin(self, unidad: UnidadHospedaje) -> str:
        unidad.estado_unidad = "OCUPADA"
        unidad.save(update_fields=["estado_unidad"])
        return unidad.estado_unidad

    def iniciar_limpieza(self, unidad: UnidadHospedaje) -> str:
        unidad.estado_unidad = "EN_LIMPIEZA"
        unidad.save(update_fields=["estado_unidad"])
        return unidad.estado_unidad


class EstadoOcupada(EstadoUnidadState):
    """Unidad con huésped en estadía activa (Check-in realizado)."""

    @property
    def codigo_estado(self) -> str:
        return "OCUPADA"

    def puede_recibir_checkin(self) -> bool:
        return False

    def marcar_sucia_por_checkout(self, unidad: UnidadHospedaje) -> str:
        unidad.estado_unidad = "SUCIO"
        unidad.save(update_fields=["estado_unidad"])
        return unidad.estado_unidad


class EstadoSucio(EstadoUnidadState):
    """Unidad recién desocupada tras Check-out; bloqueada para nuevos Check-in hasta su aseo."""

    @property
    def codigo_estado(self) -> str:
        return "SUCIO"

    def puede_recibir_checkin(self) -> bool:
        return False

    def iniciar_limpieza(self, unidad: UnidadHospedaje) -> str:
        unidad.estado_unidad = "EN_LIMPIEZA"
        unidad.save(update_fields=["estado_unidad"])
        return unidad.estado_unidad

    def habilitar_disponible(self, unidad: UnidadHospedaje) -> str:
        unidad.estado_unidad = "DISPONIBLE"
        unidad.save(update_fields=["estado_unidad"])
        return unidad.estado_unidad


class EstadoEnLimpieza(EstadoUnidadState):
    """Unidad siendo intervenida por el Personal de Aseo."""

    @property
    def codigo_estado(self) -> str:
        return "EN_LIMPIEZA"

    def puede_recibir_checkin(self) -> bool:
        return False

    def habilitar_disponible(self, unidad: UnidadHospedaje) -> str:
        unidad.estado_unidad = "DISPONIBLE"
        unidad.save(update_fields=["estado_unidad"])
        return unidad.estado_unidad


class EstadoMantenimiento(EstadoUnidadState):
    """Unidad bloqueada por falla técnica o daño mayor de inventario."""

    @property
    def codigo_estado(self) -> str:
        return "MANTENIMIENTO"

    def puede_recibir_checkin(self) -> bool:
        return False

    def iniciar_limpieza(self, unidad: UnidadHospedaje) -> str:
        unidad.estado_unidad = "EN_LIMPIEZA"
        unidad.save(update_fields=["estado_unidad"])
        return unidad.estado_unidad

    def habilitar_disponible(self, unidad: UnidadHospedaje) -> str:
        unidad.estado_unidad = "DISPONIBLE"
        unidad.save(update_fields=["estado_unidad"])
        return unidad.estado_unidad


_MAPA_ESTADOS: dict[str, EstadoUnidadState] = {
    "DISPONIBLE": EstadoDisponible(),
    "OCUPADA": EstadoOcupada(),
    "SUCIO": EstadoSucio(),
    "EN_LIMPIEZA": EstadoEnLimpieza(),
    "MANTENIMIENTO": EstadoMantenimiento(),
}


def obtener_estado_unidad(unidad: UnidadHospedaje) -> EstadoUnidadState:
    """Retorna la instancia de Estado GoF correspondiente al estado actual de la unidad."""
    return _MAPA_ESTADOS.get(unidad.estado_unidad, EstadoDisponible())
