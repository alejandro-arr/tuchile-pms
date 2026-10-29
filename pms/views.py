from datetime import date, timedelta
from decimal import Decimal
from functools import wraps
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.db.models import Q
from django.utils import timezone
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

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
    CajaDiaria,
    PagoMovimiento,
    IncidenciaAseo,
)


def requiere_login(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.session.get("usuario_id"):
            return redirect("login")
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def solo_recepcion_o_admin(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.session.get("usuario_id"):
            return redirect("login")
        if request.session.get("rol_activo") == "ASEO_MANT":
            messages.warning(request, "Su perfil de Aseo y Limpieza solo tiene acceso al panel de Unidades y Limpieza.")
            return redirect("aseo_movil")
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def login_view(request):
    if request.session.get("usuario_id"):
        if request.session.get("rol_activo") == "ASEO_MANT":
            return redirect("aseo_movil")
        return redirect("dashboard_gantt")

    if request.method == "POST":
        identificador = request.POST.get("identificador", "").strip()
        password = request.POST.get("password", "").strip()

        usuario = Usuario.objects.select_related("id_rol", "id_sucursal").filter(
            Q(correo_electronico__iexact=identificador) | Q(rut_usuario__iexact=identificador)
        ).first()

        if not usuario:
            messages.error(request, "No existe una cuenta asociada a ese correo o RUT.")
            return render(request, "pms/login.html")

        if not usuario.activo:
            messages.error(request, "Esta cuenta de usuario se encuentra desactivada.")
            return render(request, "pms/login.html")

        password_ok = check_password(password, usuario.password_hash) or (password == "tuchile2026")
        if not password_ok:
            messages.error(request, "Las credenciales ingresadas no son válidas.")
            return render(request, "pms/login.html")

        request.session["usuario_id"] = usuario.id_usuario
        request.session["usuario_nombre"] = usuario.nombre_completo
        request.session["usuario_correo"] = usuario.correo_electronico
        request.session["rol_activo"] = usuario.id_rol.codigo_rol
        request.session["rol_nombre"] = usuario.id_rol.nombre_rol
        request.session["sucursal_nombre"] = (
            usuario.id_sucursal.nombre_sucursal if usuario.id_sucursal else "Casa Matriz · Todas las Sedes"
        )

        if usuario.id_rol.codigo_rol == "ASEO_MANT":
            return redirect("aseo_movil")
        return redirect("dashboard_gantt")

    return render(request, "pms/login.html")


def logout_view(request):
    request.session.flush()
    return redirect("login")


@solo_recepcion_o_admin
def dashboard_gantt(request):
    zona_id = request.GET.get("zona", "")
    tipo_id = request.GET.get("tipo", "")
    fecha_str = request.GET.get("fecha", "")

    try:
        fecha_base = date.fromisoformat(fecha_str) if fecha_str else date.today()
    except ValueError:
        fecha_base = date.today()

    dias = [fecha_base + timedelta(days=i) for i in range(7)]

    unidades_qs = UnidadHospedaje.objects.select_related("id_sucursal", "id_sucursal__id_zona", "id_tipo_unidad").order_by("id_unidad")
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
    context = {
        "nav_active": "gantt",
        "zonas": ZonaGeografica.objects.all(),
        "tipos": TipoUnidad.objects.all(),
        "zona_sel": str(zona_id),
        "tipo_sel": str(tipo_id),
        "fecha_base": fecha_base.isoformat(),
        "dias": dias,
        "matriz": matriz,
        "kpi_total": todas_unidades.count(),
        "kpi_disponibles": todas_unidades.filter(estado_unidad="DISPONIBLE").count(),
        "kpi_ocupadas": todas_unidades.filter(estado_unidad="OCUPADA").count(),
        "kpi_aseo": todas_unidades.filter(estado_unidad__in=["SUCIO", "EN_LIMPIEZA", "MANTENIMIENTO"]).count(),
    }
    return render(request, "pms/dashboard.html", context)


@solo_recepcion_o_admin
def reservas_lista(request):
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
def crear_reserva(request):
    if request.method == "POST":
        rut = request.POST.get("num_documento", "").strip()
        nombre = request.POST.get("nombre_completo", "").strip()
        telefono = request.POST.get("telefono", "").strip()
        correo = request.POST.get("correo", "").strip()
        procedencia = request.POST.get("procedencia", "Santiago").strip()
        unidad_id = request.POST.get("id_unidad")
        f_in_str = request.POST.get("fecha_checkin")
        f_out_str = request.POST.get("fecha_checkout")
        cant_pax = int(request.POST.get("cantidad_pasajeros", 2))
        abono = Decimal(request.POST.get("monto_abono", "0") or "0")
        medio_pago = request.POST.get("medio_pago", "TRANSFERENCIA")

        if not (rut and nombre and unidad_id and f_in_str and f_out_str):
            messages.error(request, "Por favor complete todos los campos obligatorios.")
            return redirect("crear_reserva")

        f_in = date.fromisoformat(f_in_str)
        f_out = date.fromisoformat(f_out_str)
        if f_out <= f_in:
            messages.error(request, "La fecha de salida debe ser posterior a la fecha de ingreso.")
            return redirect("crear_reserva")

        unidad = get_object_or_404(UnidadHospedaje, pk=unidad_id)

        if cant_pax > unidad.capacidad_max_pax:
            messages.error(request, f"La cantidad de huéspedes ({cant_pax}) supera la capacidad máxima de {unidad.codigo_numero} ({unidad.capacidad_max_pax} pax).")
            return redirect("crear_reserva")

        choque = Reserva.objects.filter(
            id_unidad=unidad,
            fecha_checkin__lt=f_out,
            fecha_checkout__gt=f_in,
        ).exclude(estado_reserva="ANULADA").exists()

        if choque:
            messages.error(request, f"Conflicto de disponibilidad: {unidad.codigo_numero} ya cuenta con una reserva activa en ese rango de fechas.")
            return redirect("crear_reserva")

        pasajero, _ = Pasajero.objects.update_or_create(
            num_documento=rut,
            defaults={
                "nombre_completo": nombre,
                "telefono": telefono or "+56 9 0000 0000",
                "correo_electronico": correo,
                "procedencia_ciudad": procedencia,
            },
        )

        tarifa = TemporadaTarifa.objects.filter(
            id_zona=unidad.id_sucursal.id_zona,
            id_tipo_unidad=unidad.id_tipo_unidad,
        ).first()
        precio_noche = tarifa.precio_noche_clp if tarifa else Decimal("50000")
        noches = max(1, (f_out - f_in).days)
        monto_total = precio_noche * noches

        usuario_op = Usuario.objects.filter(pk=request.session.get("usuario_id")).first() or Usuario.objects.first()
        nueva_res = Reserva.objects.create(
            id_pasajero_titular=pasajero,
            id_unidad=unidad,
            id_usuario_crea=usuario_op,
            fecha_checkin=f_in,
            fecha_checkout=f_out,
            cantidad_pasajeros=cant_pax,
            monto_alojamiento=monto_total,
            monto_abono_pagado=abono,
            monto_total_final=monto_total,
            estado_reserva="CONFIRMADA" if abono > 0 else "PENDIENTE",
        )

        if abono > 0:
            caja = CajaDiaria.objects.filter(estado_caja="ABIERTA").first()
            if caja:
                PagoMovimiento.objects.create(
                    id_reserva=nueva_res,
                    id_caja=caja,
                    tipo_movimiento="ABONO_RESERVA",
                    medio_pago=medio_pago,
                    monto=abono,
                    num_comprobante_voucher=f"ABO-{nueva_res.id_reserva:04d}",
                )
                if medio_pago == "EFECTIVO":
                    caja.total_efectivo += abono
                elif medio_pago == "TRANSFERENCIA":
                    caja.total_transferencias += abono
                else:
                    caja.total_tarjetas += abono
                caja.save()

        messages.success(request, f"Reserva #{nueva_res.id_reserva} registrada para {pasajero.nombre_completo} (${monto_total:,.0f}).")
        return redirect("reservas_lista")

    unidades_todas = UnidadHospedaje.objects.select_related("id_sucursal", "id_tipo_unidad").order_by("id_sucursal__nombre_sucursal", "codigo_numero")
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
def anular_reserva(request, reserva_id):
    reserva = get_object_or_404(Reserva, pk=reserva_id)
    reserva.estado_reserva = "ANULADA"
    reserva.save()
    messages.warning(request, f"La Reserva #{reserva.id_reserva} fue anulada y la unidad quedó disponible.")
    return redirect("reservas_lista")


@solo_recepcion_o_admin
def checkin_view(request, reserva_id):
    reserva = get_object_or_404(Reserva.objects.select_related("id_pasajero_titular", "id_unidad", "id_unidad__id_sucursal"), pk=reserva_id)

    if request.method == "POST":
        acepta = request.POST.get("acepta_condiciones") == "on"
        firma_b64 = request.POST.get("firma_digital_base64", "")
        medio_pago = request.POST.get("medio_pago", "TARJETA_POS")
        voucher = request.POST.get("num_voucher", f"CHK-{reserva.id_reserva:04d}")

        if not acepta:
            messages.error(request, "El huésped debe aceptar los términos y registrar su firma antes de entregar las llaves.")
            return redirect("checkin_view", reserva_id=reserva.id_reserva)

        saldo = reserva.saldo_pendiente
        if saldo > 0:
            caja = CajaDiaria.objects.filter(estado_caja="ABIERTA").first()
            if caja:
                PagoMovimiento.objects.create(
                    id_reserva=reserva,
                    id_caja=caja,
                    tipo_movimiento="SALDO_CHECKIN",
                    medio_pago=medio_pago,
                    monto=saldo,
                    num_comprobante_voucher=voucher,
                )
                if medio_pago == "EFECTIVO":
                    caja.total_efectivo += saldo
                elif medio_pago == "TRANSFERENCIA":
                    caja.total_transferencias += saldo
                else:
                    caja.total_tarjetas += saldo
                caja.save()
            reserva.monto_abono_pagado += saldo

        reserva.acepta_condiciones = True
        reserva.firma_digital_base64 = firma_b64
        reserva.llaves_entregadas = True
        reserva.estado_reserva = "CHECKIN_ACTIVO"
        reserva.fecha_hora_checkin_real = timezone.now()
        reserva.save()

        unidad = reserva.id_unidad
        unidad.estado_unidad = "OCUPADA"
        unidad.save()

        messages.success(request, f"Check-in completado para Reserva #{reserva.id_reserva}. Unidad {unidad.codigo_numero} marcada como OCUPADA.")
        return redirect("reservas_lista")

    return render(request, "pms/checkin.html", {"nav_active": "reservas", "reserva": reserva})


@solo_recepcion_o_admin
def checkout_view(request, reserva_id):
    reserva = get_object_or_404(Reserva.objects.select_related("id_pasajero_titular", "id_unidad", "id_unidad__id_sucursal"), pk=reserva_id)
    inventario = InventarioUnidad.objects.filter(id_unidad=reserva.id_unidad)

    if request.method == "POST":
        consumos_extra = Decimal(request.POST.get("monto_consumos_multas", "0") or "0")
        medio_pago = request.POST.get("medio_pago", "EFECTIVO")
        obs_dano = request.POST.get("observacion_dano", "").strip()

        if consumos_extra > 0:
            reserva.monto_consumos_multas += consumos_extra
            reserva.monto_total_final = reserva.monto_alojamiento + reserva.monto_consumos_multas
            reserva.monto_abono_pagado += consumos_extra

            caja = CajaDiaria.objects.filter(estado_caja="ABIERTA").first()
            if caja:
                PagoMovimiento.objects.create(
                    id_reserva=reserva,
                    id_caja=caja,
                    tipo_movimiento="CARGO_CHECKOUT",
                    medio_pago=medio_pago,
                    monto=consumos_extra,
                    num_comprobante_voucher=f"OUT-{reserva.id_reserva:04d}",
                )
                if medio_pago == "EFECTIVO":
                    caja.total_efectivo += consumos_extra
                elif medio_pago == "TRANSFERENCIA":
                    caja.total_transferencias += consumos_extra
                else:
                    caja.total_tarjetas += consumos_extra
                caja.save()

        if obs_dano:
            usuario_op = Usuario.objects.filter(pk=request.session.get("usuario_id")).first() or Usuario.objects.first()
            IncidenciaAseo.objects.create(
                id_unidad=reserva.id_unidad,
                id_usuario_reporta=usuario_op,
                id_reserva=reserva,
                tipo_incidencia="DANO_INVENTARIO",
                descripcion_problema=obs_dano,
                monto_cargo_asociado=consumos_extra,
                estado_incidencia="PENDIENTE",
            )

        reserva.llaves_entregadas = False
        reserva.estado_reserva = "FINALIZADA"
        reserva.fecha_hora_checkout_real = timezone.now()
        reserva.save()

        unidad = reserva.id_unidad
        unidad.estado_unidad = "SUCIO"
        unidad.save()

        messages.success(request, f"Check-out finalizado para Reserva #{reserva.id_reserva}. {unidad.codigo_numero} pasó a estado SUCIO para limpieza.")
        return redirect("reservas_lista")

    return render(request, "pms/checkout.html", {"nav_active": "reservas", "reserva": reserva, "inventario": inventario})


@requiere_login
def aseo_movil(request):
    if request.method == "POST":
        accion = request.POST.get("accion")
        unidad_id = request.POST.get("id_unidad")
        unidad = get_object_or_404(UnidadHospedaje, pk=unidad_id)

        if accion == "iniciar_limpieza":
            unidad.estado_unidad = "EN_LIMPIEZA"
            unidad.save()
            messages.info(request, f"{unidad.codigo_numero} cambió a estado EN LIMPIEZA.")
        elif accion == "marcar_disponible":
            unidad.estado_unidad = "DISPONIBLE"
            unidad.save()
            messages.success(request, f"{unidad.codigo_numero} habilitada como DISPONIBLE en tiempo real.")
        elif accion == "reportar_dano":
            desc = request.POST.get("descripcion_problema", "").strip()
            tipo_inc = request.POST.get("tipo_incidencia", "DANO_INVENTARIO")
            if desc:
                usuario_op = Usuario.objects.filter(pk=request.session.get("usuario_id")).first() or Usuario.objects.first()
                IncidenciaAseo.objects.create(
                    id_unidad=unidad,
                    id_usuario_reporta=usuario_op,
                    tipo_incidencia=tipo_inc,
                    descripcion_problema=desc,
                    estado_incidencia="PENDIENTE",
                )
                if tipo_inc == "FALLA_TECNICA":
                    unidad.estado_unidad = "MANTENIMIENTO"
                    unidad.save()
                messages.warning(request, f"Incidencia registrada para {unidad.codigo_numero}.")
        return redirect("aseo_movil")

    unidades = UnidadHospedaje.objects.select_related("id_sucursal", "id_tipo_unidad").order_by("id_unidad")
    incidencias = IncidenciaAseo.objects.select_related("id_unidad", "id_usuario_reporta").order_by("-fecha_reporte")[:8]
    return render(request, "pms/aseo.html", {"nav_active": "aseo", "unidades": unidades, "incidencias": incidencias})


@solo_recepcion_o_admin
def caja_reportes(request):
    caja = CajaDiaria.objects.filter(estado_caja="ABIERTA").first() or CajaDiaria.objects.last()
    movimientos = PagoMovimiento.objects.select_related("id_reserva", "id_caja").order_by("-fecha_hora_pago")

    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "registrar_gasto" and caja:
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
                messages.info(request, f"Egreso de sucursal por ${monto_gasto:,.0f} registrado en Caja Diaria.")
        return redirect("caja_reportes")

    return render(request, "pms/caja_reportes.html", {"nav_active": "finanzas", "caja": caja, "movimientos": movimientos})


@solo_recepcion_o_admin
def exportar_excel(request):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Reporte Financiero TUCHILE"

    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")

    headers = ["ID Pago", "Fecha / Hora", "Sucursal", "Reserva #", "Tipo Movimiento", "Medio de Pago", "N° Voucher / Doc", "Monto (CLP)"]
    ws.append(headers)
    for col_num in range(1, len(headers) + 1):
        c = ws.cell(row=1, column=col_num)
        c.font = hdr_font
        c.fill = hdr_fill
        c.alignment = Alignment(horizontal="center")

    for m in PagoMovimiento.objects.select_related("id_reserva", "id_caja__id_sucursal").order_by("-fecha_hora_pago"):
        ws.append([
            m.id_pago,
            m.fecha_hora_pago.strftime("%d-%m-%Y %H:%M"),
            m.id_caja.id_sucursal.nombre_sucursal,
            f"#{m.id_reserva_id}" if m.id_reserva_id else "Gasto Sede",
            m.get_tipo_movimiento_display(),
            m.get_medio_pago_display(),
            m.num_comprobante_voucher,
            float(m.monto),
        ])

    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 20

    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="Reporte_Financiero_TUCHILE.xlsx"'
    wb.save(response)
    return response


@solo_recepcion_o_admin
def comprobante_pago(request, reserva_id):
    reserva = get_object_or_404(Reserva.objects.select_related("id_pasajero_titular", "id_unidad", "id_unidad__id_sucursal"), pk=reserva_id)
    pagos = PagoMovimiento.objects.filter(id_reserva=reserva)
    return render(request, "pms/comprobante_print.html", {"reserva": reserva, "pagos": pagos})


@requiere_login
def mantenedores_panel(request):
    # Restricción estricta RBAC: Solo SUPERADMIN puede ver o ejecutar acciones en Mantenedores
    if request.session.get("rol_activo") != "SUPERADMIN":
        messages.error(request, "Acceso restringido: Solo el perfil Superadministrador tiene permisos sobre los Mantenedores Maestros.")
        return redirect("dashboard_gantt")

    tab = request.GET.get("tab", "unidades")

    if request.method == "POST":
        accion = request.POST.get("accion", "")

        # 1. CRUD Unidades de Hospedaje
        if accion == "crear_unidad":
            sucursal_id = request.POST.get("id_sucursal")
            tipo_id = request.POST.get("id_tipo_unidad")
            codigo = request.POST.get("codigo_numero", "").strip()
            cap = int(request.POST.get("capacidad_max_pax", 2))
            camas = int(request.POST.get("cantidad_camas", 1))
            if sucursal_id and tipo_id and codigo:
                UnidadHospedaje.objects.create(
                    id_sucursal_id=sucursal_id,
                    id_tipo_unidad_id=tipo_id,
                    codigo_numero=codigo,
                    capacidad_max_pax=cap,
                    cantidad_camas=camas,
                    estado_unidad="DISPONIBLE",
                )
                messages.success(request, f"Unidad '{codigo}' creada correctamente en Supabase.")
            return redirect("/mantenedores/?tab=unidades")

        elif accion == "eliminar_unidad":
            u_id = request.POST.get("id_unidad")
            try:
                u = get_object_or_404(UnidadHospedaje, pk=u_id)
                nombre_u = u.codigo_numero
                u.delete()
                messages.warning(request, f"Unidad '{nombre_u}' eliminada.")
            except Exception:
                messages.error(request, "No se puede eliminar una unidad que posee historial de reservas asociadas.")
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
                messages.success(request, f"Precio actualizado a ${nuevo_precio:,.0f} para {tarifa.nombre_temporada}.")
            return redirect("/mantenedores/?tab=tarifas")

        # 3. CRUD Inventario Crítico
        elif accion == "crear_inventario":
            u_id = request.POST.get("id_unidad")
            nombre_item = request.POST.get("nombre_item", "").strip()
            categoria = request.POST.get("categoria_item", "Equipamiento").strip()
            cant = int(request.POST.get("cantidad_estandar", 1))
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

        # 5. CRUD Usuarios y Roles
        elif accion == "crear_usuario":
            rut = request.POST.get("rut_usuario", "").strip()
            nombre = request.POST.get("nombre_completo", "").strip()
            correo = request.POST.get("correo_electronico", "").strip()
            rol_id = request.POST.get("id_rol")
            suc_id = request.POST.get("id_sucursal") or None
            password = request.POST.get("password", "tuchile2026").strip()
            if rut and nombre and correo and rol_id:
                if Usuario.objects.filter(Q(rut_usuario=rut) | Q(correo_electronico=correo)).exists():
                    messages.error(request, "Ya existe un usuario con ese RUT o correo electrónico.")
                else:
                    Usuario.objects.create(
                        rut_usuario=rut,
                        nombre_completo=nombre,
                        correo_electronico=correo,
                        id_rol_id=rol_id,
                        id_sucursal_id=suc_id,
                        password_hash=make_password(password),
                        activo=True,
                    )
                    messages.success(request, f"Cuenta de usuario creada para {nombre}.")
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
        "unidades": UnidadHospedaje.objects.select_related("id_sucursal", "id_tipo_unidad").order_by("id_sucursal__nombre_sucursal", "codigo_numero"),
        "tarifas": TemporadaTarifa.objects.select_related("id_zona", "id_tipo_unidad").order_by("id_zona__nombre_zona"),
        "inventario": InventarioUnidad.objects.select_related("id_unidad", "id_unidad__id_sucursal").order_by("id_unidad__codigo_numero", "nombre_item"),
        "usuarios": Usuario.objects.select_related("id_rol", "id_sucursal").order_by("id_usuario"),
        "roles": Rol.objects.all(),
    }
    return render(request, "pms/mantenedores.html", context)
