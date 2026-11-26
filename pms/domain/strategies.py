"""Patrón GoF: Strategy para Cálculo Dinámico de Tarifas por Temporada y Macrozona.

Permite intercambiar dinámicamente la fórmula de tarificación según las reglas de negocio de
Turismo TUCHILE:
1. `TarifaTemporadaBajaStrategy`: Tarifa base sin recargo.
2. `TarifaCosteraFinDeSemanaStrategy`: Recargo de alta rotación en Zona Costera (El Tabo / El Quisco).
3. `TarifaSurEstadiaProlongadaStrategy`: Descuento del 10% en Zona Sur (Pucón / Ancud) por estadías >= 5 noches.
4. `TarifaFiestasPatriasVeranoStrategy`: Recargo de temporada alta (+20%) y abono mínimo garantizado del 50%.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pms.models import TemporadaTarifa, UnidadHospedaje


@dataclass(frozen=True)
class CotizacionReserva:
    """Resultado estructurado del cálculo tarifario de una reserva."""

    nombre_estrategia: str
    noches: int
    precio_base_noche: Decimal
    monto_total_alojamiento: Decimal
    abono_minimo_sugerido: Decimal


class EstrategiaTarifa(ABC):
    """Interfaz Strategy para el cálculo del valor de estadía y abono mínimo."""

    @property
    @abstractmethod
    def nombre_regla(self) -> str:
        """Nombre descriptivo de la estrategia aplicada."""

    @abstractmethod
    def calcular_total(self, precio_base_noche: Decimal, noches: int) -> Decimal:
        """Calcula el monto total de alojamiento para la cantidad de noches dada."""

    def calcular_cotizacion(
        self,
        precio_base_noche: Decimal,
        noches: int,
        porcentaje_abono: Decimal = Decimal("50"),
    ) -> CotizacionReserva:
        noches_validas = max(1, noches)
        total = self.calcular_total(precio_base_noche, noches_validas).quantize(Decimal("1"))
        abono_min = ((total * porcentaje_abono) / Decimal("100")).quantize(Decimal("1"))
        return CotizacionReserva(
            nombre_estrategia=self.nombre_regla,
            noches=noches_validas,
            precio_base_noche=precio_base_noche,
            monto_total_alojamiento=total,
            abono_minimo_sugerido=abono_min,
        )


class TarifaEstandarStrategy(EstrategiaTarifa):
    """Estrategia base: precio lineal por noche."""

    @property
    def nombre_regla(self) -> str:
        return "Tarifa Estándar Temporada Base"

    def calcular_total(self, precio_base_noche: Decimal, noches: int) -> Decimal:
        return precio_base_noche * Decimal(noches)


class TarifaSurEstadiaProlongadaStrategy(EstrategiaTarifa):
    """Estrategia para Zona Sur (Pucón, Villarrica, Ancud): 10% de descuento en estadías >= 5 noches."""

    FACTOR_DESCUENTO_SUR: Decimal = Decimal("0.90")

    @property
    def nombre_regla(self) -> str:
        return "Tarifa Zona Sur - Beneficio Estadía Prolongada (-10%)"

    def calcular_total(self, precio_base_noche: Decimal, noches: int) -> Decimal:
        subtotal = precio_base_noche * Decimal(noches)
        return subtotal * self.FACTOR_DESCUENTO_SUR


class TarifaTemporadaAltaFestivosStrategy(EstrategiaTarifa):
    """Estrategia para Fiestas Patrias (Septiembre) y Verano (Enero-Febrero): factor de alta demanda."""

    FACTOR_TEMPORADA_ALTA: Decimal = Decimal("1.15")

    @property
    def nombre_regla(self) -> str:
        return "Tarifa Temporada Alta / Fiestas Patrias (+15%)"

    def calcular_total(self, precio_base_noche: Decimal, noches: int) -> Decimal:
        return (precio_base_noche * Decimal(noches)) * self.FACTOR_TEMPORADA_ALTA


def resolver_estrategia_tarifa(
    unidad: UnidadHospedaje,
    fecha_checkin: date,
    fecha_checkout: date,
) -> tuple[EstrategiaTarifa, Decimal, Decimal]:
    """Contexto Strategy: selecciona automáticamente la estrategia según Macrozona, Temporada y duración."""
    zona = unidad.id_sucursal.id_zona
    tarifa_bd = TemporadaTarifa.objects.filter(
        id_zona=zona,
        id_tipo_unidad=unidad.id_tipo_unidad,
    ).first()

    precio_base = tarifa_bd.precio_noche_clp if tarifa_bd else Decimal("50000")
    pct_abono = tarifa_bd.porcentaje_abono_min if tarifa_bd else Decimal("50")
    noches = max(1, (fecha_checkout - fecha_checkin).days)

    # 1. Si es Fiestas Patrias (Septiembre) o pleno Verano (Enero/Febrero)
    if fecha_checkin.month in (1, 2, 9):
        return TarifaTemporadaAltaFestivosStrategy(), precio_base, pct_abono

    # 2. Si es Macrozona Sur (ZS-SUR) y estadía prolongada (>= 5 noches)
    if "SUR" in (zona.codigo_zona or "").upper() and noches >= 5:
        return TarifaSurEstadiaProlongadaStrategy(), precio_base, pct_abono

    # 3. Tarifa estándar
    return TarifaEstandarStrategy(), precio_base, pct_abono
