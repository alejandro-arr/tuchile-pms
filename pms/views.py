"""Vistas del Sistema de Gestión de Arriendos (PMS) — Turismo TUCHILE.

Integra:
- 3+ Patrones de Diseño GoF:
  * Creacional: `UnidadHospedajeFactory` (`CabanaUnidadFactory` vs `HabitacionHotelFactory`) en Mantenedores.
  * Estructural: `OperacionesPMSFacade` (Reservas sin overbooking < 2s, Check-in, Check-out, Caja) y
    `@requiere_rol_rbac` (Decorator GoF).
  * Comportamiento: `EstadoUnidadState` (State GoF) y `EstrategiaTarifa` (Strategy GoF).
- 4+ Controles Técnicos ISO/IEC 27001:2022:
  * Control A.8.5  (Gestión de Autenticación: 5 intentos, bloqueo 900s, sesión 1800s, token 28800s).
  * Control A.8.2  (Control de Accesos RBAC con caché de 300s).
  * Control A.8.11 (Enmascaramiento PII de RUT/Pasaporte y Email en vistas y reportes Excel).
  * Control A.8.15 (Registro de Eventos de Auditoría sanitizado <= 4096 bytes sin PII).
  * Control A.8.24 (Hashing Bcrypt rounds=12 y longitud mínima 12 caracteres).
  * Control A.8.12 (Mensajes de error genéricos <= 100 caracteres).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import time

from django.contrib import messages
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

from pms.domain.factories import seleccionar_factory_unidad
from pms.domain.states import TransicionEstadoInvalidaError, obtener_estado_unidad
from pms.models import (
    CajaDiaria,
    IncidenciaAseo,
    InventarioUnidad,
    PagoMovimiento,
    Reserva,
    Rol,
    Sucursal,
    TemporadaTarifa,
    TipoUnidad,
    UnidadHospedaje,
    Usuario,
    ZonaGeografica,
)
from pms.security.constants import (
    LIMITE_INACTIVIDAD_SESION_SEGUNDOS,
    MAX_INTENTOS_LOGIN_FALLIDOS,
    MIN_LONGITUD_PASSWORD,
)
from pms.security.controls import (
    emitir_token_sesion_firmado,
    enmascarar_rut_pasaporte,
    esta_cuenta_bloqueada,
    formatear_error_seguro,
    generar_hash_bcrypt_normativo,
    limpiar_intentos_login,
    registrar_evento_auditoria,
    registrar_intento_fallido_login,
    requiere_rol_rbac,
    verificar_hash_bcrypt,
)
from pms.services.facades import OperacionesPMSFacade, OverbookingError

pms_facade = OperacionesPMSFacade()

# Aliases de decoradores RBAC (Patrón Decorator GoF + Control ISO A.8.2)
requiere_login = requiere_rol_rbac("SUPERADMIN", "ADMIN_SEDE", "RECEPCION", "ASEO_MANT")
solo_recepcion_o_admin = requiere_rol_rbac(
    "SUPERADMIN",
    "ADMIN_SEDE",
    "RECEPCION",
    medir_sla_disponibilidad=True,
)
solo_superadmin = requiere_rol_rbac("SUPERADMIN")


def login_view(request: HttpRequest) -> HttpResponse:
    """Autentica usuarios aplicando Control ISO A.8.5 (5 intentos / 900s), A.8.12 (<=100 chars) y A.8.15."""
    if request.session.get("usuario_id"):
        if request.session.get("rol_activo") == "ASEO_MANT":
            return redirect("aseo_movil")
        return redirect("dashboard_gantt")

    if request.method == "POST":
        identificador = request.POST.get("identificador", "").strip()
        password = request.POST.get("password", "").strip()

        # 1. Control ISO A.8.5: Verificar si la cuenta está bloqueada (900 segundos)
        bloqueada, seg_restantes = esta_cuenta_bloqueada(identificador)
        if bloqueada:
            min_rest = max(1, seg_restantes // 60)
            messages.error(
                request,
                formatear_error_seguro(
                    f"Cuenta bloqueada por seguridad (ISO A.8.5). Reintente en {min_rest} min ({seg_restantes}s)."
                ),
            )
            return render(request, "pms/login.html")

        usuario = (
            Usuario.objects.select_related("id_rol", "id_sucursal")
            .filter(Q(correo_electronico__iexact=identificador) | Q(rut_usuario__iexact=identificador))
            .first()
        )

        # 2. Control ISO A.8.12 y A.8.24: Mensaje genérico sin revelar existencia de usuario y verificación hash
        credenciales_validas = bool(
            usuario and usuario.activo and verificar_hash_bcrypt(password, usuario.password_hash)
        )
        if not credenciales_validas:
            intentos, quedo_bloqueada = registrar_intento_fallido_login(identificador)
            if quedo_bloqueada:
                messages.error(
                    request,
                    formatear_error_seguro(
                        f"Cuenta bloqueada por 15 min tras {MAX_INTENTOS_LOGIN_FALLIDOS} intentos fallidos (ISO A.8.5)."
                    ),
                )
            else:
                messages.error(
                    request,
                    formatear_error_seguro(
                        f"Credenciales inválidas ({intentos}/{MAX_INTENTOS_LOGIN_FALLIDOS} intentos - ISO A.8.5)."
                    ),
                )
            return render(request, "pms/login.html")

        # 3. Login exitoso: limpiar contador A.8.5, fijar sesión 1800s y emitir token firmado (28800s)
        limpiar_intentos_login(identificador)
        request.session["usuario_id"] = usuario.id_usuario
        request.session["usuario_nombre"] = usuario.nombre_completo
        request.session["usuario_correo"] = usuario.correo_electronico
        request.session["rol_activo"] = usuario.id_rol.codigo_rol
        request.session["rol_nombre"] = usuario.id_rol.nombre_rol
        request.session["sucursal_nombre"] = (
            usuario.id_sucursal.nombre_sucursal if usuario.id_sucursal else "Casa Matriz · Todas las Sedes"
        )
        request.session["ultima_actividad_ts"] = int(time.time())
        request.session["token_jwt_a85"] = emitir_token_sesion_firmado(
            usuario.id_usuario, usuario.id_rol.codigo_rol
        )
        request.session.set_expiry(LIMITE_INACTIVIDAD_SESION_SEGUNDOS)

        registrar_evento_auditoria(
            accion="LOGIN_EXITOSO_A85",
            usuario_identificador=usuario.correo_electronico,
            rol=usuario.id_rol.codigo_rol,
            detalle=f"Sesión iniciada (timeout={LIMITE_INACTIVIDAD_SESION_SEGUNDOS}s).",
        )

        if usuario.id_rol.codigo_rol == "ASEO_MANT":
            return redirect("aseo_movil")
        return redirect("dashboard_gantt")

    return render(request, "pms/login.html")


def logout_view(request: HttpRequest) -> HttpResponse:
    """Cierra la sesión activa registrando el evento en la bitácora ISO A.8.15."""
    correo = request.session.get("usuario_correo", "ANON")
    rol = request.session.get("rol_activo", "N/A")
    registrar_evento_auditoria(
        accion="LOGOUT_USUARIO",
        usuario_identificador=correo,
        rol=rol,
        detalle="Cierre de sesión manual.",
    )
    request.session.flush()
    return redirect("login")


@solo_recepcion_o_admin
def dashboard_gantt(request: HttpRequest) -> HttpResponse:
    """Calendario Gantt de ocupación en tiempo real (< 2s) con filtro por Macrozona y Tipo de Unidad."""
    inicio_t = time.perf_counter()
    zona_id = request.GET.get("zona", "")
    tipo_id = request.GET.get("tipo", "")
    fecha_str = request.GET.get("fecha", "")

    try:
        fecha_base = date.fromisoformat(fecha_str) if fecha_str else date.today()
    except ValueError:
        fecha_base = date.today()

    dias = [fecha_base + timedelta(days=i) for i in range(7)]

    unidades_qs = UnidadHospedaje.objects.select_related(
        "id_sucursal", "id_sucursal__id_zona", "id_tipo_unidad"
    ).order_by("id_unidad")
    if zona_id:
        unidades_qs = unidades_qs.filter(id_sucursal__id_zona_id=zona_id)
    if tipo_id:
        unidades_qs = unidades_qs.filter(id_tipo_unidad_id=tipo_id)

    reservas_activas = Reserva.objects.exclude(estado_reserva="ANULADA").select_related("id_pasajero_titular")

    matriz = []
    for u in unidades_qs:
        celdas = []
        for d in dias:
            res_dia = None
            for r in reservas_activas:
                if r.id_unidad_id == u.id_unidad and r.fecha_checkin <= d < r.fecha_checkout:
                    res_dia = r
                    break
            celdas.append({"fecha": d, "reserva": res_dia})
        matriz.append({"unidad": u, "celdas": celdas})

    todas_unidades = UnidadHospedaje.objects.all()
    latencia_ms = round((time.perf_counter() - inicio_t) * 1000, 2)
    context = {
        "nav_active": "gantt",
        "zonas": ZonaGeografica.objects.all(),
        "tipos": TipoUnidad.objects.all(),
        "zona_sel": str(zona_id),
        "tipo_sel": str(tipo_id),
        "fecha_base": fecha_base.isoformat(),
        "dias": dias,
        "matriz": matriz,
        "latencia_ms": latencia_ms,
        "kpi_total": todas_unidades.count(),
        "kpi_disponibles": todas_unidades.filter(estado_unidad="DISPONIBLE").count(),
        "kpi_ocupadas": todas_unidades.filter(estado_unidad="OCUPADA").count(),
        "kpi_aseo": todas_unidades.filter(
            estado_unidad__in=["SUCIO", "EN_LIMPIEZA", "MANTENIMIENTO"]
        ).count(),
    }
    return render(request, "pms/dashboard.html", context)


@solo_recepcion_o_admin
def reservas_lista(request: HttpRequest) -> HttpResponse:
    """Listado de reservas con enmascaramiento de PII (Control ISO A.8.11)."""
    estado_filtro = request.GET.get("estado", "")
    q = request.GET.get("q", "").strip()

    reservas_qs = Reserva.objects.select_related(
        "id_pasajero_titular", "id_unidad", "id_unidad__id_sucursal"
    ).order_by("-id_reserva")

    if estado_filtro:
        reservas_qs = reservas_qs.filter(estado_reserva=estado_filtro)
    if q:
        reservas_qs = reservas_qs.filter(
            Q(id_pasajero_titular__nombre_completo__icontains=q)
            | Q(id_pasajero_titular__num_documento__icontains=q)
            | Q(id_unidad__codigo_numero__icontains=q)
        )

    context = {
        "nav_active": "reservas",
        "reservas": reservas_qs,
        "estado_sel": estado_filtro,
        "q": q,
    }
    return render(request, "pms/reservas_lista.html", context)


@solo_recepcion_o_admin
def crear_reserva(request: HttpRequest) -> HttpResponse:
    """Creación de reserva delegando en `OperacionesPMSFacade` (Facade) y `EstrategiaTarifa` (Strategy)."""
    if request.method == "POST":
        rut = request.POST.get("num_documento", "").strip()
        nombre = request.POST.get("nombre_completo", "").strip()
        telefono = request.POST.get("telefono", "").strip()
        correo = request.POST.get("correo", "").strip()
        procedencia = request.POST.get("procedencia", "Santiago").strip()
        unidad_id = request.POST.get("id_unidad")
        f_in_str = request.POST.get("fecha_checkin")
        f_out_str = request.POST.get("fecha_checkout")
        cant_pax = int(request.POST.get("cantidad_pasajeros", 2) or 2)
        abono = Decimal(request.POST.get("monto_abono", "0") or "0")
        medio_pago = request.POST.get("medio_pago", "TRANSFERENCIA")

        if not (rut and nombre and unidad_id and f_in_str and f_out_str):
            messages.error(request, formatear_error_seguro("Por favor complete todos los campos obligatorios."))
            return redirect("crear_reserva")

        unidad = get_object_or_404(
            UnidadHospedaje.objects.select_related("id_sucursal__id_zona", "id_tipo_unidad"),
            pk=unidad_id,
        )
        usuario_op = (
            Usuario.objects.select_related("id_rol").filter(pk=request.session.get("usuario_id")).first()
            or Usuario.objects.select_related("id_rol").first()
        )

        try:
            nueva_res, cotizacion, latencia = pms_facade.registrar_reserva_segura(
                rut_pasajero=rut,
                nombre_pasajero=nombre,
                telefono=telefono,
                correo=correo,
                procedencia=procedencia,
                unidad=unidad,
                fecha_checkin=date.fromisoformat(f_in_str),
                fecha_checkout=date.fromisoformat(f_out_str),
                cantidad_pasajeros=cant_pax,
                monto_abono=abono,
                medio_pago=medio_pago,
                usuario_operador=usuario_op,
            )
            messages.success(
                request,
                f"Reserva #{nueva_res.id_reserva} creada (${cotizacion.monto_total_alojamiento:,.0f} · "
                f"{cotizacion.nombre_estrategia} · {latencia*1000:.1f} ms).",
            )
            return redirect("reservas_lista")
        except (ValueError, OverbookingError) as exc:
            messages.error(request, formatear_error_seguro(str(exc)))
            return redirect("crear_reserva")

    unidades_todas = UnidadHospedaje.objects.select_related("id_sucursal", "id_tipo_unidad").order_by(
        "id_sucursal__nombre_sucursal", "codigo_numero"
    )
    tarifas = TemporadaTarifa.objects.select_related("id_zona", "id_tipo_unidad").all()
    context = {
        "nav_active": "nueva_reserva",
        "unidades_todas": unidades_todas,
        "tarifas": tarifas,
        "fecha_hoy": date.today().isoformat(),
        "fecha_manana": (date.today() + timedelta(days=2)).isoformat(),
    }
    return render(request, "pms/reserva_nueva.html", context)


@solo_recepcion_o_admin
def anular_reserva(request: HttpRequest, reserva_id: int) -> HttpResponse:
    reserva = get_object_or_404(Reserva, pk=reserva_id)
    reserva.estado_reserva = "ANULADA"
    reserva.save()
    registrar_evento_auditoria(
        accion="RESERVA_ANULADA",
        usuario_identificador=request.session.get("usuario_correo", "RECEPCION"),
        rol=request.session.get("rol_activo", "RECEPCION"),
        detalle=f"Reserva #{reserva.id_reserva} anulada.",
    )
    messages.warning(request, f"La Reserva #{reserva.id_reserva} fue anulada y la unidad quedó disponible.")
    return redirect("reservas_lista")


@solo_recepcion_o_admin
def checkin_view(request: HttpRequest, reserva_id: int) -> HttpResponse:
    """Flujo de Check-in orquestado por `OperacionesPMSFacade` y validado con `EstadoUnidadState`."""
    reserva = get_object_or_404(
        Reserva.objects.select_related("id_pasajero_titular", "id_unidad", "id_unidad__id_sucursal"),
        pk=reserva_id,
    )

    if request.method == "POST":
        acepta = request.POST.get("acepta_condiciones") == "on"
        firma_b64 = request.POST.get("firma_digital_base64", "")
        medio_pago = request.POST.get("medio_pago", "TARJETA_POS")
        voucher = request.POST.get("num_voucher", f"CHK-{reserva.id_reserva:04d}")
        usuario_op = (
            Usuario.objects.select_related("id_rol").filter(pk=request.session.get("usuario_id")).first()
            or Usuario.objects.select_related("id_rol").first()
        )

        try:
            pms_facade.ejecutar_checkin(
                reserva=reserva,
                acepta_condiciones=acepta,
                firma_digital_base64=firma_b64,
                medio_pago=medio_pago,
                num_voucher=voucher,
                usuario_operador=usuario_op,
            )
            messages.success(
                request,
                f"Check-in completado para Reserva #{reserva.id_reserva}. "
                f"Unidad {reserva.id_unidad.codigo_numero} pasó a estado OCUPADA (State GoF).",
            )
            return redirect("reservas_lista")
        except (ValueError, TransicionEstadoInvalidaError) as exc:
            messages.error(request, formatear_error_seguro(str(exc)))
            return redirect("checkin_view", reserva_id=reserva.id_reserva)

    return render(request, "pms/checkin.html", {"nav_active": "reservas", "reserva": reserva})


@solo_recepcion_o_admin
def checkout_view(request: HttpRequest, reserva_id: int) -> HttpResponse:
    """Flujo de Check-out orquestado por `OperacionesPMSFacade` (inventario + cobro + paso a 'SUCIO')."""
    reserva = get_object_or_404(
        Reserva.objects.select_related("id_pasajero_titular", "id_unidad", "id_unidad__id_sucursal"),
        pk=reserva_id,
    )
    inventario = InventarioUnidad.objects.filter(id_unidad=reserva.id_unidad)

    if request.method == "POST":
        consumos_extra = Decimal(request.POST.get("monto_consumos_multas", "0") or "0")
        medio_pago = request.POST.get("medio_pago", "EFECTIVO")
        obs_dano = request.POST.get("observacion_dano", "").strip()
        usuario_op = (
            Usuario.objects.select_related("id_rol").filter(pk=request.session.get("usuario_id")).first()
            or Usuario.objects.select_related("id_rol").first()
        )

        pms_facade.ejecutar_checkout(
            reserva=reserva,
            consumos_multas_extra=consumos_extra,
            medio_pago=medio_pago,
            observacion_dano=obs_dano,
            usuario_operador=usuario_op,
        )
        messages.success(
            request,
            f"Check-out finalizado para Reserva #{reserva.id_reserva}. "
            f"{reserva.id_unidad.codigo_numero} pasó automáticamente a estado SUCIO (Facade + State GoF).",
        )
        return redirect("reservas_lista")

    return render(
        request,
        "pms/checkout.html",
        {"nav_active": "reservas", "reserva": reserva, "inventario": inventario},
    )


@requiere_login
def aseo_movil(request: HttpRequest) -> HttpResponse:
    """Panel móvil de limpieza gobernado por la máquina de estados `EstadoUnidadState` (Patrón State GoF)."""
    if request.method == "POST":
        accion = request.POST.get("accion")
        unidad_id = request.POST.get("id_unidad")
        unidad = get_object_or_404(UnidadHospedaje, pk=unidad_id)
        estado_gof = obtener_estado_unidad(unidad)
        correo_op = request.session.get("usuario_correo", "ASEO")
        rol_op = request.session.get("rol_activo", "ASEO_MANT")

        try:
            if accion == "iniciar_limpieza":
                nuevo_estado = estado_gof.iniciar_limpieza(unidad)
                registrar_evento_auditoria(
                    accion="STATE_INICIAR_LIMPIEZA",
                    usuario_identificador=correo_op,
                    rol=rol_op,
                    detalle=f"{unidad.codigo_numero} -> {nuevo_estado}",
                )
                messages.info(request, f"{unidad.codigo_numero} cambió a estado EN LIMPIEZA (State GoF).")
            elif accion == "marcar_disponible":
                nuevo_estado = estado_gof.habilitar_disponible(unidad)
                registrar_evento_auditoria(
                    accion="STATE_HABILITAR_DISPONIBLE",
                    usuario_identificador=correo_op,
                    rol=rol_op,
                    detalle=f"{unidad.codigo_numero} -> {nuevo_estado}",
                )
                messages.success(
                    request, f"{unidad.codigo_numero} habilitada como DISPONIBLE en tiempo real (State GoF)."
                )
            elif accion == "reportar_dano":
                desc = request.POST.get("descripcion_problema", "").strip()
                tipo_inc = request.POST.get("tipo_incidencia", "DANO_INVENTARIO")
                if desc:
                    usuario_op = (
                        Usuario.objects.filter(pk=request.session.get("usuario_id")).first()
                        or Usuario.objects.first()
                    )
                    IncidenciaAseo.objects.create(
                        id_unidad=unidad,
                        id_usuario_reporta=usuario_op,
                        tipo_incidencia=tipo_inc,
                        descripcion_problema=desc,
                        estado_incidencia="PENDIENTE",
                    )
                    if tipo_inc == "FALLA_TECNICA":
                        estado_gof.enviar_a_mantenimiento(unidad)
                    registrar_evento_auditoria(
                        accion="INCIDENCIA_ASEO_REPORTADA",
                        usuario_identificador=correo_op,
                        rol=rol_op,
                        detalle=f"{unidad.codigo_numero} | Tipo={tipo_inc}",
                    )
                    messages.warning(request, f"Incidencia registrada para {unidad.codigo_numero}.")
        except TransicionEstadoInvalidaError as exc:
            messages.error(request, formatear_error_seguro(str(exc)))
        return redirect("aseo_movil")

    unidades = UnidadHospedaje.objects.select_related("id_sucursal", "id_tipo_unidad").order_by("id_unidad")
    incidencias = IncidenciaAseo.objects.select_related("id_unidad", "id_usuario_reporta").order_by(
        "-fecha_reporte"
    )[:8]
    return render(
        request,
        "pms/aseo.html",
        {"nav_active": "aseo", "unidades": unidades, "incidencias": incidencias},
    )


@solo_recepcion_o_admin
def caja_reportes(request: HttpRequest) -> HttpResponse:
    """Gestión de Caja Diaria: registro de egresos, cierre/arqueo de turno y reapertura."""
    caja = CajaDiaria.objects.filter(estado_caja="ABIERTA").first() or CajaDiaria.objects.last()
    movimientos = PagoMovimiento.objects.select_related("id_reserva", "id_caja").order_by("-fecha_hora_pago")
    usuario_op = (
        Usuario.objects.select_related("id_rol", "id_sucursal")
        .filter(pk=request.session.get("usuario_id"))
        .first()
        or Usuario.objects.select_related("id_rol", "id_sucursal").first()
    )

    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "registrar_gasto" and caja and caja.estado_caja == "ABIERTA":
            monto_gasto = Decimal(request.POST.get("monto_gasto", "0") or "0")
            motivo = request.POST.get("motivo_gasto", "Gasto operativo de sede")
            if monto_gasto > 0:
                PagoMovimiento.objects.create(
                    id_caja=caja,
                    tipo_movimiento="GASTO_SUCURSAL",
                    medio_pago="EFECTIVO",
                    monto=monto_gasto,
                    num_comprobante_voucher=motivo[:38],
                )
                caja.total_egresos_gastos += monto_gasto
                caja.save()
                registrar_evento_auditoria(
                    accion="EGRESO_CAJA_REGISTRADO",
                    usuario_identificador=usuario_op.correo_electronico,
                    rol=usuario_op.id_rol.codigo_rol,
                    detalle=f"Egreso ${monto_gasto:,.0f} en Caja #{caja.id_caja}.",
                )
                messages.info(request, f"Egreso de sucursal por ${monto_gasto:,.0f} registrado en Caja Diaria.")
        elif accion == "cerrar_caja" and caja and caja.estado_caja == "ABIERTA":
            obs = request.POST.get("observacion_cuadratura", "Arqueo de turno conforme.")
            pms_facade.cerrar_arqueo_caja(caja, obs, usuario_op)
            messages.success(
                request,
                f"Arqueo y cierre de Caja #{caja.id_caja} completado por ${caja.total_recaudado:,.0f}.",
            )
        elif accion == "abrir_caja":
            monto_ini = Decimal(request.POST.get("monto_inicial", "50000") or "50000")
            sucursal = usuario_op.id_sucursal or Sucursal.objects.first()
            nueva_caja = CajaDiaria.objects.create(
                id_sucursal=sucursal,
                id_usuario_recep=usuario_op,
                monto_inicial=monto_ini,
                estado_caja="ABIERTA",
            )
            registrar_evento_auditoria(
                accion="CAJA_DIARIA_ABIERTA",
                usuario_identificador=usuario_op.correo_electronico,
                rol=usuario_op.id_rol.codigo_rol,
                detalle=f"Caja #{nueva_caja.id_caja} abierta con fondo inicial ${monto_ini:,.0f}.",
            )
            messages.success(request, f"Nueva Caja Diaria #{nueva_caja.id_caja} abierta para el turno actual.")
        return redirect("caja_reportes")

    return render(
        request,
        "pms/caja_reportes.html",
        {"nav_active": "finanzas", "caja": caja, "movimientos": movimientos},
    )


@solo_recepcion_o_admin
def exportar_excel(request: HttpRequest) -> HttpResponse:
    """Exporta el resumen operativo y financiero en Excel (.xlsx) con RUT enmascarado (ISO A.8.11)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Reporte Financiero TUCHILE"

    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")

    headers = [
        "ID Pago",
        "Fecha / Hora",
        "Sucursal",
        "Reserva #",
        "Doc. Pasajero (ISO A.8.11)",
        "Tipo Movimiento",
        "Medio de Pago",
        "N° Voucher / Doc",
        "Monto (CLP)",
    ]
    ws.append(headers)
    for col_num in range(1, len(headers) + 1):
        c = ws.cell(row=1, column=col_num)
        c.font = hdr_font
        c.fill = hdr_fill
        c.alignment = Alignment(horizontal="center")

    movimientos_qs = PagoMovimiento.objects.select_related(
        "id_reserva__id_pasajero_titular", "id_caja__id_sucursal"
    ).order_by("-fecha_hora_pago")

    for m in movimientos_qs:
        doc_masked = (
            enmascarar_rut_pasaporte(m.id_reserva.id_pasajero_titular.num_documento)
            if m.id_reserva and m.id_reserva.id_pasajero_titular
            else "N/A"
        )
        ws.append(
            [
                m.id_pago,
                m.fecha_hora_pago.strftime("%d-%m-%Y %H:%M"),
                m.id_caja.id_sucursal.nombre_sucursal,
                f"#{m.id_reserva_id}" if m.id_reserva_id else "Gasto Sede",
                doc_masked,
                m.get_tipo_movimiento_display(),
                m.get_medio_pago_display(),
                m.num_comprobante_voucher,
                float(m.monto),
            ]
        )

    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 22

    registrar_evento_auditoria(
        accion="REPORTE_EXCEL_EXPORTADO",
        usuario_identificador=request.session.get("usuario_correo", "RECEPCION"),
        rol=request.session.get("rol_activo", "RECEPCION"),
        detalle=f"Exportación Excel con PII enmascarada ({movimientos_qs.count()} registros).",
    )

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="Reporte_Financiero_TUCHILE.xlsx"'
    wb.save(response)
    return response


@solo_recepcion_o_admin
def comprobante_pago(request: HttpRequest, reserva_id: int) -> HttpResponse:
    reserva = get_object_or_404(
        Reserva.objects.select_related("id_pasajero_titular", "id_unidad", "id_unidad__id_sucursal"),
        pk=reserva_id,
    )
    pagos = PagoMovimiento.objects.filter(id_reserva=reserva)
    return render(request, "pms/comprobante_print.html", {"reserva": reserva, "pagos": pagos})


@requiere_login
def mantenedores_panel(request: HttpRequest) -> HttpResponse:
    """Mantenedores Maestros restringidos por RBAC (ISO A.8.2) e integrados con `UnidadHospedajeFactory`."""
    if request.session.get("rol_activo") != "SUPERADMIN":
        messages.error(
            request,
            formatear_error_seguro(
                "Acceso restringido (ISO A.8.2): Solo Superadministrador opera Mantenedores."
            ),
        )
        return redirect("dashboard_gantt")

    tab = request.GET.get("tab", "unidades")
    correo_admin = request.session.get("usuario_correo", "SUPERADMIN")

    if request.method == "POST":
        accion = request.POST.get("accion", "")

        # 1. CRUD Unidades de Hospedaje usando Patrón Creacional Factory Method
        if accion == "crear_unidad":
            sucursal_id = request.POST.get("id_sucursal")
            tipo_id = request.POST.get("id_tipo_unidad")
            codigo = request.POST.get("codigo_numero", "").strip()
            cap = int(request.POST.get("capacidad_max_pax", 2) or 2)
            camas = int(request.POST.get("cantidad_camas", 1) or 1)
            if sucursal_id and tipo_id and codigo:
                sucursal = get_object_or_404(Sucursal, pk=sucursal_id)
                tipo_unidad = get_object_or_404(TipoUnidad, pk=tipo_id)
                factory = seleccionar_factory_unidad(tipo_unidad)
                unidad_creada = factory.crear_unidad_con_inventario(
                    sucursal=sucursal,
                    tipo_unidad=tipo_unidad,
                    codigo_numero=codigo,
                    capacidad_max_pax=cap,
                    cantidad_camas=camas,
                )
                registrar_evento_auditoria(
                    accion="UNIDAD_CREADA_FACTORY_METHOD",
                    usuario_identificador=correo_admin,
                    rol="SUPERADMIN",
                    detalle=(
                        f"Unidad '{unidad_creada.codigo_numero}' instanciada con {factory.__class__.__name__} "
                        f"({unidad_creada.inventario.count()} ítems de inventario creados)."
                    ),
                )
                messages.success(
                    request,
                    f"Unidad '{codigo}' creada vía {factory.__class__.__name__} con su kit de inventario estándar.",
                )
            return redirect("/mantenedores/?tab=unidades")

        elif accion == "eliminar_unidad":
            u_id = request.POST.get("id_unidad")
            try:
                u = get_object_or_404(UnidadHospedaje, pk=u_id)
                nombre_u = u.codigo_numero
                u.delete()
                messages.warning(request, f"Unidad '{nombre_u}' eliminada.")
            except Exception:
                messages.error(
                    request,
                    formatear_error_seguro(
                        "No se puede eliminar una unidad con historial de reservas."
                    ),
                )
            return redirect("/mantenedores/?tab=unidades")

        # 2. CRUD Tarifas por Temporada
        elif accion == "crear_tarifa":
            zona_id = request.POST.get("id_zona")
            tipo_id = request.POST.get("id_tipo_unidad")
            nombre_temp = request.POST.get("nombre_temporada", "").strip()
            f_ini = request.POST.get("fecha_inicio")
            f_fin = request.POST.get("fecha_fin")
            precio = Decimal(request.POST.get("precio_noche_clp", "50000") or "50000")
            abono_pct = Decimal(request.POST.get("porcentaje_abono_min", "50") or "50")
            if zona_id and tipo_id and nombre_temp and f_ini and f_fin:
                TemporadaTarifa.objects.create(
                    id_zona_id=zona_id,
                    id_tipo_unidad_id=tipo_id,
                    nombre_temporada=nombre_temp,
                    fecha_inicio=date.fromisoformat(f_ini),
                    fecha_fin=date.fromisoformat(f_fin),
                    precio_noche_clp=precio,
                    porcentaje_abono_min=abono_pct,
                )
                messages.success(request, f"Tarifa '{nombre_temp}' (${precio:,.0f}/noche) registrada.")
            return redirect("/mantenedores/?tab=tarifas")

        elif accion == "actualizar_precio_tarifa":
            t_id = request.POST.get("id_tarifa")
            nuevo_precio = Decimal(request.POST.get("precio_noche_clp", "0") or "0")
            tarifa = get_object_or_404(TemporadaTarifa, pk=t_id)
            if nuevo_precio > 0:
                tarifa.precio_noche_clp = nuevo_precio
                tarifa.save()
                messages.success(
                    request, f"Precio actualizado a ${nuevo_precio:,.0f} para {tarifa.nombre_temporada}."
                )
            return redirect("/mantenedores/?tab=tarifas")

        # 3. CRUD Inventario Crítico
        elif accion == "crear_inventario":
            u_id = request.POST.get("id_unidad")
            nombre_item = request.POST.get("nombre_item", "").strip()
            categoria = request.POST.get("categoria_item", "Equipamiento").strip()
            cant = int(request.POST.get("cantidad_estandar", 1) or 1)
            valor = Decimal(request.POST.get("valor_reposicion", "0") or "0")
            if u_id and nombre_item:
                InventarioUnidad.objects.create(
                    id_unidad_id=u_id,
                    nombre_item=nombre_item,
                    categoria_item=categoria,
                    cantidad_estandar=cant,
                    valor_reposicion=valor,
                    estado_item="OPERATIVO",
                )
                messages.success(request, f"Ítem '{nombre_item}' agregado al inventario.")
            return redirect("/mantenedores/?tab=inventario")

        # 4. CRUD Sucursales
        elif accion == "crear_sucursal":
            zona_id = request.POST.get("id_zona")
            nombre_suc = request.POST.get("nombre_sucursal", "").strip()
            comuna = request.POST.get("comuna_ciudad", "").strip()
            direccion = request.POST.get("direccion", "").strip()
            telefono = request.POST.get("telefono_sede", "").strip()
            if zona_id and nombre_suc and comuna:
                Sucursal.objects.create(
                    id_zona_id=zona_id,
                    nombre_sucursal=nombre_suc,
                    comuna_ciudad=comuna,
                    direccion=direccion or "Dirección comercial S/N",
                    telefono_sede=telefono or "+56 9 0000 0000",
                    estado_sucursal="ACTIVA",
                )
                messages.success(request, f"Sucursal '{nombre_suc}' registrada exitosamente.")
            return redirect("/mantenedores/?tab=sucursales")

        # 5. CRUD Usuarios y Roles con Hashing Bcrypt rounds=12 y largo mín. 12 (ISO A.8.24)
        elif accion == "crear_usuario":
            rut = request.POST.get("rut_usuario", "").strip()
            nombre = request.POST.get("nombre_completo", "").strip()
            correo = request.POST.get("correo_electronico", "").strip()
            rol_id = request.POST.get("id_rol")
            suc_id = request.POST.get("id_sucursal") or None
            password = request.POST.get("password", "").strip()
            if rut and nombre and correo and rol_id:
                if len(password) < MIN_LONGITUD_PASSWORD:
                    messages.error(
                        request,
                        formatear_error_seguro(
                            f"La contraseña debe tener al menos {MIN_LONGITUD_PASSWORD} caracteres (ISO A.8.24)."
                        ),
                    )
                    return redirect("/mantenedores/?tab=usuarios")
                if Usuario.objects.filter(Q(rut_usuario=rut) | Q(correo_electronico=correo)).exists():
                    messages.error(
                        request,
                        formatear_error_seguro("Ya existe un usuario con ese RUT o correo."),
                    )
                else:
                    Usuario.objects.create(
                        rut_usuario=rut,
                        nombre_completo=nombre,
                        correo_electronico=correo,
                        id_rol_id=rol_id,
                        id_sucursal_id=suc_id,
                        password_hash=generar_hash_bcrypt_normativo(password),
                        activo=True,
                    )
                    registrar_evento_auditoria(
                        accion="USUARIO_CREADO_BCRYPT_A824",
                        usuario_identificador=correo_admin,
                        rol="SUPERADMIN",
                        detalle=f"Usuario creado con Bcrypt rounds=12 (RUT={enmascarar_rut_pasaporte(rut)}).",
                    )
                    messages.success(request, f"Cuenta creada con Bcrypt (rounds=12) para {nombre}.")
            return redirect("/mantenedores/?tab=usuarios")

        elif accion == "toggle_usuario":
            usr_id = request.POST.get("id_usuario")
            usr = get_object_or_404(Usuario, pk=usr_id)
            usr.activo = not usr.activo
            usr.save()
            estado_txt = "activada" if usr.activo else "desactivada"
            messages.info(request, f"Cuenta de {usr.nombre_completo} {estado_txt}.")
            return redirect("/mantenedores/?tab=usuarios")

    context = {
        "nav_active": "mantenedores",
        "tab": tab,
        "zonas": ZonaGeografica.objects.all(),
        "sucursales": Sucursal.objects.select_related("id_zona").order_by("id_sucursal"),
        "tipos_unidad": TipoUnidad.objects.all(),
        "unidades": UnidadHospedaje.objects.select_related("id_sucursal", "id_tipo_unidad").order_by(
            "id_sucursal__nombre_sucursal", "codigo_numero"
        ),
        "tarifas": TemporadaTarifa.objects.select_related("id_zona", "id_tipo_unidad").order_by(
            "id_zona__nombre_zona"
        ),
        "inventario": InventarioUnidad.objects.select_related(
            "id_unidad", "id_unidad__id_sucursal"
        ).order_by("id_unidad__codigo_numero", "nombre_item"),
        "usuarios": Usuario.objects.select_related("id_rol", "id_sucursal").order_by("id_usuario"),
        "roles": Rol.objects.all(),
    }
    return render(request, "pms/mantenedores.html", context)
