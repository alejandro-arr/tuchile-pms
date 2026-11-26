"""Patrón Creacional GoF: Factory Method para instanciación tipada de Unidades de Hospedaje.

Resuelve la problemática de negocio de Turismo TUCHILE diferenciando:
- Cabañas (`CabanaUnidadFactory`): Requieren kit crítico de menaje, cocina y cilindro de gas 15 Kg.
- Habitaciones de Hotel (`HabitacionHotelFactory`): Servicios estandarizados sin gas ni menaje de cocina.

Extensibilidad (Principio Abierto/Cerrado - SOLID):
Para agregar un nuevo tipo de alojamiento en vivo (ej. `DomoGlampingFactory`), basta con heredar
de `UnidadHospedajeFactory` e implementar `obtener_plantilla_inventario()`, sin modificar el código cliente.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from pms.models import InventarioUnidad, Sucursal, TipoUnidad, UnidadHospedaje


@dataclass(frozen=True)
class PlantillaItemInventario:
    """Especificación inmutable de un ítem del kit estándar de una unidad."""

    nombre_item: str
    categoria_item: str
    cantidad_por_unidad: int
    valor_reposicion: Decimal


class UnidadHospedajeFactory(ABC):
    """Creador Abstracto (Factory Method GoF) para unidades de hospedaje de Turismo TUCHILE."""

    @abstractmethod
    def codigo_tipo_esperado(self) -> str:
        """Retorna el código de tipo de unidad ('CAB', 'HAB', etc.)."""

    @abstractmethod
    def obtener_plantilla_inventario(self, capacidad_pax: int, camas: int) -> list[PlantillaItemInventario]:
        """Factory Method que define el kit de inventario inicial según la tipología de unidad."""

    @transaction.atomic
    def crear_unidad_con_inventario(
        self,
        sucursal: Sucursal,
        tipo_unidad: TipoUnidad,
        codigo_numero: str,
        capacidad_max_pax: int,
        cantidad_camas: int,
        observaciones: str = "",
    ) -> UnidadHospedaje:
        """Template/Operation del Creador: crea la unidad y puebla automáticamente su inventario crítico."""
        unidad = UnidadHospedaje.objects.create(
            id_sucursal=sucursal,
            id_tipo_unidad=tipo_unidad,
            codigo_numero=codigo_numero,
            capacidad_max_pax=capacidad_max_pax,
            cantidad_camas=cantidad_camas,
            estado_unidad="DISPONIBLE",
            observaciones=observaciones or f"Creada vía {self.__class__.__name__}",
        )

        for item in self.obtener_plantilla_inventario(capacidad_max_pax, cantidad_camas):
            InventarioUnidad.objects.create(
                id_unidad=unidad,
                nombre_item=item.nombre_item,
                categoria_item=item.categoria_item,
                cantidad_estandar=item.cantidad_por_unidad,
                valor_reposicion=item.valor_reposicion,
                estado_item="OPERATIVO",
            )
        return unidad


class CabanaUnidadFactory(UnidadHospedajeFactory):
    """Creador Concreto para Cabañas: incluye inventario crítico de cilindro de gas, menaje y ropa de cama."""

    def codigo_tipo_esperado(self) -> str:
        return "CAB"

    def obtener_plantilla_inventario(self, capacidad_pax: int, camas: int) -> list[PlantillaItemInventario]:
        return [
            PlantillaItemInventario(
                nombre_item="Cilindro de Gas 15 Kg",
                categoria_item="Cocina / Gas",
                cantidad_por_unidad=1,
                valor_reposicion=Decimal("55000"),
            ),
            PlantillaItemInventario(
                nombre_item="Set de Vajilla y Cubiertos",
                categoria_item="Menaje Cocina",
                cantidad_por_unidad=max(2, capacidad_pax),
                valor_reposicion=Decimal("25000"),
            ),
            PlantillaItemInventario(
                nombre_item='Televisor Smart TV 43"',
                categoria_item="Electrodoméstico",
                cantidad_por_unidad=1,
                valor_reposicion=Decimal("180000"),
            ),
            PlantillaItemInventario(
                nombre_item="Juego de Sábanas y Plumón",
                categoria_item="Ropa de Cama",
                cantidad_por_unidad=max(1, camas),
                valor_reposicion=Decimal("35000"),
            ),
        ]


class HabitacionHotelFactory(UnidadHospedajeFactory):
    """Creador Concreto para Habitaciones de Hotel: kit hotelero estandarizado sin cocina ni gas."""

    def codigo_tipo_esperado(self) -> str:
        return "HAB"

    def obtener_plantilla_inventario(self, capacidad_pax: int, camas: int) -> list[PlantillaItemInventario]:
        return [
            PlantillaItemInventario(
                nombre_item='Televisor Smart TV 43"',
                categoria_item="Electrodoméstico",
                cantidad_por_unidad=1,
                valor_reposicion=Decimal("180000"),
            ),
            PlantillaItemInventario(
                nombre_item="Juego de Sábanas y Toallas Hotel",
                categoria_item="Ropa de Cama",
                cantidad_por_unidad=max(1, camas),
                valor_reposicion=Decimal("30000"),
            ),
            PlantillaItemInventario(
                nombre_item="Frigobar Estándar Habitación",
                categoria_item="Equipamiento Hotel",
                cantidad_por_unidad=1,
                valor_reposicion=Decimal("95000"),
            ),
        ]


def seleccionar_factory_unidad(tipo_unidad: TipoUnidad) -> UnidadHospedajeFactory:
    """Resuelve dinámicamente la fábrica concreta según el tipo de unidad (Cabaña vs. Habitación)."""
    codigo = (tipo_unidad.codigo_tipo or "").upper()
    if codigo.startswith("CAB") or tipo_unidad.incluye_cocina:
        return CabanaUnidadFactory()
    return HabitacionHotelFactory()
