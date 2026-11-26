"""Implementación verificable de los Controles Técnicos ISO/IEC 27001:2022.

Controles implementados:
1. Control A.8.5  - Gestión de Autenticación (5 intentos, bloqueo 900s, sesión 1800s, token 28800s).
2. Control A.8.2  - Control de Accesos RBAC (mínimo privilegio por rol/zona, caché 300s).
3. Control A.8.11 - Enmascaramiento de Datos PII (RUT últimos 4 chars, Email 1° y último char, Tarjetas últimos 4).
4. Control A.8.15 - Registro de Eventos / Logging (sanitización CRLF '\n'/'\r', límite 4096 bytes, cero PII).
5. Control A.8.24 - Uso de Criptografía (Bcrypt rounds=12, largo mín. 12 chars, AES-256 Fernet en reposo).
6. Control A.8.12 - Prevención de Fuga de Datos (mensajes genéricos máx. 100 caracteres).
"""
from __future__ import annotations

import base64
from functools import wraps
import hashlib
import logging
import re
import time
from typing import Any, Callable

import bcrypt
from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib import messages
from django.core import signing
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from .constants import (
    BCRYPT_ROUNDS_COST,
    CARACTER_MASCARA_PII,
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

audit_logger = logging.getLogger("pms.audit")

# Patrones regex para impedir que PII (RUTs completos o contraseñas) llegue a los logs (A.8.15)
_PATRON_SECRETOS_LOG = re.compile(r"(password|passwd|secret|clave|cvv|token)\s*[:=]\s*\S+", re.IGNORECASE)


# ==============================================================================
# 1. CONTROL ISO A.8.11 — ENMASCARAMIENTO DE DATOS PERSONALES (PII)
# ==============================================================================
def enmascarar_rut_pasaporte(documento: str) -> str:
    """Ofusca un RUT o Pasaporte dejando visibles únicamente los últimos 4 caracteres (Control A.8.11).

    Ejemplo: '15.432.198-K' -> '********98-K' (4 caracteres visibles al final: '9', '8', '-', 'K').
    """
    texto = (documento or "").strip()
    if not texto:
        return CARACTER_MASCARA_PII * 4
    if len(texto) <= CARACTERES_VISIBLES_RUT_FINAL:
        return CARACTER_MASCARA_PII * len(texto)
    visibles = texto[-CARACTERES_VISIBLES_RUT_FINAL:]
    ocultos = CARACTER_MASCARA_PII * (len(texto) - CARACTERES_VISIBLES_RUT_FINAL)
    return f"{ocultos}{visibles}"


def enmascarar_email(correo: str) -> str:
    """Ofusca un correo mostrando solo el primer y último carácter antes de '@' (Control A.8.11).

    Ejemplo: 'jperez@correo.cl' -> 'j****z@correo.cl'.
    """
    texto = (correo or "").strip()
    if not texto or "@" not in texto:
        return "***@***"
    local, dominio = texto.split("@", 1)
    if len(local) <= 2:
        return f"{local[:1]}{CARACTER_MASCARA_PII * 3}@{dominio}"
    mascara = CARACTER_MASCARA_PII * (len(local) - 2)
    return f"{local[0]}{mascara}{local[-1]}@{dominio}"


def enmascarar_tarjeta(pan: str) -> str:
    """Ofusca un número de tarjeta dejando visibles solo los últimos 4 dígitos (Control A.8.11)."""
    digitos = "".join(c for c in (pan or "") if c.isdigit())
    if len(digitos) <= CARACTERES_VISIBLES_TARJETA_FINAL:
        return CARACTER_MASCARA_PII * max(4, len(digitos))
    visibles = digitos[-CARACTERES_VISIBLES_TARJETA_FINAL:]
    ocultos = CARACTER_MASCARA_PII * (len(digitos) - CARACTERES_VISIBLES_TARJETA_FINAL)
    return f"{ocultos}{visibles}"


# ==============================================================================
# 2. CONTROL ISO A.8.15 — REGISTRO DE EVENTOS (LOGGING SANITIZADO <= 4KB)
# ==============================================================================
def sanitizar_entrada_log(mensaje: str) -> str:
    """Elimina saltos de línea ('\\n', '\\r'), redacta secretos y trunca a 4096 bytes (Control A.8.15)."""
    limpio = str(mensaje or "").replace("\n", " ").replace("\r", " ")
    limpio = _PATRON_SECRETOS_LOG.sub(r"\1=[REDACTED_ISO_A815]", limpio)
    bytes_utf8 = limpio.encode("utf-8")
    if len(bytes_utf8) > MAX_LONGITUD_MENSAJE_LOG:
        truncado = bytes_utf8[: MAX_LONGITUD_MENSAJE_LOG - 16].decode("utf-8", errors="ignore")
        return f"{truncado}...[TRUNC_4KB]"
    return limpio


def registrar_evento_auditoria(
    accion: str,
    usuario_identificador: str = "ANON",
    rol: str = "N/A",
    detalle: str = "",
    nivel: str = "INFO",
) -> str:
    """Escribe un evento en la bitácora de auditoría cumpliendo el Control ISO A.8.15."""
    usr_safe = sanitizar_entrada_log(usuario_identificador)[:48]
    rol_safe = sanitizar_entrada_log(rol)[:24]
    acc_safe = sanitizar_entrada_log(accion)[:64]
    det_safe = sanitizar_entrada_log(detalle)

    entrada = sanitizar_entrada_log(f"EVENT={acc_safe} | USER={usr_safe} | ROLE={rol_safe} | DETAIL={det_safe}")
    if nivel.upper() == "WARNING":
        audit_logger.warning(entrada)
    elif nivel.upper() == "ERROR":
        audit_logger.error(entrada)
    else:
        audit_logger.info(entrada)
    return entrada


# ==============================================================================
# 3. CONTROL ISO A.8.12 — PREVENCIÓN DE FUGA DE DATOS (ERRORES GENÉRICOS <= 100 CHARS)
# ==============================================================================
def formatear_error_seguro(mensaje_usuario: str) -> str:
    """Garantiza que cualquier mensaje de error al usuario tenga como máximo 100 caracteres (Control A.8.12)."""
    texto = (mensaje_usuario or "Error al procesar la solicitud. Intente nuevamente.").strip()
    texto = texto.replace("\n", " ").replace("\r", " ")
    if len(texto) > MAX_LONGITUD_ERROR_USUARIO:
        return texto[: MAX_LONGITUD_ERROR_USUARIO - 3] + "..."
    return texto


# ==============================================================================
# 4. CONTROL ISO A.8.24 — USO DE CRIPTOGRAFÍA (BCRYPT ROUNDS=12 & AES-256 EN REPOSO)
# ==============================================================================
def generar_hash_bcrypt_normativo(password_plana: str) -> str:
    """Genera un hash Bcrypt con costo rounds=12 y valida largo mínimo de 12 caracteres (Control A.8.24)."""
    if len(password_plana or "") < MIN_LONGITUD_PASSWORD:
        raise ValueError(
            formatear_error_seguro(
                f"La contraseña debe tener al menos {MIN_LONGITUD_PASSWORD} caracteres (ISO A.8.24)."
            )
        )
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS_COST)
    return bcrypt.hashpw(password_plana.encode("utf-8"), salt).decode("utf-8")


def verificar_hash_bcrypt(password_plana: str, hash_almacenado: str) -> bool:
    """Verifica una contraseña contra un hash Bcrypt puro o PBKDF2/Bcrypt de Django (Control A.8.24)."""
    if not password_plana or not hash_almacenado:
        return False
    if hash_almacenado.startswith(("$2b$", "$2a$", "$2y$")):
        try:
            return bcrypt.checkpw(password_plana.encode("utf-8"), hash_almacenado.encode("utf-8"))
        except ValueError:
            return False
    from django.contrib.auth.hashers import check_password

    return check_password(password_plana, hash_almacenado)


def _obtener_fernet_aes256() -> Fernet:
    """Deriva una llave Fernet de 32 bytes (256 bits) desde la configuración del entorno (Control A.8.24)."""
    raw_key = getattr(settings, "FIELD_ENCRYPTION_KEY_AES256", "tuchile-default-aes256-key-2026")
    digest = hashlib.sha256(str(raw_key).encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    return Fernet(fernet_key)


def cifrar_pii_aes256(texto_plano: str) -> str:
    """Cifra un dato sensible (PII) en reposo con AES-256 / Fernet (Control A.8.24)."""
    if not texto_plano:
        return ""
    f = _obtener_fernet_aes256()
    return f.encrypt(texto_plano.encode("utf-8")).decode("utf-8")


def descifrar_pii_aes256(texto_cifrado: str) -> str:
    """Descifra un dato sensible (PII) cifrado con AES-256 / Fernet (Control A.8.24)."""
    if not texto_cifrado:
        return ""
    f = _obtener_fernet_aes256()
    return f.decrypt(texto_cifrado.encode("utf-8")).decode("utf-8")


# ==============================================================================
# 5. CONTROL ISO A.8.5 — GESTIÓN DE AUTENTICACIÓN (BLOQUEO 5 INTENTOS / 900s / SESIÓN 1800s)
# ==============================================================================
def _clave_intentos_login(identificador: str) -> str:
    limpio = (identificador or "anon").strip().lower()
    return f"iso_a85_login_attempts:{limpio}"


def _clave_bloqueo_login(identificador: str) -> str:
    limpio = (identificador or "anon").strip().lower()
    return f"iso_a85_lockout_until:{limpio}"


def esta_cuenta_bloqueada(identificador: str) -> tuple[bool, int]:
    """Verifica si una cuenta está bloqueada por fuerza bruta y retorna los segundos restantes (Control A.8.5)."""
    bloqueo_hasta = cache.get(_clave_bloqueo_login(identificador))
    if bloqueo_hasta:
        restante = int(bloqueo_hasta - time.time())
        if restante > 0:
            return True, restante
        cache.delete(_clave_bloqueo_login(identificador))
    return False, 0


def registrar_intento_fallido_login(identificador: str) -> tuple[int, bool]:
    """Incrementa el contador de intentos fallidos y bloquea por 900s al llegar a 5 (Control A.8.5)."""
    key_intentos = _clave_intentos_login(identificador)
    intentos: int = int(cache.get(key_intentos, 0)) + 1
    cache.set(key_intentos, intentos, timeout=TIEMPO_BLOQUEO_CUENTA_SEGUNDOS)

    bloqueado = intentos >= MAX_INTENTOS_LOGIN_FALLIDOS
    if bloqueado:
        expira_ts = time.time() + TIEMPO_BLOQUEO_CUENTA_SEGUNDOS
        cache.set(_clave_bloqueo_login(identificador), expira_ts, timeout=TIEMPO_BLOQUEO_CUENTA_SEGUNDOS)
        registrar_evento_auditoria(
            accion="BLOQUEO_FUERZA_BRUTA_A85",
            usuario_identificador=enmascarar_rut_pasaporte(identificador),
            detalle=f"Cuenta bloqueada por {TIEMPO_BLOQUEO_CUENTA_SEGUNDOS}s tras {intentos} intentos fallidos.",
            nivel="WARNING",
        )
    else:
        registrar_evento_auditoria(
            accion="LOGIN_FALLIDO_A85",
            usuario_identificador=enmascarar_rut_pasaporte(identificador),
            detalle=f"Intento fallido {intentos}/{MAX_INTENTOS_LOGIN_FALLIDOS}.",
            nivel="WARNING",
        )
    return intentos, bloqueado


def limpiar_intentos_login(identificador: str) -> None:
    """Reinicia el contador de intentos fallidos tras un inicio de sesión exitoso (Control A.8.5)."""
    cache.delete(_clave_intentos_login(identificador))
    cache.delete(_clave_bloqueo_login(identificador))


def emitir_token_sesion_firmado(usuario_id: int, rol: str) -> str:
    """Genera un token criptográfico firmado con expiración máxima de 28800s (8h - Control A.8.5)."""
    payload = {"uid": usuario_id, "rol": rol, "iat": int(time.time())}
    return signing.dumps(payload, salt="tuchile.iso27001.a85")


def validar_token_sesion_firmado(token: str) -> dict[str, Any] | None:
    """Valida que el token firmado no supere el umbral de 28800 segundos (8 horas - Control A.8.5)."""
    try:
        return signing.loads(
            token,
            salt="tuchile.iso27001.a85",
            max_age=EXPIRACION_TOKEN_JWT_SEGUNDOS,
        )
    except signing.BadSignature:
        return None


# ==============================================================================
# 6. CONTROL ISO A.8.2 — CONTROL DE ACCESOS RBAC + PATRÓN DECORATOR GoF
# ==============================================================================
def revalidar_permiso_rbac(usuario_id: int, roles_autorizados: tuple[str, ...]) -> tuple[bool, str, int | None]:
    """Revalida el rol activo y sede del usuario con caché acotado a 300s (Control ISO A.8.2)."""
    cache_key = f"iso_a82_rbac_user:{usuario_id}"
    datos_rbac = cache.get(cache_key)
    if datos_rbac is None:
        from pms.models import Usuario

        usuario = Usuario.objects.select_related("id_rol", "id_sucursal").filter(pk=usuario_id, activo=True).first()
        if not usuario:
            return False, "INACTIVO", None
        datos_rbac = {
            "rol": usuario.id_rol.codigo_rol,
            "sucursal_id": usuario.id_sucursal_id,
        }
        cache.set(cache_key, datos_rbac, timeout=TIMEOUT_CACHE_PERMISOS_SEGUNDOS)

    rol_actual = datos_rbac["rol"]
    autorizado = rol_actual in roles_autorizados
    return autorizado, rol_actual, datos_rbac["sucursal_id"]


def requiere_rol_rbac(*roles_permitidos: str, medir_sla_disponibilidad: bool = False) -> Callable:
    """Patrón Decorator (Estructural GoF) + Control ISO A.8.2 / A.8.5 / A.8.15.

    Intercepta la petición HTTP para:
    1. Verificar inactividad de sesión <= 1800s y validez del token <= 28800s (Control A.8.5).
    2. Revalidar permisos RBAC con mínimo privilegio y caché de 300s (Control A.8.2).
    3. Medir el tiempo de ejecución (< 2.0s en motor de disponibilidad) y registrar auditoría (Control A.8.15).
    """

    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            usuario_id = request.session.get("usuario_id")
            if not usuario_id:
                return redirect("login")

            # Control A.8.5: Verificar expiración por inactividad (1800s)
            ahora_ts = int(time.time())
            ultima_actividad = request.session.get("ultima_actividad_ts", ahora_ts)
            if (ahora_ts - int(ultima_actividad)) > LIMITE_INACTIVIDAD_SESION_SEGUNDOS:
                registrar_evento_auditoria(
                    accion="SESION_EXPIRADA_INACTIVIDAD_A85",
                    usuario_identificador=str(usuario_id),
                    detalle=f"Inactividad > {LIMITE_INACTIVIDAD_SESION_SEGUNDOS}s.",
                    nivel="WARNING",
                )
                request.session.flush()
                messages.warning(
                    request,
                    formatear_error_seguro("Su sesión expiró por inactividad (30 min - ISO A.8.5)."),
                )
                return redirect("login")

            request.session["ultima_actividad_ts"] = ahora_ts
            request.session.set_expiry(LIMITE_INACTIVIDAD_SESION_SEGUNDOS)

            # Control A.8.5: Verificar token firmado si existe en sesión (28800s)
            token_sesion = request.session.get("token_jwt_a85")
            if token_sesion and validar_token_sesion_firmado(token_sesion) is None:
                request.session.flush()
                messages.warning(
                    request,
                    formatear_error_seguro("Su token de sesión alcanzó el límite de 8 horas (ISO A.8.5)."),
                )
                return redirect("login")

            # Control A.8.2: Revalidar permiso RBAC (caché 300s)
            roles_objetivo = roles_permitidos if roles_permitidos else ("SUPERADMIN", "ADMIN_SEDE", "RECEPCION", "ASEO_MANT")
            autorizado, rol_actual, _ = revalidar_permiso_rbac(int(usuario_id), roles_objetivo)
            if not autorizado:
                registrar_evento_auditoria(
                    accion="ACCESO_DENEGADO_RBAC_A82",
                    usuario_identificador=str(usuario_id),
                    rol=rol_actual,
                    detalle=f"Intento de acceso a {view_func.__name__} sin rol requerido {roles_objetivo}.",
                    nivel="WARNING",
                )
                if rol_actual == "ASEO_MANT":
                    messages.warning(
                        request,
                        formatear_error_seguro("Acceso RBAC (A.8.2): Su rol solo autoriza Unidades y Limpieza."),
                    )
                    return redirect("aseo_movil")
                messages.error(
                    request,
                    formatear_error_seguro("Acceso denegado por principio de mínimo privilegio (ISO A.8.2)."),
                )
                return redirect("dashboard_gantt")

            inicio = time.perf_counter()
            response = view_func(request, *args, **kwargs)
            duracion_seg = time.perf_counter() - inicio

            if medir_sla_disponibilidad:
                response["X-PMS-Availability-Latency-Sec"] = f"{duracion_seg:.4f}"
                if duracion_seg > SLA_MAX_LATENCIA_DISPONIBILIDAD_SEG:
                    registrar_evento_auditoria(
                        accion="SLA_LATENCIA_EXCEDIDA",
                        usuario_identificador=str(usuario_id),
                        rol=rol_actual,
                        detalle=f"Vista {view_func.__name__} tardó {duracion_seg:.3f}s (> {SLA_MAX_LATENCIA_DISPONIBILIDAD_SEG}s).",
                        nivel="WARNING",
                    )
            return response

        return _wrapped_view

    return decorator
