# Sistema de Gestión de Arriendos (PMS) — Turismo TUCHILE (Evaluación Sumativa N°4)

Prototipo funcional en **Python 3.11+ / Django** para **Turismo TUCHILE** (liderada por Teresa Tapia Soto), diseñado para administrar las dos macrozonas operativas (**Zona Costera Central**: El Tabo, El Quisco, Las Cruces; y **Zona Sur de Lagos y Archipiélago**: Pucón, Villarrica, Lago Llanquihue y Ancud) aplicando **Patrones de Diseño GoF** y **Controles Técnicos ISO/IEC 27001:2022**.

---

## 1. Arquitectura Modular y Trazabilidad (Sección 6 del Enunciado)

```text
codigo/
├── .env.example                      # Variables de entorno requeridas (ISO A.8.9 / A.8.28 / A.8.31)
├── requirements.txt                  # Dependencias del proyecto (Django, bcrypt, cryptography, openpyxl)
├── README.md                         # Guía de instalación, patrones GoF, controles ISO y defensa en vivo
├── manage.py
├── seed_data.py                      # Carga inicial de macrozonas, sedes, roles, unidades y tarifas
├── tuchile_config/
│   └── settings.py                   # ConfiguracionSeguraSingleton (Fail-Fast A.8.9 + Logging A.8.15)
└── pms/
    ├── security/                     # Controles técnicos verificables ISO/IEC 27001:2022
    │   ├── constants.py              # Constantes normativas en MAYÚSCULAS (PEP 8)
    │   └── controls.py               # Implementación A.8.5, A.8.2, A.8.11, A.8.15, A.8.24 y A.8.12
    ├── domain/                       # Patrones de Diseño GoF (Creacional y de Comportamiento)
    │   ├── factories.py              # Creacional: Factory Method (Cabaña con gas/menaje vs Habitación)
    │   ├── states.py                 # Comportamiento: State (Disponible -> Ocupada -> Sucio -> Limpieza)
    │   └── strategies.py             # Comportamiento: Strategy (Cálculo dinámico de tarifas por temporada/zona)
    ├── services/                     # Casos de uso PMS + Patrón Estructural GoF
    │   └── facades.py                # Estructural: Facade (Disponibilidad < 2s, Check-in, Check-out, Caja)
    ├── models.py                     # 14 entidades relacionales del PMS + propiedades de enmascaramiento PII
    ├── views.py                      # Controladores HTTP protegidos con @requiere_rol_rbac (Decorator GoF)
    └── tests.py                      # Suite de pruebas automatizadas (Bloques 1 y 2 de la Defensa)
```

---

## 2. Los 3+ Patrones de Diseño GoF Implementados (Sección 3.1)

| Categoría GoF        | Patrón Implementado      | Archivo Principal            | Clase / Función Principal                   |
| :------------------- | :----------------------- | :--------------------------- | :------------------------------------------ |
| **1. Creacional**    | **Factory Method**       | `pms/domain/factories.py`    | `UnidadHospedajeFactory` / `CabanaUnidadFactory` |
| **1b. Creacional**   | **Singleton**            | `tuchile_config/settings.py` | `ConfiguracionSeguraSingleton`              |
| **2. Estructural**   | **Facade**               | `pms/services/facades.py`    | `OperacionesPMSFacade`                      |
| **2b. Estructural**  | **Decorator**            | `pms/security/controls.py`   | `@requiere_rol_rbac`                        |
| **3. Comportamiento**| **State**                | `pms/domain/states.py`       | `EstadoUnidadState` (`EstadoDisponible`, etc.) |
| **3b. Comportamiento**| **Strategy**            | `pms/domain/strategies.py`   | `EstrategiaTarifa` (`resolver_estrategia_tarifa`) |

### Detalle de Aplicación en Turismo TUCHILE:
* **1. Creacional (`Factory Method` + `Singleton`):**
  * **Archivo:** `pms/domain/factories.py` (`UnidadHospedajeFactory`, `CabanaUnidadFactory`, `HabitacionHotelFactory`).
  * **Problema que resuelve:** Diferencia la creación de **Cabañas** (instancia automáticamente su kit de inventario crítico: *Cilindro de Gas 15 Kg*, *Set de Vajilla y Cubiertos*, *Smart TV*, *Ropa de cama*) frente a **Habitaciones de Hotel** (kit hotelero con *Frigobar* y sin gas).
* **2. Estructural (`Facade` + `Decorator`):**
  * **Archivo:** `pms/services/facades.py` (`OperacionesPMSFacade`) y `pms/security/controls.py` (`@requiere_rol_rbac`).
  * **Problema que resuelve:** Orquesta en una sola llamada transaccional el **Check-out complejo** (cobro de multas de inventario + movimiento en `CajaDiaria` + ticket en `IncidenciaAseo` + paso automático de unidad a `'SUCIO'`) y verifica disponibilidad sin overbooking en **`< 2 segundos`**.
* **3. Comportamiento (`State` + `Strategy`):**
  * **Archivo:** `pms/domain/states.py` (`EstadoUnidadState`) y `pms/domain/strategies.py` (`EstrategiaTarifa`).
  * **Problema que resuelve:** **State** controla la máquina de estados de la unidad (`DISPONIBLE -> OCUPADA -> SUCIO -> EN_LIMPIEZA / MANTENIMIENTO`), impidiendo hacer Check-in en una cabaña sucia. **Strategy** intercambia el cálculo de tarifa según Macrozona (descuento 10% en Sur por `>= 5` noches) y Temporada Alta (+15% en Verano/Fiestas Patrias).

---

## 3. Los Controles ISO/IEC 27001:2022 y Umbrales Normativos (Sección 3.2)

Todas las constantes están declaradas en **MAYÚSCULAS (PEP 8)** en `pms/security/constants.py`:

1. **Control A.8.5 — Gestión de Autenticación (`pms/security/controls.py`):**
   - `MAX_INTENTOS_LOGIN_FALLIDOS = 5`
   - `TIEMPO_BLOQUEO_CUENTA_SEGUNDOS = 900` (15 minutos de bloqueo tras el 5° intento fallido)
   - `LIMITE_INACTIVIDAD_SESION_SEGUNDOS = 1800` (30 minutos de expiración por inactividad)
   - `EXPIRACION_TOKEN_JWT_SEGUNDOS = 28800` (8 horas de validez máxima del token firmado)
2. **Control A.8.2 — Control de Accesos RBAC (`pms/security/controls.py`):**
   - `TIMEOUT_CACHE_PERMISOS_SEGUNDOS = 300` (5 minutos de caché de permisos con revalidación en cada operación por rol: `SUPERADMIN`, `ADMIN_SEDE`, `RECEPCION`, `ASEO_MANT`).
3. **Control A.8.11 — Enmascaramiento de Datos PII (`pms/security/controls.py`):**
   - `CARACTERES_VISIBLES_RUT_FINAL = 4` (ej. `15.432.198-K` -> `********98-K` en listado de reservas y exportación Excel).
   - `enmascarar_email`: muestra solo el 1° y último carácter antes de `@` (ej. `jperez@correo.cl` -> `j****z@correo.cl`).
   - `CARACTERES_VISIBLES_TARJETA_FINAL = 4` (`************0366`).
4. **Control A.8.15 — Registro de Eventos / Logging (`pms/security/controls.py`):**
   - `MAX_LONGITUD_MENSAJE_LOG = 4096` (4 KB máximo por entrada en `audit_security.log`).
   - Sanitización obligatoria de `\n` y `\r` (Anti Log Injection) y redacción automática de contraseñas/PII.
5. **Control A.8.24 y A.8.12 — Criptografía y Prevención de Fuga de Datos:**
   - `BCRYPT_ROUNDS_COST = 12`, `MIN_LONGITUD_PASSWORD = 12` y cifrado `AES-256 (Fernet)` en reposo.
   - `MAX_LONGITUD_ERROR_USUARIO = 100` (mensajes de error genéricos acotados a 100 caracteres).

---

## 4. Guía Rápida de Ejecución y Defensa en Vivo (25 Minutos)

### A. Levantar el Servidor Local
```powershell
cd "C:\Users\janoa\Desktop\TUCHILE_PMS\codigo"
.\venv\Scripts\python.exe manage.py runserver
```
* **Credenciales de prueba (contraseña para todos: `tuchile2026`):**
  * **Superadministrador:** `ttapia@tuchile.cl` (Teresa Tapia Soto — Acceso total y Mantenedores)
  * **Recepcionista:** `recepcion.tabo@tuchile.cl` (Camila Muñoz — Gantt, Reservas, Check-in/out y Caja)
  * **Personal de Aseo:** `aseo.tabo@tuchile.cl` (Pedro Soto — Vista simplificada de Unidades y Limpieza)

### B. Ejecutar la Auditoría Automatizada de Controles ISO y Patrones GoF (Bloque 2)
```powershell
.\venv\Scripts\python.exe manage.py test pms -v 2
```

### C. Recetas para el Bloque 3 (Modificación en Vivo frente al Docente)
1. **Si el docente pide cambiar un umbral ISO 27001 (ej. *"que bloquee al 3° intento"* o *"mostrar los últimos 3 caracteres del RUT"*):**
   - Abre `pms/security/constants.py` y cambia `MAX_INTENTOS_LOGIN_FALLIDOS = 3` o `CARACTERES_VISIBLES_RUT_FINAL = 3`.
2. **Si el docente pide extender el Patrón Creacional Factory Method (ej. *"agregar un Domo Glamping con Telescopio"*):**
   - Abre `pms/domain/factories.py`, duplica `CabanaUnidadFactory` como `DomoGlampingFactory(UnidadHospedajeFactory)` agregando el ítem `"Telescopio Astronómico"` en `obtener_plantilla_inventario()`.
3. **Si el docente pide agregar una nueva regla de tarifa en Strategy (ej. *"descuento de Adulto Mayor 20%"*):**
   - Abre `pms/domain/strategies.py` y crea `class TarifaAdultoMayorStrategy(EstrategiaTarifa)` con `FACTOR = Decimal("0.80")`.
