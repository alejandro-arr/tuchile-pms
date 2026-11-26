"""Constantes y umbrales normativos explícitos bajo ISO/IEC 27001:2022 (PEP 8).

"""

# ==============================================================================
# CONTROL ISO A.8.5 — GESTIÓN DE AUTENTICACIÓN SEGURA
# ==============================================================================
MAX_INTENTOS_LOGIN_FALLIDOS: int = 5            # Máx. 5 intentos fallidos antes de bloquear
TIEMPO_BLOQUEO_CUENTA_SEGUNDOS: int = 900       # Bloqueo temporal de cuenta por 900s (15 min)
LIMITE_INACTIVIDAD_SESION_SEGUNDOS: int = 1800  # Expiración de sesión por inactividad en 1800s (30 min)
EXPIRACION_TOKEN_JWT_SEGUNDOS: int = 28800      # Tiempo máximo de vida de token firmado: 28800s (8h)

# ==============================================================================
# CONTROL ISO A.8.2 — CONTROL DE ACCESOS PRIVILEGIADOS (RBAC)
# ==============================================================================
TIMEOUT_CACHE_PERMISOS_SEGUNDOS: int = 300      # Timeout de caché de permisos RBAC: 300s (5 min)
ROLES_PERMITIDOS_SISTEMA: tuple[str, ...] = (
    "SUPERADMIN",
    "ADMIN_SEDE",
    "RECEPCION",
    "ASEO_MANT",
)

# ==============================================================================
# CONTROL ISO A.8.11 — ENMASCARAMIENTO DE DATOS PERSONALES (PII)
# ==============================================================================
CARACTERES_VISIBLES_RUT_FINAL: int = 4          # RUT/Pasaporte muestra solo los últimos 4 caracteres
CARACTERES_VISIBLES_TARJETA_FINAL: int = 4      # Tarjetas muestran solo los últimos 4 dígitos
CARACTER_MASCARA_PII: str = "*"                 # Carácter estándar de ofuscación PII

# ==============================================================================
# CONTROL ISO A.8.24 — USO DE CRIPTOGRAFÍA
# ==============================================================================
BCRYPT_ROUNDS_COST: int = 12                    # Factor de trabajo Bcrypt (rounds=12, >= 250ms)
MIN_LONGITUD_PASSWORD: int = 12                 # Largo mínimo de contraseña: 12 caracteres
TIEMPO_MIN_HASH_MS: int = 250                   # Umbral mínimo de tiempo de hashing en milisegundos
DIAS_EXPIRACION_LLAVE_AES: int = 90             # Rotación de llave simétrica AES-256 cada 90 días

# ==============================================================================
# CONTROL ISO A.8.15 — REGISTRO DE EVENTOS Y AUDITORÍA (LOGGING)
# ==============================================================================
MAX_LONGITUD_MENSAJE_LOG: int = 4096            # Límite máximo de 4096 bytes (4 KB) por entrada de log
DIAS_RETENCION_LOGS_AUDITORIA: int = 365        # Retención de bitácora de auditoría por 365 días

# ==============================================================================
# CONTROL ISO A.8.12 — PREVENCIÓN DE FUGA DE DATOS
# ==============================================================================
MAX_LONGITUD_ERROR_USUARIO: int = 100           # Mensajes de error genéricos al usuario <= 100 caracteres

# ==============================================================================
# CONTROL ISO A.8.28 / A.8.9 / A.8.31 — CODIFICACIÓN SEGURA Y ENTORNOS
# ==============================================================================
DB_QUERY_TIMEOUT_SEGUNDOS: int = 5              # Timeout máximo de consultas a Base de Datos: 5s
SLA_MAX_LATENCIA_DISPONIBILIDAD_SEG: float = 2.0  # Consulta de disponibilidad sin overbooking < 2s
ENTORNOS_VALIDOS: tuple[str, ...] = ("production", "staging", "development")
