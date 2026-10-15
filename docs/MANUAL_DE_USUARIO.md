# Manual de usuario de SIBILA

**Fecha del documento:** 2026-10-12 · **Estado del código descrito:** árbol `nucleo/` tras las reparaciones del Día 1 del cierre (CRIT-1, CRIT-2, ALTO-1, CRIT-3 y pin urllib3 2.8.0; ver el Anexo C).
**Este manual reúne en un solo documento la instalación, la configuración, el uso de la CLI y los anexos técnicos (arquitectura, seguridad, pruebas y estado, tareas pendientes y conservación). Existe versión en inglés: `USER_MANUAL.md`.**

> Etiquetas de evidencia usadas en este manual: **[EJEC]** = comprobado por ejecución real (con fecha); **[INSP]** = comprobado por inspección directa del código citado; **[DOC]** = consta en los informes del proyecto, citado sin re-ejecutar.

**Contenido:** §1 Instalación · §2 Configuración · §3 Uso de la CLI · Anexo A Arquitectura · Anexo B Seguridad y privacidad · Anexo C Pruebas y estado real · Anexo D Tareas pendientes · Anexo E Conservación.

---

## 1 · Instalación

### 1.1 Requisitos

| Requisito | Detalle | Evidencia |
|---|---|---|
| **Python** | Objetivo: **3.12** (verificado en 3.12.12). Mínimo funcional: **3.11** (por `tomllib`, usado para leer la configuración). Con 3.11 o 3.13+ `sibila check` arranca pero marca **AVISO** «distinto del objetivo 3.12; no probado». Con <3.11 el programa no funciona. | [INSP] `sibila/cli.py` (_cmd_check); [EJEC] suite ejecutada en Python 3.12.12 el 2026-10-12 |
| **Sistema operativo** | Desarrollado en **Linux x86_64**; pensado para **Windows** (los `.bat`, los XML de tareas y `instalar.bat` son Windows-only por diseño). **Instalación y funcionamiento verificados en dos pruebas reales de Windows 11 (2026-10-15, W1–W14)**; pendiente solo el ciclo natural de 24 h (ver el Anexo D). | [INSP] + [DOC] auditoría de cierre + pruebas Windows |
| **Disco** | ~300 MB adicionales si se instala `lingua` (su wheel pesa ~170 MB y el modelo cargado más); el resto es modesto (la BD crece con los datos). `check` avisa si quedan <1 GB libres. | [INSP] `cli.py` (aviso de espacio), [DOC] D-066 / LEEME_T2 |
| **Red** | Solo para: instalación de dependencias, descarga de recursos de datos, **ingesta real**, **alertas** y la descarga de la referencia GDELT (`informe --actualizar-gdelt`). La batería de tests y todo el procesado local funcionan sin red. | [INSP] |
| **Git (opcional)** | Necesario solo para el anclaje del registro sellado (`registro anclar`). Sin git: el anclaje queda «pendiente» con AVISO, nunca es fallo. | [INSP] `sibila/anclaje.py`, `doctor.py` |
| **ots (opcional)** | `opentimestamps-client` (no está en `requirements.txt`; va en un requirements-extra futuro). Sin él, el sello de tiempo externo queda desactivado (AVISO). | [INSP] `requirements.txt`, `anclaje.py` |

### 1.2 Dependencias (pins exactos de `requirements.txt`)

Todas las versiones están **fijadas** para instalación reproducible:

| Paquete | Pin | Para qué |
|---|---|---|
| feedparser | `6.0.12` | RSS/Atom (Lobsters, Mastodon, fallback RSS de Reddit) |
| sgmllib3k | `1.0.0` | Dependencia de feedparser. **Ojo:** solo existe como sdist en PyPI (el módulo se llama `sgmllib`); por eso el instalador NO puede usar `--only-binary=:all:` salvo que se precompilen wheels |
| requests | `2.34.2` | HTTP (ingesta, GDELT, Telegram, descarga de recursos) |
| urllib3 | `2.8.0` | Transitiva de requests, pinneada. **Subida desde 2.7.0 el 2026-10-12** por 3 CVE corregidos en 2.8.0 (ver el Anexo B) |
| idna | `3.18` | Transitiva de requests |
| charset-normalizer | `3.4.9` | Transitiva de requests |
| certifi | `2026.6.17` | Transitiva de requests |
| fasttext-predict | `0.9.2.4` | Detección de idioma (176 idiomas, modelo `lid.176.ftz`). Se importa como módulo `fasttext` |
| lingua-language-detector | `2.2.0` | Fallback de idioma cuando fastText duda (conjunto congelado de 8 idiomas; ver §3, «Qué analiza de verdad»). **Opcional** |
| vaderSentiment | `3.3.2` | Componente VADER de la emoción en inglés |

[Evidencia: INSP de `requirements.txt`; barrido de vulnerabilidades OSV del 2026-10-12: todos los pins limpios — ver el Anexo C.]

**Sin dependencias pesadas:** no se usan numpy, scipy ni datasketch (MinHash está implantado a mano con la stdlib; decisión registrada D-039: datasketch 1.6.5 importa scipy a nivel de módulo). Los imports de fasttext/lingua/vader/requests son **perezosos**: sin ellos el paquete importa igual y degrada.

### 1.3 Instalación paso a paso

#### 1.3.1 Windows (vía prevista; verificada en dos pruebas reales de Windows 11, 2026-10-15)

El paquete incluye `instalar.bat`, diseñado para que cada paso verifique o aborte con mensaje claro, sin requerir administrador:

0. Prerrequisito: **Python 3.12** desde python.org, marcando «py launcher» al instalar.
1. Copia **TODA la carpeta** (no solo `sibila\`: hacen falta también `resumen.py`, los `.bat`, `requirements.txt`, `tools\` y las plantillas de configuración) a una **ruta corta y fuera de OneDrive/Documentos** (recomendado: `C:\sibila`).
2. **Exclusión de antivirus (manual, importante):** Seguridad de Windows → Protección antivirus → Exclusiones → añadir las carpetas `C:\sibila\datos` y `C:\sibila\logs`. Sin esto, Defender puede bloquear la base de datos a mitad de escritura (riesgo nº 1 identificado para Windows).
3. Doble clic en **`instalar.bat`**. No sigas hasta ver `=== Instalacion completa ===`.

El instalador ejecuta, en orden: materializa `config.toml`/`fuentes.toml` si faltan (no pisa los existentes) → crea `.venv` → instala `requirements.txt` → descarga los recursos de datos (§1.4) → genera `config.local.toml` con una `hmac_key` nueva (idempotente, con permisos restringidos vía `icacls`) → crea la base (`sibila init`) → exige la puerta `check: VERDE` → muestra el informe de `sibila doctor` → verifica la integridad del paquete **en destino** (`sibila paquete verificar`) → programa las dos tareas diarias (§1.6).

[Evidencia: INSP de `instalar.bat` + dos pruebas reales en Windows 11 (2026-10-15): la segunda superó W1–W14 con los seis defectos de la primera corregidos. Queda pendiente un ciclo natural de 24 h — ver el Anexo D.]

**Opciones del instalador:**
- **Sin lingua** (ahorra ~300 MB): antes de instalar, en esa misma consola, `set SIBILA_SIN_LINGUA=1` y luego `instalar.bat`. Consecuencia documentada: los documentos cuyo idioma sea dudoso para fastText quedan sin idioma (no se estudian); `doctor` lo recordará como AVISO «(skip explícito)» y escribe el centinela `<data_dir>/recursos/SIN_LINGUA`.
- **Sin red durante la instalación:** la instalación **no se interrumpe**; el programa queda en modo degradado (sin idioma ni emoción) hasta que se ejecute `tools\descargar_recursos.py` con red.

#### 1.3.2 Linux (entorno de desarrollo, verificado)

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python tools/descargar_recursos.py   # recursos de datos (§1.4)
.venv/bin/python -m sibila init                # crea BD y carpetas (idempotente)
.venv/bin/python -m sibila check               # debe decir "check: VERDE"
.venv/bin/python -m sibila doctor              # informe post-instalación
```

`init` es idempotente por construcción (todo el DDL usa `IF NOT EXISTS`) y jamás borra ni recrea una base existente.

### 1.4 Recursos de datos (no van por pip)

Dos familias, ambas descargadas por `tools/descargar_recursos.py` a `<data_dir>/recursos/` (por defecto `datos/recursos/`):

#### 1.4.1 Modelo de idioma fastText `lid.176.ftz`

- **Origen oficial:** `https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz` (Facebook AI Research, licencia MIT).
- **Tamaño y SHA-256 fijados en el código** (`tools/descargar_recursos.py`): 938 013 bytes, SHA-256
  `8f3472cfe8738a7b6099e8e999c3cbfae0dcd15696aac7d7738a8039db603e83`
  (verificado por doble descarga del URL oficial, decisión D-030). [EJEC 2026-10-12: este fichero se descargó y verificó realmente; es el único recurso confirmado contra su fuente oficial.]

#### 1.4.2 Los cuatro léxicos NRC (emoción)

| Fichero (normalizado) | Origen | SHA-256 pinneado en `sibila/procesado/emocion.py` |
|---|---|---|
| `nrc_vad_en.txt` | NRC-VAD Lexicon **v2.1** (unigrams EN, scores ya en [−1,1]) | `71518ac0e3cea299b43714190b4fc3ec55acf4302eb04b9c36d148aaffbe9d81` |
| `nrc_vad_es.txt` | NRC-VAD Lexicon **v1** (hoja Spanish; transpuesta a palabra_es⇥v⇥a, scores reescalados a [−1,1] al cargar) | `0ac2f639f8b222ef5bce14dac26bb6dd34217d80a447d6443c2a21fa77da75f7` |
| `nrc_emociones_en.txt` | NRC Emotion Lexicon v0.92 (wordlevel EN; filas positive/negative eliminadas) | `0b1ce8ec1297f523eee882fd3973cca394c0b20ff54c3beb0dbd952efe314a81` |
| `nrc_emociones_es.txt` | NRC Emotion Lexicon (hoja Spanish; transpuesta a palabra_es⇥emoción_en⇥1) | `60124be34075390015aea04eb86574a4ae84f943f5fb5c9a196ec63a79abe46e` |

- **Licencia:** NRC-VAD y NRC Emotion Lexicon © National Research Council Canada — uso libre **no comercial** (investigación/educación). Por eso **no se redistribuyen**: se descargan en la instalación desde `https://saifmohammad.com/WebDocs/Lexicons/…`. [INSP del docstring de `tools/descargar_recursos.py`.]
- **Estado real al 2026-10-15:** la descarga automática funciona (el HTTP 406 era el rechazo del `User-Agent` de python-requests; resuelto en D-077 con cabeceras de navegador) y **los 4 SHA-256 pinneados quedaron verificados contra descargas reales** ese mismo día. La descarga manual con navegador queda como ruta alternativa documentada. Detalle y consecuencias en el Anexo D.

#### 1.4.3 Cómo verificar los hashes a mano

```bash
# Linux
sha256sum datos/recursos/lid.176.ftz
# Windows (PowerShell)
Get-FileHash .\datos\recursos\lid.176.ftz -Algorithm SHA256
```

y comparar con los valores de arriba. El programa lo hace por ti: `sibila doctor` verifica el SHA-256 de los 5 recursos en cada ejecución (§1.5).

#### 1.4.4 Qué pasa si faltan: modo degradado (documentado en código)

- **Sin `lid.176.ftz` o sin fasttext:** `lang` queda `NULL` en todos los documentos → no hay analítica lingüística (los excluidos por idioma se contabilizan). El pipeline diario `corre` detecta este caso y termina en **ROJO (exit 1)** con remediación explícita — no da un falso éxito (reparación ALTO-1, 2026-10-12). Un día **sin documentos** sigue siendo éxito legítimo.
- **Sin los NRC:** emoción desactivada (los agregados `emo_stats` del día no se recalculan ni se borran en modo degradado: las series previas se conservan). La remediación es `sibila procesa --todo` tras colocar los recursos.
- **Sin lingua:** el fallback de idioma dudoso se desactiva (AVISO de `doctor`).
- **Sin VADER:** la emoción EN se desactiva (`vector()` devuelve None para `en`; nunca se inventa un promedio a medias); ES no se ve afectada.

En todos los casos `procesa` registra la métrica `procesa.modo_degradado` y avisa; nada falla en silencio.

### 1.5 Verificación post-instalación

#### `sibila check` — la puerta

Verificación verde/rojo de la base y el entorno. Todos los chequeos corren aunque alguno falle (informe completo); **no repara nada** (reparar es de `init`). Comprueba: intérprete Python · recursos del paquete accesibles · configuración cargable · `data_dir` existente y escribible (sonda) y espacio libre · la base abre · `PRAGMA integrity_check` · pragmas `journal_mode=wal`, `foreign_keys=1`, `busy_timeout=30000` · schema v1 conforme (12 tablas, columnas, literales de dominio e índices) · `echo_flags` vacía (contrato de Fase 1) · git y ots (AVISO, nunca fallo) · el log a fichero crece de verdad. Resultado: `check: VERDE` (exit 0) o `check: ROJO` (exit 1). [INSP `sibila/cli.py::_cmd_check`.]

#### `sibila doctor` — el informe de salud del paquete

Distinto de `check` (que es la puerta del instalador): `doctor` audita la instalación completa en modo **solo lectura** (conexión SQLite `mode=ro`; la única escritura es una sonda temporal en `data_dir`):

| Comprobación | Falla si | Avisa si |
|---|---|---|
| D1 · BD existe, abre, schema íntegro (12 tablas) | falta/rota | — |
| D2 · dependencias importables (`feedparser`, `requests`, `sgmllib`, `fasttext`, `vaderSentiment`; sondeo sin importar lo pesado) | falta alguna | `lingua` ausente («fallback desactivado»; «(skip explícito)» si existe el centinela `SIN_LINGUA`) |
| D3 · recursos con SHA-256 (`lid.176.ftz` + 4 NRC) | hash no coincide, o hashes no fijados en código | recurso ausente («modo degradado; corre tools\descargar_recursos.py») |
| D4 · `data_dir` escribible | no escribible | — |
| D5 · git y ots | — (nunca fallo) | ausentes («anclaje pendiente») |
| D6 · `config.local.toml` con `hmac_key` | — (nunca fallo) | ausente («author_hash quedará NULL») |

Resultado: `doctor: SANO (n avisos)` (exit 0; los avisos no penalizan) o `doctor: ROTO (n fallos)` (exit 1). [INSP `sibila/doctor.py`.]

**Limitación conocida (MED-3, abierta):** `doctor` importa el SHA-256 de `lid.176.ftz` desde `tools/`, que no es un paquete instalable; ejecutado desde un directorio de trabajo distinto de la raíz del proyecto puede dar un FALLO espurio de verificabilidad. Los `.bat` lo enmascaran haciendo `cd` antes.

### 1.6 Windows: tareas programadas

El instalador programa **dos tareas diarias** (plantillas `tarea_ingesta.xml` y `tarea_diaria.xml`; `instalar.bat` sustituye los placeholders `{SIBILA_RAIZ}` y `{START_BOUNDARY}` con PowerShell en línea y escribe el XML final en UTF-8 **sin BOM**, que `schtasks` rechazaría con BOM; la misma lógica, factorizada y testeable, vive en `tools/preparar_tarea.py`):

| Tarea | Hora (local) | Script | Qué hace | Límite |
|---|---|---|---|---|
| **SibilaIngesta** | 07:00 | `ingesta_diaria.bat` | Solo `sibila ingesta --en-vivo`. La recolección es lo irrecuperable (si un día falta, ese día se pierde); por eso va sola y primero | PT1H |
| **SibilaDiario** | 07:45 | `pipeline_diario.bat` | Pipeline completo: ingesta → procesa → detecta → registro sellar → registro anclar → **registro verificar** (la integridad se chequea a diario) → alerta enviar → alerta digest | PT2H |

Ambas: `InteractiveToken`, `LeastPrivilege`, `IgnoreNew` (no solapa instancias), `StartWhenAvailable` (si el PC está apagado a esa hora, corren al encender), reintento ante fallo 3 × 5 min. La doble ingesta (07:00 + 07:45) está justificada en D-048: la recolección es lo irrecuperable; lo demás es reejecutable. Logs: `logs\ingesta_tarea.log` y `logs\pipeline_diario.log`. `pipeline_diario.bat` sale con exit 1 si un eslabón falla (el `RestartOnFailure` de la tarea lo reintenta); el digest sin canales configurados da exit 0 con AVISO (no es fallo). [INSP de `tarea_*.xml`, `*_diaria.bat`, `pipeline_diario.bat`.]

**Advertencia honesta:** estos ficheros fueron revisados estáticamente (CRLF correcto en los `.bat`, placeholders) y **ya ejecutados en dos pruebas reales de Windows 11** (2026-10-15): la segunda superó W1–W14, incluida la importación de las tareas en UTF-16 por `schtasks`. Lo único pendiente es un ciclo natural de 24 h (ver el Anexo D).

**Desinstalación:** `schtasks /delete /tn SibilaIngesta /f` y `schtasks /delete /tn SibilaDiario /f`, y borrar la carpeta.

### 1.7 Problemas habituales de instalación

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `check` ROJO por schema | Base preexistente mal formada | `init` nunca recrea: revisa el mensaje en español; en última instancia mueve la BD y re-inicia (perdiendo los datos) |
| `doctor` dice «dep NO importable» | Dependencias sin instalar | Re-ejecuta `instalar.bat` (reinstala dependencias) |
| `doctor` dice «recurso ausente» | Descarga de recursos falló (sin red o bloqueo del servidor) | Con red: `.venv\Scripts\python.exe tools\descargar_recursos.py` (lleva cabeceras de navegador desde D-077). Alternativa: descarga manual (§1.4.2) |
| «SHA-256 no coincide» en un recurso | Descarga corrupta o fichero manipulado | Borra el fichero y re-descarga (el descargador NUNCA pisa en silencio un fichero con hash malo) |
| `sgmllib3k` no instala con `--only-binary` | Solo existe como sdist | Instala sin `--only-binary`, o precompila wheels (`pip wheel -r requirements.txt`) |
| «database is locked» en operación | Otra ventana/proceso del programa abierto | Cierra otras ventanas y reintenta (hay `busy_timeout` de 30 s); si persiste, reinicia el PC |

---

## 2 · Configuración

**Fecha del documento:** 2026-10-12 · **Fuente:** inspección directa de `sibila/config.py`, `config.toml`, `config.local.toml.example` y `fuentes.toml`.

### 2.1 Los tres niveles (y su precedencia)

```
defaults del código  <  config.toml  <  config.local.toml  <  variables SIBILA_*
```

(Esta cadena está literalmente en la cabecera de `config.py`.)

| Capa | Dónde | Para qué | ¿Versionable? |
|---|---|---|---|
| Defaults | En el código (`DEFAULTS`): `data_dir="datos"`, `log_level="INFO"` | Que el programa arranque sin ningún fichero | — |
| `config.toml` | Raíz del proyecto | Ajustes **no secretos** (rutas, nivel de log) | **Sí** (y por eso tiene vetada la sección `[secretos]`) |
| `config.local.toml` | Raíz del proyecto | **Secretos** (hmac_key, tokens, SMTP) | **No**: está en `.gitignore` y excluido del manifiesto del paquete |
| Entorno `SIBILA_*` | Variables de entorno | Pisan cualquier fichero (útil en tareas/CI) | — |

- `config.toml` ausente → **aviso** («usando valores por defecto»), no error.
- `config.local.toml` ausente → **caso normal** (los secretos son opt-in): silencio total.
- Las **rutas relativas** se anclan a la **raíz del proyecto**, nunca al directorio de trabajo actual (trampa T3); una variable de entorno **vacía se ignora** (una cadena vacía anclaría rutas al root — trampa M6).

### 2.2 Claves válidas (whitelist cerrada)

La configuración valida contra una **lista blanca** para cazar erratas silenciosas: cualquier sección o clave no listada es un **error** al arrancar. Solo existen estas:

#### Sección `[general]`
| Clave | Tipo | Notas |
|---|---|---|
| `data_dir` | texto (ruta) | Carpeta de datos; defecto `datos` |
| `db_path` | texto (ruta) | Ruta de la base SQLite; si no se da, se deriva de `data_dir` |
| `log_level` | texto | Debe ser uno de los niveles permitidos (`DEBUG`, `INFO`, …) |

#### Sección `[secretos]` (solo en `config.local.toml` o entorno)
| Clave | Tipo | Notas |
|---|---|---|
| `hmac_key` | texto | Clave HMAC del `author_hash` (anonimización de autores). Sin ella, `author_hash` queda `NULL` |
| `telegram_token` | texto | Token del bot de Telegram |
| `smtp_password` | texto | Contraseña SMTP |
| `telegram_chat` | texto | **(nueva)** chat/canal destino de Telegram |
| `smtp_host` | texto | **(nueva)** servidor SMTP |
| `smtp_usuario` | texto | **(nueva)** usuario SMTP |
| `smtp_puerto` | **entero 1–65535** | **(nueva)** puerto SMTP (validación estricta, §2.4) |
| `smtp_destino` | texto | **(nueva)** destinatario del correo |

Las **5 claves nuevas** (`telegram_chat`, `smtp_host`, `smtp_usuario`, `smtp_puerto`, `smtp_destino`) se añadieron en la reparación **CRIT-2** (2026-10-12): antes las claves de alerta no estaban reconocidas y las alertas no podían configurarse sin error de «clave desconocida».

#### Variables de entorno equivalentes (las 11)
`SIBILA_DATA_DIR`, `SIBILA_DB_PATH`, `SIBILA_LOG_LEVEL`, `SIBILA_HMAC_KEY`, `SIBILA_TELEGRAM_TOKEN`, `SIBILA_SMTP_PASSWORD`, `SIBILA_TELEGRAM_CHAT`, `SIBILA_SMTP_HOST`, `SIBILA_SMTP_USUARIO`, `SIBILA_SMTP_PORT`, `SIBILA_SMTP_DESTINO`.

### 2.3 Regla de oro: secretos solo en local o entorno

- `config.toml` (el fichero versionable) **no puede contener `[secretos]`**: si la tiene, `load_config` lanza `ConfigError` explicando que los secretos van en `config.local.toml` o variables `SIBILA_*`.
- Los secretos se guardan en un `MappingProxyType` con `repr=False`: **nunca aparecen en el repr ni en logs** (trampa T4). El instalador además endurece permisos de `config.local.toml` (`icacls` en Windows).
- El manifiesto del paquete (`sibila paquete generar`) **excluye** `config.local.toml*` (excepto el `.example`) para que ningún secreto se distribuya.

### 2.4 `smtp_puerto`: validación estricta

Caso especial documentado en el código:
- En TOML se escribe como entero natural: `smtp_puerto = 587`.
- Una variable de entorno llega como **texto**; si es ASCII de solo dígitos se **normaliza a entero**.
- Se rechazan: booleanos (`true`), no-enteros, y cualquier valor fuera de **1–65535**, con mensajes explícitos (p. ej. `'secretos.smtp_puerto' fuera de rango (1-65535): 70000`).

### 2.5 Errores habituales y su significado

| Error / síntoma | Causa | Qué hacer |
|---|---|---|
| `empieza con BOM UTF-8; guárdalo como UTF-8 sin BOM` | El Bloc de notas (u otro editor) guardó el `.toml` con BOM. `tomllib` solo diría el críptico «Invalid statement», así que el código lo detecta y lo dice claro | Guardar como **UTF-8 sin BOM** |
| `TOML inválido …` (`TOMLDecodeError`) | Sintaxis TOML rota (comillas, corchetes, `=` mal puestos) | Revisar la línea que indica el error |
| `sección desconocida [x]` / `clave desconocida 'x.y'` | Errata o clave no soportada | Corregir el nombre contra la whitelist de §2.2 |
| `config.toml NO puede tener [secretos]` | Secretos en el fichero versionable | Moverlos a `config.local.toml` o a variables `SIBILA_*` |
| `'secretos.smtp_puerto' debe ser un entero` / `fuera de rango` | Puerto mal tipado o fuera de 1–65535 | Poner un entero válido (p. ej. `587`) |
| `'general.log_level' debe ser una de [...]` | Nivel de log no reconocido | Usar un nivel válido (`INFO`, etc.) |
| Una variable `SIBILA_*` «no hace efecto» | Está definida pero **vacía** | Las cadenas vacías se ignoran a propósito; definirla con valor |

### 2.6 Fuentes (`fuentes.toml`, aparte de la config)

Las fuentes **no** viven en `config.toml` sino en `fuentes.toml` (la CLI permite apuntar a otro con `ingesta --fuentes RUTA`). Hay **3 habilitadas por defecto**, anglófonas: Reddit r/worldnews, Lobsters y Mastodon (#ai). El conector de 4chan existe y está probado, pero su configuración (`/pol/`) **no viene habilitada por defecto** desde D-075 (señal ruidosa, riesgo reputacional, valor nunca validado); la fuente sigue registrada en la semilla de la base de datos y se puede activar editando `fuentes.toml`. Cada fuente puede marcarse habilitada/deshabilitada; `ingesta` solo recorre las habilitadas. La política de acceso (ritmo con descansos y backoff ante 429/5xx, `User-Agent` propio) está en `sibila/conectores/base.py`. **No hay política robots.txt implantada** — queda registrado como límite conocido.

---

## 3 · Uso de la CLI

**Fecha del documento:** 2026-10-12 · **Fuente:** inspección directa de `sibila/cli.py` y los módulos que invoca. Toda la sintaxis descrita aquí existe tal cual en el código.

La CLI se invoca como `python -m sibila <comando> [opciones]` (en Windows con la venv: `.venv\Scripts\python.exe -m sibila …`). Los `.bat` incluidos ya hacen `cd` a la raíz del proyecto antes de invocarla.

**Códigos de salida (contrato del propio `cli.py`):**

| Código | Significado |
|---|---|
| 0 | OK |
| 1 | Fallo |
| 2 | Uso incorrecto (argparse) |
| 3 | «No implantado» (reservado; ya no hay comandos que lo devuelvan — incidencia menor BAJO-3) |

Las fechas son siempre `YYYY-MM-DD` en **UTC** (todo el programa trabaja en UTC; es regla de oro sin excepciones desde D-077: los rangos por defecto del CLI también usan la fecha UTC). «Ayer» significa ayer UTC, y los días no sellables aún (hoy) se excluyen de la detección y el sellado.

---

### Comandos de ciclo de vida

### `sibila init`
Crea la base de datos y la estructura de carpetas. **Idempotente por construcción** (todo el DDL es `IF NOT EXISTS`) y jamás borra ni recrea una base existente. Sin opciones. Es lo primero tras instalar.

#### `sibila check`
Puerta verde/rojo: «¿puedo trabajar?». Comprueba intérprete, schema completo (las 12 tablas), pragmas SQLite, integridad, git/ots, log a fichero, etc. **No repara nada** (eso es `init`). Exit 0 = VERDE, 1 = ROJO. Detalle en §1.5 de este manual.

#### `sibila doctor`
Informe de salud post-instalación (deps, recursos con SHA-256, `data_dir` escribible, git/ots, `config.local.toml`). Solo lectura. Detalle en §1.5 de este manual.

---

### `sibila ingesta` — una pasada por las fuentes

```
sibila ingesta [--fuente NOMBRE]... [--fuentes RUTA] [--fixture RUTA]
               [--en-vivo] [--sin-db] [--limite N]
```

| Opción | Efecto |
|---|---|
| `--fuente NOMBRE` | Solo esa fuente (repetible). Por defecto, todas las **habilitadas** de `fuentes.toml` |
| `--fuentes RUTA` | Fichero `fuentes.toml` alternativo (por defecto el del paquete) |
| `--fixture RUTA` | Parsea un fichero local (RSS/JSONL) como una sola fuente; **exige `--fuente`** |
| `--en-vivo` | Fuerza descarga por red aunque haya fixture (la ingesta real es en vivo) |
| `--sin-db` | Solo parsea y muestra: no persiste ni mueve cursores (modo sondeo) |
| `--limite N` | Máximo de documentos por fuente |

**Qué produce:** documentos en la tabla `documents` (con `author_hash` HMAC — nunca el autor en claro), actualización de cursores por fuente, dedup en el punto de ingesta (la misma URL —`url_hash`— o el mismo contenido —`content_hash`— no entra dos veces; la segunda pasada cuenta «repetidos», no duplica filas). **La red solo se toca aquí (y en alertas/GDELT):** sin `--en-vivo`/fixture no hay tráfico. **Si una fuente falla** (excepción del conector, p. ej. red caída), se registra `[FALLO]` para esa fuente, el resto continúa y el comando **sale con exit 1** (`pipeline_diario.bat` lo trata como fallo de la cadena); los errores de documentos individuales se saltan con AVISO sin alterar el exit.

### `sibila procesa` — pipeline lingüístico

```
sibila procesa [--lote N] [--limite N] [--dia YYYY-MM-DD] [--todo]
```

| Opción | Efecto |
|---|---|
| `--lote N` | Documentos por lote/**transacción** (defecto 200). Regla de oro: red fuera de las transacciones y lotes atómicos |
| `--limite N` | Máximo de documentos (depuración; el resto queda pendiente) |
| `--dia` | Restringe la selección a un día |
| `--todo` | **Re-procesa todo el rango**, no solo los pendientes |

**Qué hace por documento** (en orden): limpieza → detección de idioma → dedup → calidad → heurística de bots → emoción → n-gramas. Solo los documentos **ES/EN** llegan al análisis completo (stopwords y léxicos NRC existen solo en ES/EN; ver la sección «Qué analiza de verdad», más abajo). Al terminar, recalcula los agregados diarios (`term_stats`, `emo_stats`, `ops_metrics`). Si faltan recursos (modelo de idioma, NRC, VADER) trabaja en **modo degradado**, lo registra en `procesa.modo_degradado` y avisa (no falla en silencio; el comportamiento consecuente de `corre` se describe abajo).

### `sibila detecta` — detección temporal

```
sibila detecta [--dia D] [--desde D] [--hasta D] [--todo]
```

- `--hasta` por defecto es **ayer UTC** (requiere `--desde`); `--todo` = desde el primer día con stats hasta ayer.
- Calcula sobre las series diarias: **z_r** (z-score robusto con mediana/MAD), **CUSUM** y **Mann-Kendall**; escribe `term_stats.z_r` y la tabla `signals`. Un día sin historia suficiente queda «inmaduro» (días de madurez: 28) y no genera señales.
- Las señales son la materia prima que luego se **sella** como predicciones.

### `sibila registro` — el registro sellado de predicciones

Subcomandos:

| Subcomando | Qué hace |
|---|---|
| `sellar [--dia D | --desde D [--hasta D]]` | Convierte las señales del período en predicciones **inmutables**: líneas JSONL encadenadas por hash (cadena de custodia local) + filas en la tabla `predictions` |
| `verificar` | Verifica la cadena JSONL **y** su cruce con la tabla `predictions`. Exit 0/1. En el pipeline diario corre a diario |
| `anclar` | Ancla el estado del registro en **git** (commit de manifiesto) y, si existe `ots` (OpenTimestamps), pide sello de tiempo externo. Sin git/ots: queda «pendiente» con AVISO, **nunca es fallo**. Sin señales selladas aún (registro vacío): AVISO «sin señales selladas que anclar», exit 0 (D-078) |
| `listar [--pendientes]` | Lista la tabla `predictions` (sin escritura); `--pendientes` = solo las pendientes |

### `sibila informe` — informe del período

```
sibila informe [--semana AAAA-Www | --dia D | --desde D --hasta D]
               [--salida RUTA] [--formato md|json|csv] [--actualizar-gdelt]
```

- Por defecto: la **semana ISO** que termina ayer. `--formato` admite `md` (defecto), `json` y `csv` (vectores congelados). `--salida` escribe a fichero (defecto: stdout). Lectura siempre en **modo solo-lectura**.
- `--actualizar-gdelt` es una **subacción escritora aparte**: descarga la referencia GDELT (red) y luego el informe puede contrastar contra ella. Sin referencia descargada, el contraste sale como `n/d` (vacío = no disponible, nunca un dato inventado).

### `sibila alerta` — envío por red

Subcomandos:

| Subcomando | Qué hace |
|---|---|
| `enviar [--dia D | --desde D [--hasta D]]` | Envía las alertas del período (defecto: **ayer**) por los canales configurados (Telegram/SMTP). Sin canales configurados no envía nada (y `digest` lo reporta como AVISO, exit 0) |
| `probar` | Envía un mensaje de prueba (TP-N7) para validar credenciales |
| `digest [--semana AAAA-Www]` | Digest semanal de alertas (canal `digest`; semana por defecto: la de ayer) |

Las claves/canales viven **solo** en `config.local.toml` o en variables `SIBILA_*` (ver el §2 de este manual). Estos son los únicos comandos, junto a `ingesta --en-vivo` e `informe --actualizar-gdelt`, que generan tráfico de red.

### `sibila corre` — pipeline diario completo

```
sibila corre [--dia D | --desde D [--hasta D]] [--fuente NOMBRE]
             [--fixture FEED | --fixture-dir DIR] [--digest] [--con-informe]
```

Encadena, por día: **ingesta → procesa → detecta → sellar → alerta** (y opcionalmente digest semanal e informe). Los `--fixture*` permiten ensayos E2E sin red: `--fixture` exige `--dia` y `--fuente`; `--fixture-dir` (un `{dia}.xml` por día) exige `--desde` y `--fuente`.

#### Comportamiento anti falso-éxito (reparación ALTO-1, 2026-10-12)

Regla: **`corre` solo da VERDE si el día produjo evidencia procesable.**

- Día con documentos cuyo idioma quedó **todo `NULL`** (p. ej. falta el modelo fastText o el detector no carga): `corre` termina en **ROJO (exit 1)** con error explícito — antes de la reparación esto daba un falso VERDE.
- **Día sin documentos**: sigue siendo éxito legítimo (nada que procesar no es un fallo).
- **Remediación documentada:** colocar/reparar los recursos (`tools/descargar_recursos.py`), ejecutar **`sibila procesa --todo`** para reprocesar el rango, y repetir `corre` para ese día.

### `sibila paquete` — integridad del propio paquete

| Subcomando | Qué hace |
|---|---|
| `generar` | Regenera `MANIFIESTO.sha256.json` (SHA-256 de los 133 ficheros del paquete, con exclusiones: datos, logs, BD, `__pycache__`, `.pytest_cache`, `config.local.toml`…). **Solo al construir el paquete** |
| `verificar` | Verifica la integridad del árbol contra el manifiesto (exit 0/1). `instalar.bat` lo corre en destino |

Detalles de conservación y restauración en el Anexo E.

---

### Qué analiza de verdad (límites honestos)

- **Detección de idioma:** 176 idiomas vía fastText `lid.176`; fallback `lingua` (8 idiomas: ES, EN, PT, FR, DE, IT, CA, EU — GL **no existe** en lingua 2.2.0, hallazgo reciente).
- **Análisis lingüístico completo: solo ES y EN** (stopwords y léxicos NRC solo ES/EN; VADER solo EN). El resto de idiomas queda detectado y clasificado, pero fuera del análisis de emoción/n-gramas.
- **Las 3 fuentes habilitadas por defecto son anglófonas** (Reddit r/worldnews, Lobsters, Mastodon etiqueta #ai; 4chan /pol/ no viene habilitada por defecto, D-075), así que en la práctica el volumen útil es EN.
- La **capacidad predictiva no está validada**: faltan ~12 meses de datos reales acumulados. El sistema registra predicciones selladas para poder evaluarlas después, no para afirmar hoy que acierta.

---

## Anexo A · Arquitectura

**Fecha del documento:** 2026-10-12 · **Fuente:** inspección directa del árbol `sibila/`, `sibila/schema.sql`, `sibila/db.py` y los docstrings de cada módulo.

### A.1 Qué es SIBILA

Programa **CLI de lingüística aplicada a la investigación**. La idea: el lenguaje emocional de foros públicos «tensa» antes de ciertos acontecimientos. El sistema ingiere fuentes públicas, procesa el lenguaje, detecta cambios temporales en las series, **sella predicciones** en un registro auditable y emite alertas e informes. Base **SQLite**. Sin red en tests (fixtures); la red solo se toca en ingesta real, alertas y la referencia GDELT.

> Advertencia central: la **capacidad predictiva no está validada**. El sistema está construido para *registrar predicciones selladas y evaluarlas después con honestidad* (resolución ciega), no para afirmar hoy que acierta. Ver el Anexo C.

### A.2 Flujo de datos

```
fuentes públicas (RSS/HTML)
   │  sibila/conectores/{reddit,lobsters,mastodon,cuatrochan}.py   (RED, solo ingesta)
   ▼
documents (crudo)  ── cursor opaco por fuente en conector_cursor (misma TX que los datos)
   │  sibila/procesa.py → sibila/procesado/*
   │    limpieza → idioma → dedup → calidad → bots → emoción → n-gramas
   ▼
agregados diarios: terms / term_stats / emo_stats   (+ ops_metrics)
   │  sibila/detecta.py → sibila/deteccion/{series,cusum,pendiente,motor}.py
   ▼
signals  (z_r, CUSUM, Mann-Kendall)
   │  sibila/sella.py → sibila/registro/{canonico,derivar,sellar,verificar}.py
   ▼
predictions + cadena JSONL sellada ── anclaje git/ots (sibila/anclaje.py)
   │
   ├─→ sibila/alerta.py → alertas/{reglas,cooldown}.py   (RED: Telegram/SMTP)
   └─→ sibila/informe_datos.py → informe/render.py  (+ gdelt.py, RED bajo demanda)
```

### A.3 Estructura de directorios y módulos

| Módulo | Responsabilidad |
|---|---|
| `cli.py` | Punto de entrada y parsers de todos los comandos (ver el §3 de este manual) |
| `config.py` | Carga/valida configuración (precedencia, whitelist, secretos) |
| `db.py` | Conexión, `init_db`, `verify_schema`, `tx`, `now_iso`, `integrity_ok` |
| `doctor.py` | Auditoría de instalación D1–D6 (solo lectura) |
| `corre.py` | Orquestador del pipeline diario + anti falso-éxito (ALTO-1) |
| `ingesta.py` + `conectores/` | Ingesta por fuente; `conectores/base.py` define el contrato `RawDoc` y la política común; un módulo por fuente (`reddit`, `lobsters`, `mastodon`, `cuatrochan`) |
| `procesa.py` + `procesado/` | Pipeline lingüístico: `limpieza`, `idioma` (fastText+lingua), `dedup` (simhash/MinHash), `calidad`, `bot_heur`, `emocion` (NRC/VADER), `ngramas`, `stopwords` |
| `detecta.py` + `deteccion/` | Series diarias y detectores: `series`, `cusum`, `pendiente` (Mann-Kendall), `motor` |
| `sella.py` + `registro/` | Registro sellado: `canonico` (`canonical_json` CONGELADO), `derivar`, `sellar`, `verificar` |
| `anclaje.py` | Anclaje git (+ OpenTimestamps si existe) |
| `alerta.py` + `alertas/` | `reglas` (vigilancia/alerta/alarma) y `cooldown` por tema |
| `informe_datos.py` + `informe/render.py` | Informe del período; `INFORME_VERSION` en render |
| `gdelt.py` | Referencia GDELT (vacío = n/d, jamás 0 persistido) |
| `paquete.py` | Manifiesto SHA-256 del paquete (generar/verificar) |

### A.4 Esquema SQLite — las 12 tablas

Schema v1 (`sibila/schema.sql`), creado **íntegramente con `IF NOT EXISTS`** (init idempotente) y versionado con `PRAGMA user_version`. El DDL hace cumplir en la base las reglas que la spec solo enuncia en prosa (refuerzos R1–R5).

| # | Tabla | Propósito / notas de contrato |
|---|---|---|
| 1 | `sources` | Fuentes. `stratum` ∈ {normal, vidente, control} (el «vidente» es para anti-eco, Fase 2) |
| 2 | `documents` | Documentos. `author_hash` (HMAC, nunca el autor en claro); `simhash` hex(16) minúsculas con `CHECK` (cierra en la base el bug int64, trampa T1); `dia` con forma `YYYY-MM-DD`; invariante «si la fecha es real, existe» en DDL |
| 3 | `terms` | Términos y clusters. `type` ∈ {term, bigram, trigram, cluster, emocion}; `cluster_key` da identidad persistente al cluster |
| 4 | `term_stats` | Series diarias por término (baseline y `z_r`); `UNIQUE(day, term_id)` |
| 5 | `emo_stats` | Series diarias de emoción por idioma (NRC-VAD reescalado `v' = 2v − 1`) |
| 6 | `signals` | Señales de tensión. `metric` ∈ {z_r, cusum, mk}; `status` ∈ {nuevo, confirmado, descartado, reactivo, inmaduro}; `UNIQUE(day, target_type, target_id, metric)` permite **UPSERT idempotente** |
| 7 | `predictions` | Registro sellado **append-only** con cadena de hash (`hash`, `prev_hash`); `umbral` como string decimal; `ventana` ISO-8601; `estado` ∈ {pendiente, parcial, cumplida, fallada, expirada}; `resolucion_ciega` |
| 8 | `echo_flags` | Anti-eco (Fase 2): **existe VACÍA en Fase 1**, contrato congelado. `tipo` ∈ {sincronia, meme, cita_profecia, bot_ia}; `score` ∈ [0,1] |
| 9 | `alert_log` | Alertas enviadas (cooldown por tema). `nivel` ∈ {vigilancia, alerta, alarma} |
| 10 | `gdelt_ref` | Referencia GDELT por tema/día. **Vacío = n/d; jamás un 0 persistido** (se hace cumplir en el módulo, no solo en prosa) |
| 11 | `ops_metrics` | Métricas operativas (log append, sin PK) |
| 12 | `conector_cursor` | Cursores opacos de ingesta por fuente, **en la BD, jamás en ficheros**; se guardan en la misma transacción que los documentos para que cursor y datos nunca diverjan |

Índices explícitos para los patrones de lectura congelados (día, fuente, término, estado de señal, etc.).

### A.5 Reglas de oro del código

**Persistencia y transacciones (`db.py`):**
- `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=30000` ms, `synchronous=NORMAL`.
- `tx()` = transacción corta con **`BEGIN IMMEDIATE`** (toma el lock de escritura al entrar).
- **Red fuera de las transacciones** y lotes atómicos (procesa en lotes de 200).
- `PRAGMA user_version` no admite bind params: se escribe como literal entero desde la constante (trampa T12).
- `init` jamás borra ni recrea la base: la evidencia sellada es intocable.

**Tiempo y serialización:**
- `now_iso()` es el **único punto** donde se obtiene la hora (todo UTC; desde D-077 los rangos por defecto del CLI también derivan de él — MED-1 resuelta).
- `canonical_json` (`registro/canonico.py`) está **CONGELADO**: define la serialización canónica de la que dependen todos los hashes; no se negocia. El registro se escribe en binario `ab` con `canonical_json(linea)+b"\n"` (jamás CRLF, trampa 3).

**Versiones de algoritmo (cambiar el algoritmo = subir la versión = re-procesado):**

| Constante | Valor | Gobierna |
|---|---|---|
| `SCHEMA_VERSION` | `1` (`PRAGMA user_version`) | Estructura de la BD |
| `BOT_VERSION` | `"bot-1"` | Marcadores/umbrales de la heurística de bots |
| `STOPWORDS_VERSION` | `"sw-1"` | Listas de stopwords (de ellas dependen bigramas/trigramas y `cluster_key`) |
| `INFORME_VERSION` | `"informe-1"` | Algoritmo de render del informe |

(Decisión D-019: **no existe versión del programa en código**; lo que se versiona son los algoritmos que afectan a la reproducibilidad.)

**Separación de capas:** la lógica pura (detección, emoción, render) no toca la BD; la capa de datos persiste resultados. Esto permite tests sin BD y modo degradado controlado.

### A.6 Límites conocidos documentados en el propio código

- **`echo_flags` vacía en Fase 1** por contrato: el anti-eco es Fase 2.
- **`gdelt_ref` vacío = n/d**: sin referencia descargada el informe muestra «n/d», nunca un dato inventado.
- **Detección 176 idiomas, análisis solo ES/EN** (stopwords y léxicos NRC solo ES/EN; VADER solo EN). Fallback lingua limitado a 8 idiomas (GL no existe en lingua 2.2.0).
- **Modo degradado explícito**: sin modelo fastText/NRC/VADER el sistema no falla en silencio: registra `procesa.modo_degradado` y `corre` penaliza el falso éxito (ALTO-1).
- **Días «inmaduros»**: una serie necesita historia (`DIAS_MADUREZ = 28` días) antes de confirmar señales; un sistema recién instalado no puede «predecir» nada todavía.
- **Simhash/MinHash implantados a mano** con la stdlib (sin numpy/scipy/datasketch) para mantener el paquete ligero y portable.

---

## Anexo B · Seguridad y privacidad

**Fecha del documento:** 2026-10-12 · **Fuentes:** `sibila/config.py`, `sibila/procesa.py`/`db.py`, `.gitignore`, `sibila/paquete.py`, `tools/descargar_recursos.py`, y las auditorías cruzadas de `auditoria/` (2026-10-12).

### B.1 Secretos: nunca versionados, nunca en logs

Medidas concretas (todas verificables en código):

| Medida | Dónde |
|---|---|
| `config.toml` (versionable) tiene **vetada** la sección `[secretos]`: si aparece, `ConfigError` al arrancar | `config.py` (`load_config`) |
| Los secretos solo caben en `config.local.toml` (gitignored) o en variables `SIBILA_*` | `config.py`, `.gitignore` |
| Los secretos se guardan con `repr=False` en un `MappingProxyType`: **no salen en el repr ni en logs** (trampa T4) | `config.py` |
| El manifiesto del paquete **excluye** `config.local.toml*` (salvo el `.example`), además de BD, logs y `__pycache__` | `paquete.py` |
| `.gitignore` bloquea `config.local.toml`, `datos/`, `logs/`, `*.db*`, `__pycache__/`, `registro/`, `.venv/` | `.gitignore` |
| El instalador endurece permisos de `config.local.toml` (`icacls`) | `instalar.bat` |

### B.2 Privacidad de autores: `author_hash` (HMAC)

Los autores de los documentos **nunca se guardan en claro**. En el punto de ingesta el identificador del autor se sustituye por `author_hash`, un **HMAC** con la `hmac_key` local:

- Permite deduplicar/agrupar por autor sin conocer al autor (anonimización seudonimizada).
- **Sin `hmac_key`, `author_hash` queda `NULL`** (nunca se cae a guardar el autor en claro). `doctor` lo avisa (D6).
- La clave vive solo en `config.local.toml`/`SIBILA_HMAC_KEY`; si se pierde, los hashes antiguos dejan de ser comparables con los nuevos (consecuencia aceptada y documentada).

### B.3 Dependencias: barrido OSV del 2026-10-12

- Las 10 dependencias están **pinneadas** (ver §1.2 de este manual). El **barrido OSV del 2026-10-12 (re-ejecutado por un verificador independiente) da 0 avisos** en todas salvo el caso urllib3, ya resuelto.
- **urllib3 se subió de 2.7.0 a 2.8.0** por 3 CVE corregidos en 2.8.0:

| CVE | Qué es | Exposición de SIBILA (clasificación de la auditoría) |
|---|---|---|
| CVE-2026-97688 (GHSA-gh4c-6fx4-qh6g) | Bucle infinito en streaming chunked+deflate | **Improbable**: SIBILA no llama a `stream()` directamente, pero `requests.get(...).content` sí alcanza internamente `urllib3.stream()` en **toda descarga**; requeriría un servidor hostil entre hosts fijos TLS |
| CVE-2026-97689 (GHSA-vxq7-64xx-v4gw) | Buffer ilimitado de línea chunk-size (memoria) | **Improbable**; impacto: agotamiento de memoria |
| CVE-2026-97687 (GHSA-8988-9cw3-xx77) | TLS de proxy HTTPS ignorada | **Improbable**: SIBILA no configura proxies; `requests` honra `HTTPS_PROXY` del entorno, la única vía teórica |

La auditoría **corrigió a la baja** la primera valoración («no explotable» → «improbable») al comprobar la ruta interna requests→urllib3, y por eso el bump se hizo **antes de cualquier recolección real**. urllib3 2.8.0 exige Python ≥3.10 y es compatible con `requests 2.34.2` (que pide `urllib3<3,>=1.26`).

### B.4 Procedencia e integridad de los recursos de datos

| Recurso | Origen | Integridad |
|---|---|---|
| `lid.176.ftz` (modelo fastText) | URL oficial de Facebook AI Research (`dl.fbaipublicfiles.com`), licencia MIT | SHA-256 **pinneado en el código** y **verificado por doble descarga del URL oficial** (D-030); `doctor` lo re-verifica |
| 4 léxicos NRC (VAD EN/ES, Emoción EN/ES) | `saifmohammad.com` (National Research Council Canada), **licencia no comercial** — no se redistribuyen, se descargan en la instalación | SHA-256 pinneados en `emocion.py`; **verificados contra descarga real el 2026-10-15** (D-077) |

El descargador **nunca pisa en silencio** un fichero cuyo hash no coincide: un recurso corrupto o manipulado es un fallo explícito, no un dato malo silencioso.

### B.5 Qué sale por red y qué no

**Sale por red (y solo en estos casos):**
- **Ingesta real** (`ingesta --en-vivo` / tareas programadas): RSS/HTML de las 4 fuentes públicas.
- **Alertas** (`alerta enviar/probar/digest`): API de Telegram y/o SMTP, solo si hay canales configurados.
- **Referencia GDELT** (`informe --actualizar-gdelt`).
- **Descarga de recursos** (`tools/descargar_recursos.py`) e instalación de dependencias.

**No sale por red:**
- La **batería de tests** completa (trabaja con fixtures; es una regla del proyecto).
- Todo el **procesado local** (`procesa`, `detecta`, `registro`, `informe` sin `--actualizar-gdelt`).
- **Ninguna telemetría**: el programa no «llama a casa»; no hay endpoints propios ni analítica.

**Riesgo residual declarado:** en una red con proxy por entorno (wifi de hotel), `requests` podría honrar `HTTPS_PROXY`; el programa no configura proxies por sí mismo.

### B.6 Integridad del propio paquete y del registro

- **Manifiesto SHA-256** de los 133 ficheros (`sibila paquete generar`/`verificar`), serializado con el `canonical_json` congelado; se verifica en destino tras instalar (ver el Anexo E).
- **Registro sellado**: cadena JSONL con hash encadenado (`hash`/`prev_hash`) cruzada con la tabla `predictions`, verificable con `registro verificar`, y anclaje opcional en git + OpenTimestamps para fijar el «cuándo» ante terceros.

---

## Anexo C · Pruebas y estado real

**Fecha del documento:** 2026-10-12 · **Fuentes:** `equipo/EVIDENCIA_CIERRE_DIA1_v1.md` (evidencia del Día 1 del cierre) y las auditorías de `auditoria/`. Regla de este documento: **no se afirma nada sin respaldo**; lo no probado se dice expresamente.

### C.1 Qué SÍ está probado (con evidencia)

#### Suite automatizada
- **737 passed / 3 skipped / 50 subtests** (2026-10-15, D-078), entorno: Python 3.12.12 · pytest 9.1.1 · urllib3 2.8.0 · requests 2.34.2 · lingua 2.2.0 · fasttext-predict 0.9.2.4. (735/3 al cierre del 2026-10-12; +1 frontera MED-1 en D-077, +1 anclaje sin señales en D-078.)
- Los 3 skips son los **esperados**: 2 × léxicos NRC reales ausentes (MED-5) + 1 × degradación-sin-lingua.
- Evolución del día: 726 (base intacta) → 728 (tras CRIT-1/CRIT-2/ALTO-1) → **735** (tras CRIT-3 y el resto).

#### Puertas de aceptación (todas verdes)
| Puerta | Resultado | Detalle |
|---|---|---|
| **CRIT-1** (carga del modelo de idioma) | **4/4** | ES@0.9838 · EN@0.9847 · FR@0.9973 · PT@0.9990 con el modelo real `lid.176.ftz` por la ruta de producción. Negativas: fichero ausente → degradado; corrupto → error controlado |
| **CRIT-2** (claves de alertas) | **OK** | Config ficticia con las 5 claves carga; canales habilitados; clave desconocida rechazada; `smtp_puerto` no entero rechazado; secretos en `config.toml` siguen vetados. **Sin ningún envío ni conexión real** |
| **ALTO-1** (anti falso-éxito) | **OK** | `corre` con fixture: exit 0 con lang poblado; sin modelo y con trabajo → **exit 1**; día hueco sin recursos → exit 0 legítimo |
| **CRIT-3** (conjunto lingua) | **OK** | Conjunto congelado de 8 {ES,EN,PT,FR,DE,IT,CA,EU}; la puerta `test_dudoso_cae_en_lingua` pasa **por primera vez en la historia del proyecto** con lingua real |

#### Escenarios y mordidas
- **C1–C8 + negativas extra (BOM, `telegram_chat` como entero): 10/10.**
- **Mordidas (mutation testing manual):** revertir la línea de idioma → muere la puerta CRIT-1; revertir la firma a `None` → muere la puerta verde de `corre`; quitar `telegram_chat` de la whitelist → muere CRIT-2. Tras cada mordida, restauración verificada **byte-exacta por hash**. (Demuestran que los tests muerden de verdad.)

#### E2E sintético y su lectura honesta
- **32 días / 576 documentos con dobles inyectados → verde** (dentro de la suite). Prueba la **fontanería** (ingesta→procesa→detecta→sellado).
- **Con el detector de idioma real: 576/576 quedan `lang NULL` y el anti falso-éxito dispara ROJO los 32 días.** Diagnóstico documentado: los cuerpos sintéticos son tokens artificiales con confianza fastText ~0.12 < umbral 0.80, así que la detección los rechaza honestamente. **Conclusión: el corpus sintético no prueba la lingüística; el ROJO observado es exactamente el comportamiento que ALTO-1 debía producir.**

#### Auditorías cruzadas del 2026-10-12
- **Reproducción por verificador independiente: PASS** — suite 728/3 reproducida en su propio entorno; puertas de idioma con frases propias; diff contra la referencia con exactamente los ficheros esperados, ni uno más.
- **Auditoría de seguridad: PASS** (barrido OSV re-ejecutado; ver el Anexo B).
- **Revisión cruzada:** encontró 3 críticos (después corregidos); una **segunda pasada** confirmó las correcciones.

#### Inglés de extremo a extremo (verificación del Día 2, agente verificador independiente)
- **Veredicto: OPERATIVO.** Detección con el modelo real (5/5 frases inglesas variadas sobre el umbral 0.80, confianzas 0.81–0.99); stopwords EN (`sw-1`, 161 palabras); n-gramas sin contaminación de stopwords; emoción EN con fixtures NRC + **VADER real** (confirmado matemáticamente que VADER entra en la valencia; VADER ausente → vector `None`, jamás un promedio a medias — anti-sesgo); pipeline completo vía `corre` con exit 0 y `emo_stats`/`term_stats` pobladas en `lang='en'`.
- **Prueba adversaria:** léxicos con SHA-256 incorrecto en `recursos/` → exit 1 con `[FALLO]` explícito (fallo visible, nunca silencioso).
- **Limitaciones exactas del veredicto:** la emoción usó fixtures de 8 palabras (los NRC reales siguen ausentes — el umbral de cobertura 0.30 deja textos neutros sin vector con el fixture); textos con confianza fastText < 0.80 caen a `lang NULL` si lingua no está instalada; el E2E del Día 2 se hizo con corpus propio del verificador, no con fuentes vivas.

### C.2 Qué NO está probado / verificado (honesto)

| No probado | Por qué importa | Estado |
|---|---|---|
| **Windows real** | Todo el despliegue previsto (`.bat`, tareas, `icacls`) es Windows-only | **Verificado (2026-10-15):** dos pruebas reales en Windows 11 ejecutadas por un verificador independiente; la segunda superó W1–W14 con los seis defectos de la primera corregidos (D-077/D-078). Queda pendiente un ciclo natural de 24 h con las tareas programadas |
| **Léxicos NRC reales** | Sin ellos **no hay emoción en producción** (el E2E usó fixtures de test) | MED-5 resuelta (D-077): la descarga automática funciona y los hashes están verificados; queda activarlos en la máquina de producción |
| **12 meses de datos reales** | La detección necesita historia (madurez 28 días mínimo) y la validación necesita un año de series reales | Pendiente |
| **Capacidad predictiva** | No hay evidencia de que las señales anticipen nada; el sistema está para *registrar y evaluar*, no para afirmar aciertos | **Sin validar** |
| **CLI por subproceso** | La CLI se ha ejercitado *in-process* en la suite, no como proceso independiente de extremo a extremo | Pendiente menor |

### C.3 Lectura global (sin marketing)

SIBILA está **sólido de fontanería** (persistencia, dedup, sellado, verificación, configuración, anti falso-éxito) y **honesto en sus degradaciones** (cuando falta un recurso, lo dice y no da un falso éxito). Pero **aún no es un predictor validado**: le faltan los recursos de emoción reales, la verificación en Windows y, sobre todo, meses de datos reales que permitan evaluar si las predicciones selladas aciertan. Cualquier afirmación más fuerte que esto **no está respaldada** por la evidencia disponible a 2026-10-12.

---

## Anexo D · Tareas pendientes

**Fecha del documento:** 2026-10-12 · **Fuentes:** `auditoria/FASE_PLANIFICACION_v1.md`, `auditoria/AUDITORIA_CIERRE_PREPARACION_v1.md`, `equipo/DECISIONES_PENDIENTES_v1.md`, `equipo/DECISIONES.md`, `equipo/EVIDENCIA_CIERRE_DIA1_v1.md`.

Formato por tarea: **estado · motivo · consecuencia práctica · requisitos para completarla · prueba que faltaría · riesgo de usar el sistema sin resolverla.**

---

### A. Bloqueantes para un uso real serio

#### A1 · Verificación en Windows real (plan W1–W14)
- **Estado:** **verificado en dos pruebas reales (2026-10-15, D-076/D-077/D-078).** Primera prueba: 6 defectos encontrados (2 bloqueantes) y corregidos. Segunda prueba: **W1–W14 satisfactorios** con los seis defectos verificados como corregidos. Queda pendiente únicamente un **ciclo natural de 24 horas** con las tareas programadas corriendo solas.
- **Motivo:** el despliegue previsto es Windows (`.bat`, XML de tareas, `icacls`, cp1252, Defender) y el sandbox no puede simularlo.
- **Consecuencia práctica:** no se puede asegurar que la instalación, las tareas programadas ni la consola funcionen en el entorno de destino.
- **Requisitos:** una sesión en el Windows real (con Hermes) ejecutando los 14 pasos W1–W14 con evidencia por paso (versión de Python, instalador, `check`/`doctor`, ingesta real 1 día —W9—, `procesa`+`detecta`+`sellar`, tarea importada y ejecutada, pipeline completo con alerta degradada, cp1252/Defender, concurrencia tarea+`resumen.py`). W10/W12 exigen el código ya reparado (hecho el 2026-10-12); W6 exige la decisión sobre los NRC; W11/W13/W14 son los únicos totalmente insimulables.
- **Prueba que faltaría:** 14/14 pasos con evidencia, o las limitaciones aceptadas expresamente. Está **prohibido** declarar «Windows validado» por inspección de los `.bat`.
- **Riesgo de usar sin resolverlo:** que el primer fallo se descubra en producción (tarea que no corre, BD bloqueada por Defender, consola ilegible), con pérdida de días de ingesta irrecuperables.

#### A2 · Los 4 léxicos NRC reales (MED-5) — RESUELTO en D-077 (2026-10-15)
- **Estado:** **resuelto.** La causa del HTTP 406 era el `User-Agent` por defecto de python-requests, rechazado por el servidor oficial; con cabeceras de navegador la descarga automática funciona (verificado el 2026-10-15: los 3 zips descargados, normalizados y **los 4 SHA-256 coinciden con los pinneados en `emocion.py`** — los hashes quedan verificados contra descarga real). `tools/descargar_recursos.py` ya incluye esas cabeceras; la descarga manual con navegador queda como ruta alternativa documentada.
- **Motivo:** sin los NRC no hay puntuación de emoción real (en el E2E se usaron fixtures).
- **Consecuencia práctica si faltan:** la serie emocional —pieza central del paradigma— no existe en producción; el sistema corre en modo degradado de emoción con avisos claros.
- **Requisitos para activarla:** ejecutar `tools/descargar_recursos.py` con red (el instalador ya lo hace) y, si un hash no coincide, no se fuerza: se documenta y se decide.
- **Prueba que faltaría:** `doctor` D3 en verde para los 4 NRC + `procesa --todo` recalculando `emo_stats` reales en la máquina de producción.
- **Riesgo de usar sin resolverlo:** creer que hay analítica emocional cuando solo hay degradado; el anti falso-éxito mitiga el autoengaño, pero la funcionalidad sigue ausente.

#### A3 · Auditoría humana/independiente y veredicto de aceptación
- **Estado:** hay **auditorías cruzadas entre agentes** (reproducción PASS, seguridad PASS, revisión con 3 críticos corregidos y segunda pasada). La **decisión 6** propone que cada revisión la audite un auditor independiente (Sol o Hermes) con recomputación propia y veredicto aprobado/rechazado/inconcluso (**inconcluso nunca cuenta como aprobado**). El **veredicto de Sol está pendiente**: cuando llegue, se incorpora o se rebate con evidencia.
- **Motivo:** la auto-verificación del equipo no sustituye una mirada externa; es la doble puerta previa a declarar cualquier versión VÁLIDA.
- **Consecuencia práctica:** ninguna versión puede declararse VÁLIDA mientras esta puerta no opere.
- **Requisitos:** aprobar la decisión 6 y enviar los paquetes de auditoría por revisión al auditor disponible.
- **Prueba que faltaría:** veredicto documentado (aprobado/rechazado/inconcluso) con recomputación propia de hashes y reproducción de las pruebas críticas.
- **Riesgo de usar sin resolverlo:** confianza no auditada; los fallos que el equipo no se inflige a sí mismo quedan sin descubrir.

#### A4 · 12 meses de datos reales
- **Estado:** no hay histórico real; la detección exige además madurez de serie (`DIAS_MADUREZ = 28` días) antes de confirmar señales.
- **Motivo:** la validación del paradigma (¿las señales anticipan algo?) solo se puede evaluar contra un año de series reales y resolución ciega de las predicciones selladas.
- **Consecuencia práctica:** hoy el sistema **registra** predicciones para poder evaluarlas mañana; no puede afirmarse que acierte.
- **Requisitos:** ingesta real diaria sostenida (~12 meses), con las tareas programadas verificadas (A1) y la emoción activa (A2).
- **Prueba que faltaría:** evaluación de acierto/fallo sobre las `predictions` resueltas (cumplida/fallada/expirada) tras el período, con resolución ciega.
- **Riesgo de usar sin resolverlo:** tomar decisiones basadas en señales de un sistema **no validado**; el diseño (registro sellado + resolución ciega) existe precisamente para no hacerlo.

---

### B. Decisiones abiertas del proyecto (no técnicas)

| Decisión | Estado | Qué falta |
|---|---|---|
| **Segunda copia de seguridad** | Recomendado USB dedicado (offline, ~10 €) + GitHub como ancla externa tras publicar. Hoy la referencia vive en **un solo disco** | Aprobación y ejecución; regla: la copia solo cuenta si `paquete verificar` pasa en el destino. **Riesgo de no hacerla:** perder el portátil = perder todo el historial |
| **Seudónimo público** | **Decidido (D-072, 2026-10-13): «Yosu Gem»**. El `NOTICE` del paquete ya lleva ese nombre; queda por crear la cuenta de GitHub (el propietario la crea; ningún agente recibe credenciales) | — (decisión tomada) |
| **Publicación** | Destino decidido: **GitHub, software libre, licencia Apache 2.0** (nombre SIBILA y licencia firmes). El paquete de publicación se prepara pero **nada se publica sin orden explícita** (publicar = entregar al mundo). Aviso registrado: GitHub permite una cuenta gratuita por persona; la cuenta la crea el propietario y ningún agente recibe credenciales | Orden explícita de publicación (la fuente 4chan /pol/ ya no viene habilitada por defecto, D-075) |
| **Léxico de jerga generacional (sociolectos de edad)** | **Paso previsto, no realizado** (planteado por el creador el 2026-10-12, D-069). Cada generación usa palabras y locuciones propias como marcador de identidad (*guay*, *mola mazo*, *tope*, *de puta madre*, *te cagas*…), a menudo con significado distinto del de diccionario: cambio semántico, intensificadores (*mazo*, *tope*), locuciones multi-palabra, inversión de polaridad (*jodido*). Hoy: la capa de emoción (NRC, formal) no las conoce o las etiquetaría con su sentido estándar; la capa de n-gramas **sí las captura sin diccionario** — aparición, frecuencia y series en `term_stats`, y la detección de *emergentes* podría registrar el nacimiento de una palabra nueva —. Lo que falta: léxico de jerga con valencia emocional por cohorte y mantenimiento continuo (la jerga nace y muere con su generación); SIBILA tampoco modela autores ni edades (solo fuentes y fechas), así que la atribución generacional sería inferida por co-ocurrencia temporal, no observada | Decisión del creador (versión futura, D-019): diseño del recurso léxico, registro de hashes, pruebas y cobertura por idioma |

Otras decisiones menores ya catalogadas en el consolidado (numeración de la referencia, `sw-2`, identificador dual de versiones, regla de cierre en Z) siguen el principio: **el silencio no autoriza nada**.

---

### C. Incidencias técnicas abiertas (catálogo)

Reparadas el 2026-10-12: **CRIT-1, CRIT-2, CRIT-3, ALTO-1** y el pin urllib3 (INFO-1). Reparadas el 2026-10-15 tras la primera prueba real en Windows 11 (D-077): **MED-1** (reloj UTC único en los rangos por defecto del CLI), **MED-3** (`sibila` importable desde cualquier carpeta vía `.pth` que escribe el instalador), **MED-5** (descarga NRC con cabeceras de navegador: el 406 era el rechazo del User-Agent de python-requests), **BAJO-1** (`.pytest_cache` excluido del manifiesto) y **BAJO-5** (`plantillas\` existe de nuevo con `config.toml` y `fuentes.toml` canónicos). Siguen abiertas, planificadas para próximas versiones:

| Incidencia | Gravedad | Resumen | Versión prevista |
|---|---|---|---|
| **ALTO-2** | Alta | Stopwords del español sin tildes: no filtran las formas acentuadas reales → lista `sw-2` con marca de versión por fila (hoy no hay datos reales: la decisión es barata ahora, cara después) | 0.9.2 |
| **MED-2** | Media | `--actualizar-gdelt` solo descarga el lunes | 0.9.3 |
| **MED-4** | Media | Costes cuadráticos / cargas completas en memoria en rangos largos (requiere benchmark antes/después) | 0.9.3 |
| **BAJO-2..4** | Baja | Logs de `.bat` sin rotación; código muerto / exit 3 inalcanzable; docstring de exit code incorrecta | 0.9.4 |
| **INFO-2..5** | Info | Fragilidad latente en propagación de clúster; condición redundante en `cli.py`; exit 2 discutible en `corre` sin feedparser; `check` escribe sonda en `logs/` del proyecto | 0.9.4 |
| **INFO-6** | Info | 4chan /pol en la distribución pública: **resuelto en D-075 (2026-10-13)** — no viene habilitada por defecto en `fuentes.toml` (señal ruidosa, riesgo reputacional, valor nunca validado); el conector sigue disponible y probado para quien lo active manualmente. Sin versión prevista — la numeración es prerrogativa de Yosu (D-019) | — (resuelto, D-075) |

---

### D. Orden lógico de desbloqueo

```
A1 (Windows) ──┐
A2 (NRC)      ─┼─► A3 (auditoría independiente) ─► versión VÁLIDA ─► A4 (12 meses) ─► validación predictiva
B (backup)    ──┘   (publicación solo tras VÁLIDA y orden explícita)
```

Nada de lo anterior está bloqueado por falta de diseño: todo tiene plan, prueba de aceptación y responsable propuestos. Lo que falta es **ejecución en el entorno real y decisiones explícitas**.

---

## Anexo E · Conservación

**Fecha del documento:** 2026-10-12 · **Fuentes:** `referencia/ACTA_CONGELACION_20260920.md`, `sibila/paquete.py`, `equipo/DECISIONES.md`, el manifiesto vigente en `nucleo/`.

### E.1 Piezas de la conservación

| Pieza | Qué es | Dónde |
|---|---|---|
| **Referencia congelada** | Copia byte-exacta del árbol auditado (131 ficheros, CRLF preservado), de **solo lectura** | `referencia/arbol_auditado_20260920/` |
| **Acta de congelación** | Documento que fija la identidad del árbol: hash del manifiesto, contenido, exclusiones y defectos conocidos al congelar | `referencia/ACTA_CONGELACION_20260920.md` |
| **Manifiesto regenerable** | `MANIFIESTO.sha256.json`: SHA-256 + tamaño de cada fichero del paquete | Raíz del árbol (`nucleo/`) |
| **DECISIONES.md** | Registro cronológico de decisiones: la memoria de *por qué* cada cambio | `equipo/DECISIONES.md` |

### E.2 La referencia congelada (identidad)

- **Manifiesto:** `generado: 2026-09-20T14:46:53Z` · `generador: sibila-paquete-1` · `version_programa: null` (no hay versión de programa en el código, D-019).
- **SHA-256 del manifiesto:** `02b0c92f92f7e95176c90e3acecf31769a7d890f6618efbd4af6fdf1dd840061`.
- **Contenido:** 131 ficheros de manifiesto + el propio manifiesto = 132 ficheros, 894 641 bytes.
- **Verificación de la copia [EJEC 2026-10-11]:** 131/131 SHA-256 coincidentes, 0 fallos (verificación recomputada fichero a fichero, no asumida).
- **Qué incluye:** código `sibila/` (46 `.py` + `schema.sql`), `tests/` completa con fixtures (69 ficheros), `tools/`, los `.bat`/`.xml` y `resumen.py`, plantillas de configuración **sin secretos**, `requirements.txt`, `LEEME_T2.md`.
- **Qué excluye y por qué:** `config.local.toml*` (secretos, nunca viajan), `datos/`·`logs/`·`registro/` (datos de un árbol vivido), `__pycache__/`·`*.pyc` (artefactos regenerables, excluidos por regla), `.gitignore` y el propio manifiesto (autoexcluido). Matiz honesto: `.pytest_cache/` consta ausente de la referencia, pero su exclusión **no está endurecida** en `paquete.py` — si se corre pytest en el árbol y se regenera el manifiesto, el conteo cambia (incidencia abierta **BAJO-1**; ver el Anexo D).
- **Advertencia honesta del acta:** la referencia congelada corresponde al estado **2026-09-20, con los defectos CRIT-1/CRIT-2/ALTO-1 aún abiertos y urllib3 2.7.0**. El acta lo dice expresamente: «729 verdes ≠ programa sano» y «esta referencia NO es VÁLIDA». Es un **punto de recuperación histórico**, no una versión recomendada.

### E.3 El manifiesto regenerable

El manifiesto **no es un objeto precioso: es regenerable** con el propio programa, de forma **determinista** (mismo árbol → mismo manifiesto, porque se serializa con el `canonical_json` congelado):

```
# Regenerar (solo al construir/empaquetar; NUNCA sobre la referencia)
python -m sibila paquete generar

# Verificar un árbol contra su manifiesto (exit 0 = íntegro)
python -m sibila paquete verificar
```

`instalar.bat` ya corre `paquete verificar` **en destino** tras copiar, de modo que una copia corrupta se detecta en el acto. Regla del proyecto: **una copia de seguridad solo cuenta si `paquete verificar` pasa en el destino.**

> Matiz temporal (honesto): el árbol de trabajo `nucleo/` tiene hoy un manifiesto **regenerado el 2026-10-15** (`sibila-paquete-1`, **133 ficheros** — la carpeta `plantillas/` reingresó en D-077) tras las reparaciones del cierre y de las pruebas Windows. La **referencia** sigue siendo la del 2026-09-20. Conviven dos manifiestos: el histórico (congelado) y el vigente (regenerado tras los cambios asentados en DECISIONES.md).

### E.4 DECISIONES.md como registro

`equipo/DECISIONES.md` es la memoria del proyecto: cada cambio relevante queda asentado con fecha, motivo y evidencia (entradas D-nnn). Reglas asociadas:

- **Todo cambio** respecto a una versión debe estar asentado en la entrada de esa versión; comparar árboles sin ese asiento es incomparable.
- **El silencio no autoriza nada:** una decisión no tomada no habilita ningún cambio.
- **Congelada ≠ válida:** incluso una versión rechazada se congela (se conserva), pero marcada como tal.
- Protección por capas: solo-lectura + hash del manifiesto anclado en el registro + segunda copia física (pendiente, ver el Anexo D) + re-verificación periódica + ancla externa (GitHub/OTS) cuando se publique.

### E.5 Cómo restaurar un fichero (o todo) a su estado de referencia

**Todo el árbol:**
1. Copia `referencia/arbol_auditado_20260920/` a un destino nuevo (nunca trabajes sobre la referencia).
2. Dentro: `python -m sibila paquete verificar` → debe decir **ÍNTEGRO 131/131**.
3. Alternativa sin el programa: recomputa el SHA-256 de cada fichero y compáralo con `MANIFIESTO.sha256.json` (la copia es byte-exacta, CRLF incluido).

**Un solo fichero:**
1. Localiza su ruta en el manifiesto de la referencia y su SHA-256 esperado.
2. Copia ese fichero desde `arbol_auditado_20260920/` al árbol de trabajo (byte-exacto).
3. Verifica: `sha256sum <fichero>` (o `Get-FileHash` en Windows) contra el valor del manifiesto; luego `python -m sibila paquete verificar` en el árbol completo.
4. **Asienta la restauración en DECISIONES.md** (qué fichero, desde qué referencia, por qué).

**Comparar con una versión posterior:** genera el manifiesto de la versión nueva y coteja entradas por ruta: hash distinto = cambiado; ruta nueva = añadido; ruta ausente = retirado. Todo cambio ha de tener su asiento.

### E.6 Reglas de conservación (resumen operativo)

1. La referencia es **de solo lectura**: nada la modifica jamás; una reparación se hace en una versión nueva.
2. Una copia **solo cuenta si verifica** (`paquete verificar` en destino).
3. Los **secretos nunca** entran en copias ni paquetes (`config.local.toml` excluido).
4. **Segunda copia física** (USB dedicado) recomendada y pendiente: hoy todo vive en un solo disco (ver el Anexo D).
5. Ancla externa (GitHub/OpenTimestamps) cuando se publique; publicar requiere orden explícita.
