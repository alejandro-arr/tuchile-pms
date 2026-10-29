import os
import django
from datetime import date, timedelta

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tuchile_config.settings")
django.setup()

from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from pms.models import (
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

# Superuser for Django Admin
if not User.objects.filter(username="admin").exists():
    User.objects.create_superuser("admin", "ttapia@turismotuchile.cl", "tuchile2026")

# 1. Zonas
z_litoral, _ = ZonaGeografica.objects.get_or_create(
    codigo_zona="ZC-LITORAL",
    defaults={
        "nombre_zona": "Zona Costera Central",
        "descripcion": "El Tabo, El Quisco, Las Cruces. Alta rotación fines de semana largos y verano.",
    },
)
z_sur, _ = ZonaGeografica.objects.get_or_create(
    codigo_zona="ZS-SUR",
    defaults={
        "nombre_zona": "Zona Sur de Lagos y Archipiélago",
        "descripcion": "Pucón, Villarrica, Lago Llanquihue y Ancud (Chiloé). Estadías prolongadas.",
    },
)

# 2. Sucursales
s_tabo, _ = Sucursal.objects.get_or_create(
    nombre_sucursal="Sede El Tabo",
    defaults={"id_zona": z_litoral, "comuna_ciudad": "El Tabo", "direccion": "Av. Las Cruces 450", "telefono_sede": "+56 9 8111 2233"},
)
s_quisco, _ = Sucursal.objects.get_or_create(
    nombre_sucursal="Sede El Quisco",
    defaults={"id_zona": z_litoral, "comuna_ciudad": "El Quisco", "direccion": "Av. Isidoro Dubournais 890", "telefono_sede": "+56 9 8222 3344"},
)
s_pucon, _ = Sucursal.objects.get_or_create(
    nombre_sucursal="Sede Pucón",
    defaults={"id_zona": z_sur, "comuna_ciudad": "Pucón", "direccion": "Camino al Volcán Km 2", "telefono_sede": "+56 9 8333 4455"},
)
s_ancud, _ = Sucursal.objects.get_or_create(
    nombre_sucursal="Sede Ancud (Chiloé)",
    defaults={"id_zona": z_sur, "comuna_ciudad": "Ancud", "direccion": "Costanera Salvador Allende 310", "telefono_sede": "+56 9 8444 5566"},
)

# 3. Roles
r_super, _ = Rol.objects.get_or_create(
    codigo_rol="SUPERADMIN",
    defaults={"nombre_rol": "Superadministrador", "descripcion_permisos": "Acceso total, métricas globales, tarifas y usuarios."},
)
r_admin, _ = Rol.objects.get_or_create(
    codigo_rol="ADMIN_SEDE",
    defaults={"nombre_rol": "Administrador de Sede / Zona", "descripcion_permisos": "Gestión operativa y financiera zonal."},
)
r_recep, _ = Rol.objects.get_or_create(
    codigo_rol="RECEPCION",
    defaults={"nombre_rol": "Recepcionista / Operador Local", "descripcion_permisos": "Reservas, Check-in, Check-out y Caja Diaria."},
)
r_aseo, _ = Rol.objects.get_or_create(
    codigo_rol="ASEO_MANT",
    defaults={"nombre_rol": "Personal de Aseo y Mantenimiento", "descripcion_permisos": "Vista móvil de limpieza y reporte de daños."},
)

# 4. Usuarios
u_teresa, _ = Usuario.objects.get_or_create(
    rut_usuario="10.234.567-8",
    defaults={
        "id_rol": r_super,
        "id_sucursal": None,
        "nombre_completo": "Teresa Tapia Soto",
        "correo_electronico": "ttapia@tuchile.cl",
        "password_hash": make_password("tuchile2026"),
    },
)
u_recep, _ = Usuario.objects.get_or_create(
    rut_usuario="18.456.789-2",
    defaults={
        "id_rol": r_recep,
        "id_sucursal": s_tabo,
        "nombre_completo": "Camila Muñoz (Recepción El Tabo)",
        "correo_electronico": "recepcion.tabo@tuchile.cl",
        "password_hash": make_password("tuchile2026"),
    },
)
u_aseo, _ = Usuario.objects.get_or_create(
    rut_usuario="19.876.543-1",
    defaults={
        "id_rol": r_aseo,
        "id_sucursal": s_tabo,
        "nombre_completo": "Pedro Soto (Aseo y Mantención)",
        "correo_electronico": "aseo.tabo@tuchile.cl",
        "password_hash": make_password("tuchile2026"),
    },
)

# 5. Tipos de Unidad
t_cab, _ = TipoUnidad.objects.get_or_create(
    codigo_tipo="CAB",
    defaults={"nombre_tipo": "Cabaña Independiente", "incluye_cocina": True, "descripcion": "Cabaña equipada con cocina, gas y vajilla."},
)
t_hab, _ = TipoUnidad.objects.get_or_create(
    codigo_tipo="HAB",
    defaults={"nombre_tipo": "Habitación de Hotel", "incluye_cocina": False, "descripcion": "Habitación con baño privado y servicios estándar."},
)

# 6. Unidades de Hospedaje
u1, _ = UnidadHospedaje.objects.get_or_create(
    id_sucursal=s_tabo,
    codigo_numero="Cabaña 1 (Vista Mar)",
    defaults={"id_tipo_unidad": t_cab, "capacidad_max_pax": 4, "cantidad_camas": 3, "estado_unidad": "DISPONIBLE"},
)
u2, _ = UnidadHospedaje.objects.get_or_create(
    id_sucursal=s_tabo,
    codigo_numero="Cabaña 2 (Familiar)",
    defaults={"id_tipo_unidad": t_cab, "capacidad_max_pax": 6, "cantidad_camas": 4, "estado_unidad": "OCUPADA"},
)
u3, _ = UnidadHospedaje.objects.get_or_create(
    id_sucursal=s_tabo,
    codigo_numero="Habitación 101",
    defaults={"id_tipo_unidad": t_hab, "capacidad_max_pax": 2, "cantidad_camas": 1, "estado_unidad": "EN_LIMPIEZA"},
)
u4, _ = UnidadHospedaje.objects.get_or_create(
    id_sucursal=s_tabo,
    codigo_numero="Cabaña 5 (Bosque)",
    defaults={"id_tipo_unidad": t_cab, "capacidad_max_pax": 5, "cantidad_camas": 3, "estado_unidad": "SUCIO"},
)
u5, _ = UnidadHospedaje.objects.get_or_create(
    id_sucursal=s_pucon,
    codigo_numero="Cabaña Volcán 1",
    defaults={"id_tipo_unidad": t_cab, "capacidad_max_pax": 6, "cantidad_camas": 4, "estado_unidad": "DISPONIBLE"},
)
u6, _ = UnidadHospedaje.objects.get_or_create(
    id_sucursal=s_ancud,
    codigo_numero="Habitación Palafito 201",
    defaults={"id_tipo_unidad": t_hab, "capacidad_max_pax": 2, "cantidad_camas": 1, "estado_unidad": "MANTENIMIENTO"},
)

# 7. Inventario Crítico
for uni in [u1, u2, u4, u5]:
    InventarioUnidad.objects.get_or_create(
        id_unidad=uni, nombre_item="Televisor Smart TV 43\"", defaults={"categoria_item": "Electrodoméstico", "cantidad_estandar": 1, "valor_reposicion": 180000}
    )
    InventarioUnidad.objects.get_or_create(
        id_unidad=uni, nombre_item="Cilindro de Gas 15 Kg", defaults={"categoria_item": "Cocina / Gas", "cantidad_estandar": 1, "valor_reposicion": 55000}
    )
    InventarioUnidad.objects.get_or_create(
        id_unidad=uni, nombre_item="Juego de Sábanas y Plumón", defaults={"categoria_item": "Ropa de Cama", "cantidad_estandar": uni.cantidad_camas, "valor_reposicion": 35000}
    )
    InventarioUnidad.objects.get_or_create(
        id_unidad=uni, nombre_item="Set de Vajilla y Cubiertos", defaults={"categoria_item": "Menaje Cocina", "cantidad_estandar": uni.capacidad_max_pax, "valor_reposicion": 25000}
    )

# 8. Tarifas por Temporada
TemporadaTarifa.objects.get_or_create(
    id_zona=z_litoral, id_tipo_unidad=t_cab, nombre_temporada="Temporada Alta / Fin de Semana Largo",
    defaults={"fecha_inicio": date(2026, 1, 1), "fecha_fin": date(2026, 12, 31), "precio_noche_clp": 60000, "porcentaje_abono_min": 50}
)
TemporadaTarifa.objects.get_or_create(
    id_zona=z_litoral, id_tipo_unidad=t_hab, nombre_temporada="Tarifa Estándar Habitación Litoral",
    defaults={"fecha_inicio": date(2026, 1, 1), "fecha_fin": date(2026, 12, 31), "precio_noche_clp": 38000, "porcentaje_abono_min": 50}
)
TemporadaTarifa.objects.get_or_create(
    id_zona=z_sur, id_tipo_unidad=t_cab, nombre_temporada="Temporada Alta Sur (Pucón / Chiloé)",
    defaults={"fecha_inicio": date(2026, 1, 1), "fecha_fin": date(2026, 12, 31), "precio_noche_clp": 85000, "porcentaje_abono_min": 50}
)

# 9. Pasajeros
p1, _ = Pasajero.objects.get_or_create(
    num_documento="15.432.198-K",
    defaults={"tipo_documento": "RUT", "nombre_completo": "Juan Pérez Gómez", "telefono": "+56 9 9123 4567", "correo_electronico": "jperez@correo.cl", "procedencia_ciudad": "Santiago"},
)
p2, _ = Pasajero.objects.get_or_create(
    num_documento="17.654.321-5",
    defaults={"tipo_documento": "RUT", "nombre_completo": "María González Soto", "telefono": "+56 9 8765 4321", "correo_electronico": "mgonzalez@correo.cl", "procedencia_ciudad": "Rancagua"},
)

# 10. Reservas y Caja Diaria
hoy = date.today()
r1, _ = Reserva.objects.get_or_create(
    id_pasajero_titular=p1,
    id_unidad=u2,
    fecha_checkin=hoy,
    defaults={
        "id_usuario_crea": u_recep,
        "fecha_checkout": hoy + timedelta(days=2),
        "cantidad_pasajeros": 4,
        "monto_alojamiento": 120000,
        "monto_abono_pagado": 60000,
        "monto_total_final": 120000,
        "estado_reserva": "CONFIRMADA",
    },
)
r2, _ = Reserva.objects.get_or_create(
    id_pasajero_titular=p2,
    id_unidad=u1,
    fecha_checkin=hoy + timedelta(days=1),
    defaults={
        "id_usuario_crea": u_recep,
        "fecha_checkout": hoy + timedelta(days=4),
        "cantidad_pasajeros": 3,
        "monto_alojamiento": 180000,
        "monto_abono_pagado": 90000,
        "monto_total_final": 180000,
        "estado_reserva": "CONFIRMADA",
    },
)

caja, _ = CajaDiaria.objects.get_or_create(
    id_sucursal=s_tabo,
    estado_caja="ABIERTA",
    defaults={
        "id_usuario_recep": u_recep,
        "monto_inicial": 50000,
        "total_efectivo": 60000,
        "total_transferencias": 90000,
        "total_tarjetas": 0,
    },
)

PagoMovimiento.objects.get_or_create(
    id_reserva=r1,
    id_caja=caja,
    tipo_movimiento="ABONO_RESERVA",
    defaults={"medio_pago": "EFECTIVO", "monto": 60000, "num_comprobante_voucher": "REC-00101"},
)
PagoMovimiento.objects.get_or_create(
    id_reserva=r2,
    id_caja=caja,
    tipo_movimiento="ABONO_RESERVA",
    defaults={"medio_pago": "TRANSFERENCIA", "monto": 90000, "num_comprobante_voucher": "TRF-88421"},
)

print("Seed data loaded successfully!")
