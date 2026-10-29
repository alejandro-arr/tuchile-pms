from django.db import models
from django.utils import timezone


# 1. ZONA_GEOGRAFICA
class ZonaGeografica(models.Model):
    id_zona = models.AutoField(primary_key=True)
    codigo_zona = models.CharField(max_length=15, unique=True)
    nombre_zona = models.CharField(max_length=80)
    descripcion = models.CharField(max_length=250, blank=True, null=True)

    class Meta:
        db_table = "ZONA_GEOGRAFICA"
        verbose_name = "Zona Geográfica"
        verbose_name_plural = "01. Zonas Geográficas"

    def __str__(self):
        return f"{self.codigo_zona} - {self.nombre_zona}"


# 2. SUCURSAL
class Sucursal(models.Model):
    ESTADOS = [
        ("ACTIVA", "Activa"),
        ("INACTIVA", "Inactiva"),
    ]
    id_sucursal = models.AutoField(primary_key=True)
    id_zona = models.ForeignKey(
        ZonaGeografica, on_delete=models.PROTECT, db_column="id_zona", related_name="sucursales"
    )
    nombre_sucursal = models.CharField(max_length=80)
    comuna_ciudad = models.CharField(max_length=60)
    direccion = models.CharField(max_length=150)
    telefono_sede = models.CharField(max_length=20)
    estado_sucursal = models.CharField(max_length=15, choices=ESTADOS, default="ACTIVA")

    class Meta:
        db_table = "SUCURSAL"
        verbose_name = "Sucursal"
        verbose_name_plural = "02. Sucursales"

    def __str__(self):
        return f"{self.nombre_sucursal} ({self.comuna_ciudad})"


# 3. ROL
class Rol(models.Model):
    CODIGOS_ROL = [
        ("SUPERADMIN", "Superadministrador"),
        ("ADMIN_SEDE", "Administrador de Sede / Zona"),
        ("RECEPCION", "Recepcionista / Operador Local"),
        ("ASEO_MANT", "Personal de Aseo y Mantenimiento"),
    ]
    id_rol = models.AutoField(primary_key=True)
    codigo_rol = models.CharField(max_length=20, unique=True, choices=CODIGOS_ROL)
    nombre_rol = models.CharField(max_length=60)
    descripcion_permisos = models.CharField(max_length=250)

    class Meta:
        db_table = "ROL"
        verbose_name = "Rol"
        verbose_name_plural = "03. Roles"

    def __str__(self):
        return self.nombre_rol


# 4. USUARIO
class Usuario(models.Model):
    id_usuario = models.AutoField(primary_key=True)
    id_rol = models.ForeignKey(Rol, on_delete=models.PROTECT, db_column="id_rol", related_name="usuarios")
    id_sucursal = models.ForeignKey(
        Sucursal, on_delete=models.SET_NULL, db_column="id_sucursal", blank=True, null=True, related_name="usuarios"
    )
    rut_usuario = models.CharField(max_length=12, unique=True)
    nombre_completo = models.CharField(max_length=120)
    correo_electronico = models.EmailField(max_length=100, unique=True)
    password_hash = models.CharField(max_length=255)
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "USUARIO"
        verbose_name = "Usuario del Sistema"
        verbose_name_plural = "04. Usuarios del Sistema"

    def __str__(self):
        return f"{self.nombre_completo} ({self.id_rol.nombre_rol})"


# 5. TIPO_UNIDAD
class TipoUnidad(models.Model):
    id_tipo_unidad = models.AutoField(primary_key=True)
    codigo_tipo = models.CharField(max_length=15, unique=True)
    nombre_tipo = models.CharField(max_length=60)
    incluye_cocina = models.BooleanField(default=False)
    descripcion = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        db_table = "TIPO_UNIDAD"
        verbose_name = "Tipo de Unidad"
        verbose_name_plural = "05. Tipos de Unidad"

    def __str__(self):
        return self.nombre_tipo


# 6. UNIDAD_HOSPEDAJE
class UnidadHospedaje(models.Model):
    ESTADOS_UNIDAD = [
        ("DISPONIBLE", "Disponible"),
        ("OCUPADA", "Ocupada"),
        ("SUCIO", "Sucio (Pendiente Aseo)"),
        ("EN_LIMPIEZA", "En Limpieza"),
        ("MANTENIMIENTO", "En Mantenimiento"),
    ]
    id_unidad = models.AutoField(primary_key=True)
    id_sucursal = models.ForeignKey(
        Sucursal, on_delete=models.PROTECT, db_column="id_sucursal", related_name="unidades"
    )
    id_tipo_unidad = models.ForeignKey(
        TipoUnidad, on_delete=models.PROTECT, db_column="id_tipo_unidad", related_name="unidades"
    )
    codigo_numero = models.CharField(max_length=30)
    capacidad_max_pax = models.IntegerField(default=2)
    cantidad_camas = models.IntegerField(default=1)
    estado_unidad = models.CharField(max_length=20, choices=ESTADOS_UNIDAD, default="DISPONIBLE")
    observaciones = models.CharField(max_length=250, blank=True, null=True)

    class Meta:
        db_table = "UNIDAD_HOSPEDAJE"
        unique_together = (("id_sucursal", "codigo_numero"),)
        verbose_name = "Unidad de Hospedaje"
        verbose_name_plural = "06. Unidades de Hospedaje"

    def __str__(self):
        return f"{self.codigo_numero} ({self.id_sucursal.nombre_sucursal}) - {self.capacidad_max_pax} pax"


# 7. INVENTARIO_UNIDAD
class InventarioUnidad(models.Model):
    ESTADOS_ITEM = [
        ("OPERATIVO", "Operativo"),
        ("DANADO", "Dañado"),
        ("FALTANTE", "Faltante"),
    ]
    id_item_inventario = models.AutoField(primary_key=True)
    id_unidad = models.ForeignKey(
        UnidadHospedaje, on_delete=models.CASCADE, db_column="id_unidad", related_name="inventario"
    )
    nombre_item = models.CharField(max_length=80)
    categoria_item = models.CharField(max_length=40)
    cantidad_estandar = models.IntegerField(default=1)
    valor_reposicion = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    estado_item = models.CharField(max_length=20, choices=ESTADOS_ITEM, default="OPERATIVO")

    class Meta:
        db_table = "INVENTARIO_UNIDAD"
        verbose_name = "Ítem de Inventario"
        verbose_name_plural = "07. Inventario de Unidades"

    def __str__(self):
        return f"{self.nombre_item} ({self.id_unidad.codigo_numero})"


# 8. TEMPORADA_TARIFA
class TemporadaTarifa(models.Model):
    id_tarifa = models.AutoField(primary_key=True)
    id_zona = models.ForeignKey(
        ZonaGeografica, on_delete=models.CASCADE, db_column="id_zona", related_name="tarifas"
    )
    id_tipo_unidad = models.ForeignKey(
        TipoUnidad, on_delete=models.CASCADE, db_column="id_tipo_unidad", related_name="tarifas"
    )
    nombre_temporada = models.CharField(max_length=60)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    precio_noche_clp = models.DecimalField(max_digits=10, decimal_places=2)
    porcentaje_abono_min = models.DecimalField(max_digits=5, decimal_places=2, default=50.00)

    class Meta:
        db_table = "TEMPORADA_TARIFA"
        verbose_name = "Tarifa por Temporada"
        verbose_name_plural = "08. Tarifas y Temporadas"

    def __str__(self):
        return f"{self.nombre_temporada} - {self.id_zona.nombre_zona} ({self.id_tipo_unidad.nombre_tipo}): ${self.precio_noche_clp:,.0f}"


# 9. PASAJERO
class Pasajero(models.Model):
    TIPOS_DOC = [
        ("RUT", "RUT Chileno"),
        ("PASAPORTE", "Pasaporte"),
    ]
    id_pasajero = models.AutoField(primary_key=True)
    tipo_documento = models.CharField(max_length=15, choices=TIPOS_DOC, default="RUT")
    num_documento = models.CharField(max_length=20, unique=True)
    nombre_completo = models.CharField(max_length=120)
    telefono = models.CharField(max_length=20)
    correo_electronico = models.EmailField(max_length=100, blank=True, null=True)
    procedencia_ciudad = models.CharField(max_length=80)
    es_titular_frecuente = models.BooleanField(default=True)

    class Meta:
        db_table = "PASAJERO"
        verbose_name = "Pasajero"
        verbose_name_plural = "09. Pasajeros"

    def __str__(self):
        return f"{self.nombre_completo} ({self.num_documento})"


# 10. RESERVA
class Reserva(models.Model):
    ESTADOS_RESERVA = [
        ("PENDIENTE", "Pendiente de Abono"),
        ("CONFIRMADA", "Confirmada (Con Seña)"),
        ("CHECKIN_ACTIVO", "En Curso (Check-in Activo)"),
        ("FINALIZADA", "Finalizada (Check-out)"),
        ("ANULADA", "Anulada"),
    ]
    id_reserva = models.AutoField(primary_key=True)
    id_pasajero_titular = models.ForeignKey(
        Pasajero, on_delete=models.PROTECT, db_column="id_pasajero_titular", related_name="reservas_titular"
    )
    id_unidad = models.ForeignKey(
        UnidadHospedaje, on_delete=models.PROTECT, db_column="id_unidad", related_name="reservas"
    )
    id_usuario_crea = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, db_column="id_usuario_crea", related_name="reservas_creadas"
    )
    fecha_checkin = models.DateField()
    fecha_checkout = models.DateField()
    cantidad_pasajeros = models.IntegerField(default=1)
    monto_alojamiento = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    monto_abono_pagado = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    monto_consumos_multas = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    monto_total_final = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    estado_reserva = models.CharField(max_length=20, choices=ESTADOS_RESERVA, default="CONFIRMADA")
    acepta_condiciones = models.BooleanField(default=False)
    firma_digital_base64 = models.TextField(blank=True, null=True)
    llaves_entregadas = models.BooleanField(default=False)
    fecha_hora_checkin_real = models.DateTimeField(blank=True, null=True)
    fecha_hora_checkout_real = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "RESERVA"
        verbose_name = "Reserva"
        verbose_name_plural = "10. Reservas"

    @property
    def saldo_pendiente(self):
        return max(0, (self.monto_alojamiento + self.monto_consumos_multas) - self.monto_abono_pagado)

    @property
    def noches(self):
        return max(1, (self.fecha_checkout - self.fecha_checkin).days)

    def __str__(self):
        return f"Reserva #{self.id_reserva} - {self.id_pasajero_titular.nombre_completo}"


# 11. RESERVA_ACOMPANANTE
class ReservaAcompanante(models.Model):
    id_reserva = models.ForeignKey(
        Reserva, on_delete=models.CASCADE, db_column="id_reserva", related_name="acompanantes"
    )
    id_pasajero = models.ForeignKey(
        Pasajero, on_delete=models.CASCADE, db_column="id_pasajero", related_name="estadias_acompanante"
    )
    parentesco_relacion = models.CharField(max_length=40, default="ACOMPANANTE")

    class Meta:
        db_table = "RESERVA_ACOMPANANTE"
        unique_together = (("id_reserva", "id_pasajero"),)
        verbose_name = "Acompañante de Reserva"
        verbose_name_plural = "11. Acompañantes por Reserva"

    def __str__(self):
        return f"Reserva #{self.id_reserva_id} - {self.id_pasajero.nombre_completo}"


# 12. CAJA_DIARIA
class CajaDiaria(models.Model):
    ESTADOS_CAJA = [
        ("ABIERTA", "Abierta"),
        ("CERRADA", "Cerrada"),
    ]
    id_caja = models.AutoField(primary_key=True)
    id_sucursal = models.ForeignKey(
        Sucursal, on_delete=models.PROTECT, db_column="id_sucursal", related_name="cajas"
    )
    id_usuario_recep = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, db_column="id_usuario_recep", related_name="cajas_operadas"
    )
    fecha_apertura = models.DateTimeField(default=timezone.now)
    fecha_cierre = models.DateTimeField(blank=True, null=True)
    monto_inicial = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_efectivo = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_transferencias = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_tarjetas = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_egresos_gastos = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    estado_caja = models.CharField(max_length=15, choices=ESTADOS_CAJA, default="ABIERTA")
    observacion_cuadratura = models.CharField(max_length=250, blank=True, null=True)

    class Meta:
        db_table = "CAJA_DIARIA"
        verbose_name = "Caja Diaria"
        verbose_name_plural = "12. Cajas Diarias"

    @property
    def total_recaudado(self):
        return (self.total_efectivo + self.total_transferencias + self.total_tarjetas) - self.total_egresos_gastos

    def __str__(self):
        return f"Caja #{self.id_caja} - {self.id_sucursal.nombre_sucursal} ({self.estado_caja})"


# 13. PAGO_MOVIMIENTO
class PagoMovimiento(models.Model):
    TIPOS_MOV = [
        ("ABONO_RESERVA", "Abono / Seña (50%)"),
        ("SALDO_CHECKIN", "Pago Saldo Check-in"),
        ("CARGO_CHECKOUT", "Cobro Consumos / Daños Check-out"),
        ("GASTO_SUCURSAL", "Egreso / Gasto de Sucursal"),
    ]
    MEDIOS_PAGO = [
        ("EFECTIVO", "Efectivo"),
        ("TRANSFERENCIA", "Transferencia Bancaria"),
        ("TARJETA_POS", "Tarjeta Crédito / Débito (POS)"),
    ]
    id_pago = models.AutoField(primary_key=True)
    id_reserva = models.ForeignKey(
        Reserva, on_delete=models.SET_NULL, db_column="id_reserva", blank=True, null=True, related_name="pagos"
    )
    id_caja = models.ForeignKey(
        CajaDiaria, on_delete=models.PROTECT, db_column="id_caja", related_name="movimientos"
    )
    tipo_movimiento = models.CharField(max_length=25, choices=TIPOS_MOV)
    medio_pago = models.CharField(max_length=25, choices=MEDIOS_PAGO)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    num_comprobante_voucher = models.CharField(max_length=40)
    fecha_hora_pago = models.DateTimeField(default=timezone.now)
    estado_pago = models.CharField(max_length=15, default="VIGENTE")

    class Meta:
        db_table = "PAGO_MOVIMIENTO"
        verbose_name = "Movimiento de Pago / Caja"
        verbose_name_plural = "13. Movimientos de Pago"

    def __str__(self):
        return f"{self.tipo_movimiento} - ${self.monto:,.0f} ({self.medio_pago})"


# 14. INCIDENCIA_ASEO
class IncidenciaAseo(models.Model):
    TIPOS_INC = [
        ("DANO_INVENTARIO", "Daño de Inventario"),
        ("FALTANTE_MENAJE", "Faltante de Menaje"),
        ("FALLA_TECNICA", "Falla Técnica / Mantención"),
    ]
    ESTADOS_INC = [
        ("PENDIENTE", "Pendiente de Revisión"),
        ("EN_REPARACION", "En Reparación / Reposición"),
        ("RESUELTA", "Resuelta"),
    ]
    id_incidencia = models.AutoField(primary_key=True)
    id_unidad = models.ForeignKey(
        UnidadHospedaje, on_delete=models.CASCADE, db_column="id_unidad", related_name="incidencias"
    )
    id_item_inventario = models.ForeignKey(
        InventarioUnidad, on_delete=models.SET_NULL, db_column="id_item_inventario", blank=True, null=True
    )
    id_usuario_reporta = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, db_column="id_usuario_reporta", related_name="incidencias_reportadas"
    )
    id_reserva = models.ForeignKey(
        Reserva, on_delete=models.SET_NULL, db_column="id_reserva", blank=True, null=True
    )
    tipo_incidencia = models.CharField(max_length=25, choices=TIPOS_INC)
    descripcion_problema = models.CharField(max_length=300)
    monto_cargo_asociado = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fecha_reporte = models.DateTimeField(default=timezone.now)
    estado_incidencia = models.CharField(max_length=20, choices=ESTADOS_INC, default="PENDIENTE")

    class Meta:
        db_table = "INCIDENCIA_ASEO"
        verbose_name = "Incidencia de Aseo / Mantención"
        verbose_name_plural = "14. Incidencias de Aseo y Mantención"

    def __str__(self):
        return f"{self.tipo_incidencia} en {self.id_unidad.codigo_numero} ({self.estado_incidencia})"
