from django.contrib import admin
from .models import (
    ZonaGeografica,
    Sucursal,
    Rol,
    Usuario,
    TipoUnidad,
    UnidadHospedaje,
    InventarioUnidad,
    TemporadaTarifa,
    Pasajero,
    Reserva,
    ReservaAcompanante,
    CajaDiaria,
    PagoMovimiento,
    IncidenciaAseo,
)

admin.site.site_header = "Turismo TUCHILE - Administración PMS"
admin.site.site_title = "PMS Turismo TUCHILE"
admin.site.index_title = "Mantenedores de las 14 Tablas del Sistema"


@admin.register(ZonaGeografica)
class ZonaGeograficaAdmin(admin.ModelAdmin):
    list_display = ("id_zona", "codigo_zona", "nombre_zona", "descripcion")
    search_fields = ("codigo_zona", "nombre_zona")


@admin.register(Sucursal)
class SucursalAdmin(admin.ModelAdmin):
    list_display = ("id_sucursal", "nombre_sucursal", "comuna_ciudad", "id_zona", "telefono_sede", "estado_sucursal")
    list_filter = ("id_zona", "estado_sucursal")


@admin.register(Rol)
class RolAdmin(admin.ModelAdmin):
    list_display = ("id_rol", "codigo_rol", "nombre_rol", "descripcion_permisos")


@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    list_display = ("id_usuario", "rut_usuario", "nombre_completo", "correo_electronico", "id_rol", "id_sucursal", "activo")
    list_filter = ("id_rol", "id_sucursal", "activo")
    search_fields = ("rut_usuario", "nombre_completo", "correo_electronico")


@admin.register(TipoUnidad)
class TipoUnidadAdmin(admin.ModelAdmin):
    list_display = ("id_tipo_unidad", "codigo_tipo", "nombre_tipo", "incluye_cocina")


@admin.register(UnidadHospedaje)
class UnidadHospedajeAdmin(admin.ModelAdmin):
    list_display = ("id_unidad", "codigo_numero", "id_sucursal", "id_tipo_unidad", "capacidad_max_pax", "cantidad_camas", "estado_unidad")
    list_filter = ("id_sucursal", "id_tipo_unidad", "estado_unidad")
    search_fields = ("codigo_numero",)


@admin.register(InventarioUnidad)
class InventarioUnidadAdmin(admin.ModelAdmin):
    list_display = ("id_item_inventario", "nombre_item", "id_unidad", "categoria_item", "cantidad_estandar", "valor_reposicion", "estado_item")
    list_filter = ("categoria_item", "estado_item")


@admin.register(TemporadaTarifa)
class TemporadaTarifaAdmin(admin.ModelAdmin):
    list_display = ("id_tarifa", "nombre_temporada", "id_zona", "id_tipo_unidad", "fecha_inicio", "fecha_fin", "precio_noche_clp", "porcentaje_abono_min")
    list_filter = ("id_zona", "id_tipo_unidad")


@admin.register(Pasajero)
class PasajeroAdmin(admin.ModelAdmin):
    list_display = ("id_pasajero", "tipo_documento", "num_documento", "nombre_completo", "telefono", "correo_electronico", "procedencia_ciudad")
    search_fields = ("num_documento", "nombre_completo")


@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = ("id_reserva", "id_pasajero_titular", "id_unidad", "fecha_checkin", "fecha_checkout", "monto_alojamiento", "monto_abono_pagado", "estado_reserva")
    list_filter = ("estado_reserva", "id_unidad__id_sucursal")


@admin.register(ReservaAcompanante)
class ReservaAcompananteAdmin(admin.ModelAdmin):
    list_display = ("id_reserva", "id_pasajero", "parentesco_relacion")


@admin.register(CajaDiaria)
class CajaDiariaAdmin(admin.ModelAdmin):
    list_display = ("id_caja", "id_sucursal", "id_usuario_recep", "fecha_apertura", "total_efectivo", "total_transferencias", "total_tarjetas", "estado_caja")
    list_filter = ("id_sucursal", "estado_caja")


@admin.register(PagoMovimiento)
class PagoMovimientoAdmin(admin.ModelAdmin):
    list_display = ("id_pago", "id_reserva", "id_caja", "tipo_movimiento", "medio_pago", "monto", "num_comprobante_voucher", "fecha_hora_pago")
    list_filter = ("tipo_movimiento", "medio_pago")


@admin.register(IncidenciaAseo)
class IncidenciaAseoAdmin(admin.ModelAdmin):
    list_display = ("id_incidencia", "id_unidad", "tipo_incidencia", "descripcion_problema", "monto_cargo_asociado", "estado_incidencia", "fecha_reporte")
    list_filter = ("tipo_incidencia", "estado_incidencia")
