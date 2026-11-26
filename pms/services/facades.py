"""Patrón Estructural GoF: Facade (`OperacionesPMSFacade`) para orquestar flujos complejos del PMS.

Desacopla las vistas HTTP (`views.py`) de la coordinación transaccional entre múltiples subsistemas:
1. Subsistema de Disponibilidad (< 2 segundos sin overbooking) y Cotización (`Strategy`).
2. Subsistema de Check-in (cobro de saldo en `CajaDiaria` + transición `EstadoUnidadState` a `OCUPADA`).
3. Subsistema de Check-out (revisión de `InventarioUnidad` + cobros extra en `CajaDiaria` + ticket en
   `IncidenciaAseo` + cambio automático de unidad a estado `'SUCIO'` + auditoría ISO A.8.15).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import time

from django.db import transaction
from django.utils import timezone

from pms.domain.states import TransicionEstadoInvalidaError, obtener_estado_unidad
from pms.domain.strategies import CotizacionReserva, resolver_estrategia_tarifa
from pms.models import (
    CajaDiaria,
    IncidenciaAseo,
    Pasajero,
    PagoMovimiento,
    Reserva,
    UnidadHospedaje,
    Usuario,
)
from pms.security.constants import SLA_MAX_LATENCIA_DISPONIBILIDAD_SEG
from pms.security.controls import enmascarar_rut_pasaporte, registrar_evento_auditoria


class OverbookingError(ValueError):
    """Error lanzado cuando la unidad ya tiene una reserva activa en el rango de fechas solicitado."""


class OperacionesPMSFacade:
    """Fachada Estructural GoF que unifica las operaciones críticas del PMS de Turismo TUCHILE."""

    # --------------------------------------------------------------------------
    # 1. MOTOR DE DISPONIBILIDAD EN TIEMPO REAL (< 2 SEGUNDOS) Y RESERVAS
    # --------------------------------------------------------------------------
    def verificar_disponibilidad_sin_overbooking(
        self,
        unidad: UnidadHospedaje,
        fecha_checkin: date,
        fecha_checkout: date,
    ) -> tuple[bool, float]:
        """Consulta disponibilidad verificando traslape de fechas y midiendo latencia (< 2.0s)."""
        inicio = time.perf_counter()
        hay_choque = (
            Reserva.objects.filter(
                id_unidad=unidad,
                fecha_checkin__lt=fecha_checkout,
                fecha_checkout__gt=fecha_checkin,
            )
            .exclude(estado_reserva="ANULADA")
            .exists()
        )
        latencia_seg = time.perf_counter() - inicio
        return (not hay_choque), latencia_seg

    def cotizar_estadia(
        self,
        unidad: UnidadHospedaje,
        fecha_checkin: date,
        fecha_checkout: date,
    ) -> CotizacionReserva:
        """Calcula la tarifa aplicable delegando en el patrón Strategy."""
        estrategia, precio_base, pct_abono = resolver_estrategia_tarifa(unidad, fecha_checkin, fecha_checkout)
        noches = max(1, (fecha_checkout - fecha_checkin).days)
        return estrategia.calcular_cotizacion(precio_base, noches, pct_abono)

    @transaction.atomic
    def registrar_reserva_segura(
        self,
        *,
        rut_pasajero: str,
        nombre_pasajero: str,
        telefono: str,
        correo: str,
        procedencia: str,
        unidad: UnidadHospedaje,
        fecha_checkin: date,
        fecha_checkout: date,
        cantidad_pasajeros: int,
        monto_abono: Decimal,
        medio_pago: str,
        usuario_operador: Usuario,
    ) -> tuple[Reserva, CotizacionReserva, float]:
        """Orquesta validación anti-overbooking (< 2s), cálculo Strategy, registro de abono y log ISO A.8.15."""
        if fecha_checkout <= fecha_checkin:
            raise ValueError("La fecha de salida debe ser posterior a la fecha de ingreso.")

        if cantidad_pasajeros > unidad.capacidad_max_pax:
            raise ValueError(
                f"La cantidad de huéspedes ({cantidad_pasajeros}) supera la capacidad de {unidad.codigo_numero}."
            )

        disponible, latencia = self.verificar_disponibilidad_sin_overbooking(unidad, fecha_checkin, fecha_checkout)
        if not disponible:
            raise OverbookingError(
                f"Conflicto de disponibilidad: {unidad.codigo_numero} ya posee reserva en ese rango."
            )

        pasajero, _ = Pasajero.objects.update_or_create(
            num_documento=rut_pasajero,
            defaults={
                "nombre_completo": nombre_pasajero,
                "telefono": telefono or "+56 9 0000 0000",
                "correo_electronico": correo,
                "procedencia_ciudad": procedencia or "Santiago",
            },
        )

        cotizacion = self.cotizar_estadia(unidad, fecha_checkin, fecha_checkout)
        nueva_reserva = Reserva.objects.create(
            id_pasajero_titular=pasajero,
            id_unidad=unidad,
            id_usuario_crea=usuario_operador,
            fecha_checkin=fecha_checkin,
            fecha_checkout=fecha_checkout,
            cantidad_pasajeros=cantidad_pasajeros,
            monto_alojamiento=cotizacion.monto_total_alojamiento,
            monto_abono_pagado=monto_abono,
            monto_total_final=cotizacion.monto_total_alojamiento,
            estado_reserva="CONFIRMADA" if monto_abono > 0 else "PENDIENTE",
        )

        if monto_abono > 0:
            self._imputar_movimiento_caja(
                reserva=nueva_reserva,
                tipo_movimiento="ABONO_RESERVA",
                medio_pago=medio_pago,
                monto=monto_abono,
                voucher=f"ABO-{nueva_reserva.id_reserva:04d}",
            )

        registrar_evento_auditoria(
            accion="RESERVA_CREADA",
            usuario_identificador=usuario_operador.correo_electronico,
            rol=usuario_operador.id_rol.codigo_rol,
            detalle=(
                f"Reserva #{nueva_reserva.id_reserva} | Unidad={unidad.codigo_numero} | "
                f"Pasajero={enmascarar_rut_pasaporte(rut_pasajero)} | "
                f"Estrategia={cotizacion.nombre_estrategia} | Latencia={latencia:.4f}s "
                f"(SLA<{SLA_MAX_LATENCIA_DISPONIBILIDAD_SEG}s)"
            ),
        )
        return nueva_reserva, cotizacion, latencia

    # --------------------------------------------------------------------------
    # 2. ORQUESTACIÓN DE CHECK-IN (CAJA + MÁQUINA DE ESTADOS `STATE`)
    # --------------------------------------------------------------------------
    @transaction.atomic
    def ejecutar_checkin(
        self,
        *,
        reserva: Reserva,
        acepta_condiciones: bool,
        firma_digital_base64: str,
        medio_pago: str,
        num_voucher: str,
        usuario_operador: Usuario,
    ) -> Reserva:
        """Ejecuta el Check-in validando el estado de la unidad con el patrón State."""
        if not acepta_condiciones:
            raise ValueError("El huésped debe aceptar las condiciones antes de entregar las llaves.")

        unidad = reserva.id_unidad
        estado_actual = obtener_estado_unidad(unidad)
        if not estado_actual.puede_recibir_checkin() and unidad.estado_unidad != "OCUPADA":
            raise TransicionEstadoInvalidaError(
                f"La unidad {unidad.codigo_numero} está en estado '{unidad.get_estado_unidad_display()}' "
                "y no puede recibir Check-in hasta finalizar su limpieza."
            )

        saldo = reserva.saldo_pendiente
        if saldo > 0:
            self._imputar_movimiento_caja(
                reserva=reserva,
                tipo_movimiento="SALDO_CHECKIN",
                medio_pago=medio_pago,
                monto=saldo,
                voucher=num_voucher or f"CHK-{reserva.id_reserva:04d}",
            )
            reserva.monto_abono_pagado += saldo

        reserva.acepta_condiciones = True
        reserva.firma_digital_base64 = firma_digital_base64
        reserva.llaves_entregadas = True
        reserva.estado_reserva = "CHECKIN_ACTIVO"
        reserva.fecha_hora_checkin_real = timezone.now()
        reserva.save()

        if estado_actual.puede_recibir_checkin():
            estado_actual.ocupar_por_checkin(unidad)
        else:
            unidad.estado_unidad = "OCUPADA"
            unidad.save(update_fields=["estado_unidad"])

        registrar_evento_auditoria(
            accion="CHECKIN_EJECUTADO",
            usuario_identificador=usuario_operador.correo_electronico,
            rol=usuario_operador.id_rol.codigo_rol,
            detalle=f"Reserva #{reserva.id_reserva} | Unidad={unidad.codigo_numero} -> OCUPADA | Saldo=${saldo:,.0f}",
        )
        return reserva

    # --------------------------------------------------------------------------
    # 3. ORQUESTACIÓN DE CHECK-OUT (INVENTARIO + COBROS + ASEO + STATE 'SUCIO')
    # --------------------------------------------------------------------------
    @transaction.atomic
    def ejecutar_checkout(
        self,
        *,
        reserva: Reserva,
        consumos_multas_extra: Decimal,
        medio_pago: str,
        observacion_dano: str,
        usuario_operador: Usuario,
    ) -> Reserva:
        """Orquesta en una sola fachada el Check-out: cobros extra, ticket de daño y paso automático a 'SUCIO'."""
        if consumos_multas_extra > 0:
            reserva.monto_consumos_multas += consumos_multas_extra
            reserva.monto_total_final = reserva.monto_alojamiento + reserva.monto_consumos_multas
            reserva.monto_abono_pagado += consumos_multas_extra
            self._imputar_movimiento_caja(
                reserva=reserva,
                tipo_movimiento="CARGO_CHECKOUT",
                medio_pago=medio_pago,
                monto=consumos_multas_extra,
                voucher=f"OUT-{reserva.id_reserva:04d}",
            )

        if observacion_dano:
            IncidenciaAseo.objects.create(
                id_unidad=reserva.id_unidad,
                id_usuario_reporta=usuario_operador,
                id_reserva=reserva,
                tipo_incidencia="DANO_INVENTARIO",
                descripcion_problema=observacion_dano,
                monto_cargo_asociado=consumos_multas_extra,
                estado_incidencia="PENDIENTE",
            )

        reserva.llaves_entregadas = False
        reserva.estado_reserva = "FINALIZADA"
        reserva.fecha_hora_checkout_real = timezone.now()
        reserva.save()

        # Transición mediante Patrón State -> 'SUCIO'
        unidad = reserva.id_unidad
        estado_actual = obtener_estado_unidad(unidad)
        if unidad.estado_unidad == "OCUPADA":
            estado_actual.marcar_sucia_por_checkout(unidad)
        else:
            unidad.estado_unidad = "SUCIO"
            unidad.save(update_fields=["estado_unidad"])

        registrar_evento_auditoria(
            accion="CHECKOUT_EJECUTADO",
            usuario_identificador=usuario_operador.correo_electronico,
            rol=usuario_operador.id_rol.codigo_rol,
            detalle=(
                f"Reserva #{reserva.id_reserva} | Unidad={unidad.codigo_numero} -> SUCIO | "
                f"CargosExtra=${consumos_multas_extra:,.0f}"
            ),
        )
        return reserva

    # --------------------------------------------------------------------------
    # 4. SUBSISTEMA DE CAJA DIARIA (APERTURA, MOVIMIENTOS Y ARQUEO/CIERRE DE TURNO)
    # --------------------------------------------------------------------------
    def _imputar_movimiento_caja(
        self,
        *,
        reserva: Reserva | None,
        tipo_movimiento: str,
        medio_pago: str,
        monto: Decimal,
        voucher: str,
    ) -> PagoMovimiento | None:
        caja = CajaDiaria.objects.filter(estado_caja="ABIERTA").first()
        if not caja:
            return None
        mov = PagoMovimiento.objects.create(
            id_reserva=reserva,
            id_caja=caja,
            tipo_movimiento=tipo_movimiento,
            medio_pago=medio_pago,
            monto=monto,
            num_comprobante_voucher=voucher[:40],
        )
        if medio_pago == "EFECTIVO":
            caja.total_efectivo += monto
        elif medio_pago == "TRANSFERENCIA":
            caja.total_transferencias += monto
        else:
            caja.total_tarjetas += monto
        caja.save()
        return mov

    @transaction.atomic
    def cerrar_arqueo_caja(
        self,
        caja: CajaDiaria,
        observacion_cuadratura: str,
        usuario_operador: Usuario,
    ) -> CajaDiaria:
        """Realiza el cierre y arqueo de caja por turno registrando evento de auditoría ISO A.8.15."""
        caja.estado_caja = "CERRADA"
        caja.fecha_cierre = timezone.now()
        caja.observacion_cuadratura = (observacion_cuadratura or "Arqueo de turno conforme.")[:250]
        caja.save()

        registrar_evento_auditoria(
            accion="CAJA_DIARIA_CERRADA",
            usuario_identificador=usuario_operador.correo_electronico,
            rol=usuario_operador.id_rol.codigo_rol,
            detalle=f"Caja #{caja.id_caja} cerrada | BalanceNeto=${caja.total_recaudado:,.0f}",
        )
        return caja
