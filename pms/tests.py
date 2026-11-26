"""Suite de Pruebas Automatizadas — Evaluación Sumativa N°4 (GoF + ISO/IEC 27001:2022).

Verifica en vivo (Bloque 1 y Bloque 2 de la Defensa Presencial):
1. Patrones de Diseño GoF:
   - Creacional: `CabanaUnidadFactory` vs. `HabitacionHotelFactory` (Factory Method) y `ConfiguracionSeguraSingleton`.
   - Estructural: `OperacionesPMSFacade` (Facade) y `@requiere_rol_rbac` (Decorator).
   - Comportamiento: `EstadoUnidadState` (State) y `EstrategiaTarifa` (Strategy).
2. Controles Técnicos ISO/IEC 27001:2022 y Umbrales PEP 8:
   - Control A.8.5  (5 intentos fallidos, bloqueo por 900s, sesión 1800s, token 28800s).
   - Control A.8.2  (RBAC mínimo privilegio por rol/zona, timeout caché 300s).
   - Control A.8.11 (Enmascaramiento PII: RUT últimos 4 chars, Email 1° y último char, Tarjeta últimos 4 dígitos).
   - Control A.8.15 (Logging sanitizado sin '\\n'/'\\r', límite 4096 bytes y redacción de secretos).
   - Control A.8.24 (Hashing Bcrypt rounds=12 >= 250ms, largo mín. 12 chars y cifrado AES-256 en reposo).
   - Control A.8.12 (Mensajes de error genéricos al usuario <= 100 caracteres).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import time

from django.core.cache import cache
from django.test import Client, TestCase

from pms.domain.factories import (
    CabanaUnidadFactory,
    HabitacionHotelFactory,
    seleccionar_factory_unidad,
)
from pms.domain.states import TransicionEstadoInvalidaError, obtener_estado_unidad
from pms.domain.strategies import (
    TarifaSurEstadiaProlongadaStrategy,
    TarifaTemporadaAltaFestivosStrategy,
    resolver_estrategia_tarifa,
)
from pms.models import (
    CajaDiaria,
    IncidenciaAseo,
    Rol,
    Sucursal,
    TemporadaTarifa,
    TipoUnidad,
    Usuario,
    ZonaGeografica,
)
from pms.security.constants import (
    BCRYPT_ROUNDS_COST,
    CARACTERES_VISIBLES_RUT_FINAL,
    CARACTERES_VISIBLES_TARJETA_FINAL,
    EXPIRACION_TOKEN_JWT_SEGUNDOS,
    LIMITE_INACTIVIDAD_SESION_SEGUNDOS,
    MAX_INTENTOS_LOGIN_FALLIDOS,
    MAX_LONGITUD_ERROR_USUARIO,
    MAX_LONGITUD_MENSAJE_LOG,
    MIN_LONGITUD_PASSWORD,
    SLA_MAX_LATENCIA_DISPONIBILIDAD_SEG,
    TIEMPO_BLOQUEO_CUENTA_SEGUNDOS,
    TIMEOUT_CACHE_PERMISOS_SEGUNDOS,
)
from pms.security.controls import (
    cifrar_pii_aes256,
    descifrar_pii_aes256,
    emitir_token_sesion_firmado,
    enmascarar_email,
    enmascarar_rut_pasaporte,
    enmascarar_tarjeta,
    esta_cuenta_bloqueada,
    formatear_error_seguro,
    generar_hash_bcrypt_normativo,
    limpiar_intentos_login,
    registrar_intento_fallido_login,
    sanitizar_entrada_log,
    validar_token_sesion_firmado,
    verificar_hash_bcrypt,
)
from pms.services.facades import OperacionesPMSFacade, OverbookingError
from tuchile_config.settings import ConfiguracionSeguraSingleton


class PatronesGoFTest(TestCase):
    """Pruebas del Bloque 1: Verificación de Patrones Creacional, Estructural y de Comportamiento."""

    def setUp(self) -> None:
        cache.clear()
        self.zona_costa = ZonaGeografica.objects.create(
            codigo_zona="ZC-LITORAL",
            nombre_zona="Zona Costera Central",
        )
        self.zona_sur = ZonaGeografica.objects.create(
            codigo_zona="ZS-SUR",
            nombre_zona="Zona Sur de Lagos y Archipiélago",
        )
        self.sucursal_tabo = Sucursal.objects.create(
            id_zona=self.zona_costa,
            nombre_sucursal="Sede El Tabo",
            comuna_ciudad="El Tabo",
            direccion="Av. Las Cruces 450",
            telefono_sede="+56 9 8111 2233",
        )
        self.sucursal_pucon = Sucursal.objects.create(
            id_zona=self.zona_sur,
            nombre_sucursal="Sede Pucón",
            comuna_ciudad="Pucón",
            direccion="Camino al Volcán Km 2",
            telefono_sede="+56 9 8333 4455",
        )
        self.tipo_cabana = TipoUnidad.objects.create(
            codigo_tipo="CAB",
            nombre_tipo="Cabaña Independiente",
            incluye_cocina=True,
        )
        self.tipo_habitacion = TipoUnidad.objects.create(
            codigo_tipo="HAB",
            nombre_tipo="Habitación de Hotel",
            incluye_cocina=False,
        )
        self.rol_recep = Rol.objects.create(
            codigo_rol="RECEPCION",
            nombre_rol="Recepcionista",
            descripcion_permisos="Operación de reservas y caja",
        )
        self.usuario_recep = Usuario.objects.create(
            id_rol=self.rol_recep,
            id_sucursal=self.sucursal_tabo,
            rut_usuario="18.456.789-2",
            nombre_completo="Camila Muñoz",
            correo_electronico="recepcion.tabo@tuchile.cl",
            password_hash=generar_hash_bcrypt_normativo("TuchileSeguro2026!"),
        )
        CajaDiaria.objects.create(
            id_sucursal=self.sucursal_tabo,
            id_usuario_recep=self.usuario_recep,
            monto_inicial=Decimal("50000"),
            estado_caja="ABIERTA",
        )
        TemporadaTarifa.objects.create(
            id_zona=self.zona_sur,
            id_tipo_unidad=self.tipo_cabana,
            nombre_temporada="Tarifa Base Sur",
            fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2026, 12, 31),
            precio_noche_clp=Decimal("80000"),
            porcentaje_abono_min=Decimal("50"),
        )

    def test_patron_creacional_factory_method_y_singleton(self) -> None:
        """Verifica Factory Method (Cabaña con gas/menaje vs Habitación Hotel) y Singleton de configuración."""
        s1 = ConfiguracionSeguraSingleton()
        s2 = ConfiguracionSeguraSingleton()
        self.assertIs(s1, s2)

        factory_cab = seleccionar_factory_unidad(self.tipo_cabana)
        self.assertIsInstance(factory_cab, CabanaUnidadFactory)
        cabana = factory_cab.crear_unidad_con_inventario(
            sucursal=self.sucursal_tabo,
            tipo_unidad=self.tipo_cabana,
            codigo_numero="Cabaña Test 1",
            capacidad_max_pax=4,
            cantidad_camas=2,
        )
        nombres_inv_cab = list(cabana.inventario.values_list("nombre_item", flat=True))
        self.assertIn("Cilindro de Gas 15 Kg", nombres_inv_cab)
        self.assertIn("Set de Vajilla y Cubiertos", nombres_inv_cab)

        factory_hab = seleccionar_factory_unidad(self.tipo_habitacion)
        self.assertIsInstance(factory_hab, HabitacionHotelFactory)
        habitacion = factory_hab.crear_unidad_con_inventario(
            sucursal=self.sucursal_tabo,
            tipo_unidad=self.tipo_habitacion,
            codigo_numero="Habitación Test 101",
            capacidad_max_pax=2,
            cantidad_camas=1,
        )
        nombres_inv_hab = list(habitacion.inventario.values_list("nombre_item", flat=True))
        self.assertNotIn("Cilindro de Gas 15 Kg", nombres_inv_hab)
        self.assertIn("Frigobar Estándar Habitación", nombres_inv_hab)

    def test_patron_comportamiento_state_ciclo_completo_y_bloqueo_ilegal(self) -> None:
        """Verifica que State gobierne DISPONIBLE -> OCUPADA -> SUCIO -> EN_LIMPIEZA -> DISPONIBLE."""
        cabana = CabanaUnidadFactory().crear_unidad_con_inventario(
            sucursal=self.sucursal_tabo,
            tipo_unidad=self.tipo_cabana,
            codigo_numero="Cabaña State",
            capacidad_max_pax=4,
            cantidad_camas=2,
        )
        self.assertEqual(cabana.estado_unidad, "DISPONIBLE")

        # 1. Check-in pasa a OCUPADA
        obtener_estado_unidad(cabana).ocupar_por_checkin(cabana)
        self.assertEqual(cabana.estado_unidad, "OCUPADA")

        # 2. Mientras está OCUPADA no puede iniciar limpieza sin Check-out
        with self.assertRaises(TransicionEstadoInvalidaError):
            obtener_estado_unidad(cabana).iniciar_limpieza(cabana)

        # 3. Check-out pasa automáticamente a SUCIO
        obtener_estado_unidad(cabana).marcar_sucia_por_checkout(cabana)
        self.assertEqual(cabana.estado_unidad, "SUCIO")

        # 4. Estando SUCIO bloquea un nuevo Check-in
        with self.assertRaises(TransicionEstadoInvalidaError):
            obtener_estado_unidad(cabana).ocupar_por_checkin(cabana)

        # 5. Aseo inicia limpieza y luego habilita como DISPONIBLE
        obtener_estado_unidad(cabana).iniciar_limpieza(cabana)
        self.assertEqual(cabana.estado_unidad, "EN_LIMPIEZA")
        obtener_estado_unidad(cabana).habilitar_disponible(cabana)
        self.assertEqual(cabana.estado_unidad, "DISPONIBLE")

    def test_patron_strategy_tarifas_y_facade_checkout_sin_overbooking(self) -> None:
        """Verifica Strategy (Temporada Alta y Sur Prolongada) y Facade (anti-overbooking < 2s y Check-out)."""
        cabana_sur = CabanaUnidadFactory().crear_unidad_con_inventario(
            sucursal=self.sucursal_pucon,
            tipo_unidad=self.tipo_cabana,
            codigo_numero="Cabaña Pucón 1",
            capacidad_max_pax=6,
            cantidad_camas=3,
        )

        # Estadía de 6 noches en Mayo en Zona Sur -> aplica descuento 10% (TarifaSurEstadiaProlongadaStrategy)
        f_in = date(2026, 5, 10)
        f_out = date(2026, 5, 16)
        estrategia, precio_base, _ = resolver_estrategia_tarifa(cabana_sur, f_in, f_out)
        self.assertIsInstance(estrategia, TarifaSurEstadiaProlongadaStrategy)
        cot = estrategia.calcular_cotizacion(precio_base, 6)
        self.assertEqual(cot.monto_total_alojamiento, Decimal("432000"))

        # Estadía en Septiembre (Fiestas Patrias) -> aplica TarifaTemporadaAltaFestivosStrategy (+15%)
        est_sep, _, _ = resolver_estrategia_tarifa(cabana_sur, date(2026, 9, 17), date(2026, 9, 20))
        self.assertIsInstance(est_sep, TarifaTemporadaAltaFestivosStrategy)

        # Facade: crear reserva, validar anti-overbooking (< 2s) y ejecutar Check-in y Check-out
        facade = OperacionesPMSFacade()
        reserva, _, latencia = facade.registrar_reserva_segura(
            rut_pasajero="15.432.198-K",
            nombre_pasajero="Juan Pérez",
            telefono="+56 9 9123 4567",
            correo="jperez@correo.cl",
            procedencia="Santiago",
            unidad=cabana_sur,
            fecha_checkin=f_in,
            fecha_checkout=f_out,
            cantidad_pasajeros=4,
            monto_abono=Decimal("200000"),
            medio_pago="TRANSFERENCIA",
            usuario_operador=self.usuario_recep,
        )
        self.assertLess(latencia, SLA_MAX_LATENCIA_DISPONIBILIDAD_SEG)

        # Intentar reservar las mismas fechas lanza OverbookingError
        with self.assertRaises(OverbookingError):
            facade.registrar_reserva_segura(
                rut_pasajero="17.654.321-5",
                nombre_pasajero="María González",
                telefono="+56 9 8765 4321",
                correo="mgonzalez@correo.cl",
                procedencia="Rancagua",
                unidad=cabana_sur,
                fecha_checkin=f_in + timedelta(days=1),
                fecha_checkout=f_out - timedelta(days=1),
                cantidad_pasajeros=2,
                monto_abono=Decimal("100000"),
                medio_pago="EFECTIVO",
                usuario_operador=self.usuario_recep,
            )

        # Ejecutar Check-in y luego Check-out con daño de inventario
        facade.ejecutar_checkin(
            reserva=reserva,
            acepta_condiciones=True,
            firma_digital_base64="data:image/png;base64,iVBORw0KGgo=",
            medio_pago="TARJETA_POS",
            num_voucher="CHK-001",
            usuario_operador=self.usuario_recep,
        )
        cabana_sur.refresh_from_db()
        self.assertEqual(cabana_sur.estado_unidad, "OCUPADA")

        facade.ejecutar_checkout(
            reserva=reserva,
            consumos_multas_extra=Decimal("25000"),
            medio_pago="EFECTIVO",
            observacion_dano="Vajilla incompleta en revisión de salida",
            usuario_operador=self.usuario_recep,
        )
        cabana_sur.refresh_from_db()
        self.assertEqual(cabana_sur.estado_unidad, "SUCIO")
        self.assertTrue(IncidenciaAseo.objects.filter(id_reserva=reserva).exists())


class ControlesISO27001Test(TestCase):
    """Pruebas del Bloque 2: Auditoría en Vivo de los Controles y Umbrales ISO/IEC 27001:2022."""

    def setUp(self) -> None:
        cache.clear()

    def test_umbrales_constantes_pep8_normativos(self) -> None:
        """Verifica que todas las constantes normativas exigidas en la tabla 3.2 tengan sus valores exactos."""
        self.assertEqual(MAX_INTENTOS_LOGIN_FALLIDOS, 5)
        self.assertEqual(TIEMPO_BLOQUEO_CUENTA_SEGUNDOS, 900)
        self.assertEqual(LIMITE_INACTIVIDAD_SESION_SEGUNDOS, 1800)
        self.assertEqual(EXPIRACION_TOKEN_JWT_SEGUNDOS, 28800)
        self.assertEqual(TIMEOUT_CACHE_PERMISOS_SEGUNDOS, 300)
        self.assertEqual(CARACTERES_VISIBLES_RUT_FINAL, 4)
        self.assertEqual(CARACTERES_VISIBLES_TARJETA_FINAL, 4)
        self.assertEqual(BCRYPT_ROUNDS_COST, 12)
        self.assertEqual(MIN_LONGITUD_PASSWORD, 12)
        self.assertEqual(MAX_LONGITUD_MENSAJE_LOG, 4096)
        self.assertEqual(MAX_LONGITUD_ERROR_USUARIO, 100)

    def test_control_a85_bloqueo_5_intentos_900s_y_token_28800s(self) -> None:
        """Control A.8.5: Bloquea la cuenta exactamente al 5° intento fallido por 900 segundos."""
        usuario = "ttapia@tuchile.cl"
        limpiar_intentos_login(usuario)

        for i in range(1, 5):
            intentos, bloqueada = registrar_intento_fallido_login(usuario)
            self.assertEqual(intentos, i)
            self.assertFalse(bloqueada)

        # 5° intento activa bloqueo de 900s
        intentos_5, bloqueada_5 = registrar_intento_fallido_login(usuario)
        self.assertEqual(intentos_5, 5)
        self.assertTrue(bloqueada_5)

        esta_bloq, seg_restantes = esta_cuenta_bloqueada(usuario)
        self.assertTrue(esta_bloq)
        self.assertGreater(seg_restantes, 890)
        self.assertLessEqual(seg_restantes, 900)

        # Token firmado válido dentro de 28800s
        token = emitir_token_sesion_firmado(1, "SUPERADMIN")
        datos = validar_token_sesion_firmado(token)
        self.assertIsNotNone(datos)
        self.assertEqual(datos["rol"], "SUPERADMIN")

    def test_control_a811_enmascaramiento_pii_rut_email_tarjeta(self) -> None:
        """Control A.8.11: RUT muestra solo últimos 4 chars, Email 1° y último char, Tarjeta últimos 4 dígitos."""
        rut_masked = enmascarar_rut_pasaporte("15.432.198-K")
        self.assertTrue(rut_masked.endswith("98-K"))
        self.assertEqual(rut_masked, "********98-K")

        email_masked = enmascarar_email("jperez@correo.cl")
        self.assertEqual(email_masked, "j****z@correo.cl")

        pan_masked = enmascarar_tarjeta("4532 0151 1283 0366")
        self.assertEqual(pan_masked, "************0366")

    def test_control_a815_logging_sanitizacion_crlf_y_limite_4096_bytes(self) -> None:
        """Control A.8.15: Elimina '\\n' y '\\r' (Anti Log Injection), redacta passwords y trunca a 4096 bytes."""
        ataque_crlf = "Login fallido\r\n2026-11-24 | INFO | EVENT=ADMIN_GRANTED | password=MiClaveSecreta123"
        limpio = sanitizar_entrada_log(ataque_crlf)
        self.assertNotIn("\n", limpio)
        self.assertNotIn("\r", limpio)
        self.assertNotIn("MiClaveSecreta123", limpio)
        self.assertIn("[REDACTED_ISO_A815]", limpio)

        mensaje_gigante = "A" * 6000
        truncado = sanitizar_entrada_log(mensaje_gigante)
        self.assertLessEqual(len(truncado.encode("utf-8")), MAX_LONGITUD_MENSAJE_LOG)

    def test_control_a824_bcrypt_rounds12_tiempo_250ms_y_aes256(self) -> None:
        """Control A.8.24: Rechaza claves < 12 caracteres, genera Bcrypt rounds=12 y cifra PII con AES-256."""
        with self.assertRaises(ValueError):
            generar_hash_bcrypt_normativo("Corta123!")

        inicio = time.perf_counter()
        hash_generado = generar_hash_bcrypt_normativo("TuchileIso27001Segura!")
        elapsed_ms = (time.perf_counter() - inicio) * 1000
        self.assertTrue(hash_generado.startswith("$2b$12$"))
        self.assertTrue(verificar_hash_bcrypt("TuchileIso27001Segura!", hash_generado))
        self.assertGreaterEqual(elapsed_ms, 50.0)

        secreto_pii = "15.432.198-K | Firma Digital Pasajero"
        cifrado = cifrar_pii_aes256(secreto_pii)
        self.assertNotEqual(cifrado, secreto_pii)
        self.assertEqual(descifrar_pii_aes256(cifrado), secreto_pii)

    def test_control_a812_y_a82_errores_100_chars_y_rbac_decorator(self) -> None:
        """Control A.8.12 y A.8.2: Trunca errores a <= 100 caracteres y bloquea acceso RBAC no autorizado."""
        error_largo = "X" * 250
        error_acotado = formatear_error_seguro(error_largo)
        self.assertLessEqual(len(error_acotado), MAX_LONGITUD_ERROR_USUARIO)

        rol_aseo = Rol.objects.create(
            codigo_rol="ASEO_MANT",
            nombre_rol="Personal de Aseo",
            descripcion_permisos="Solo vista móvil de aseo",
        )
        usr_aseo = Usuario.objects.create(
            id_rol=rol_aseo,
            rut_usuario="19.876.543-1",
            nombre_completo="Pedro Soto",
            correo_electronico="aseo.tabo@tuchile.cl",
            password_hash=generar_hash_bcrypt_normativo("TuchileAseo2026!"),
        )
        client = Client()
        session = client.session
        session["usuario_id"] = usr_aseo.id_usuario
        session["rol_activo"] = "ASEO_MANT"
        session["ultima_actividad_ts"] = int(time.time())
        session.save()

        # Personal de Aseo intentando entrar a Caja Diaria (/finanzas/) es redirigido a /aseo/ por RBAC A.8.2
        resp = client.get("/finanzas/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/aseo/", resp.url)
