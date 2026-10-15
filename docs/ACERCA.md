# Acerca de SIBILA

**Documento principal del proyecto · Cierre del desarrollo, 12 de octubre de 2026.**
**Estado del programa: utilizable en sus funciones comprobadas; capacidad predictiva NO validada. Ninguna versión ha sido declarada VALIDA.**

---

## 1. Qué es SIBILA

SIBILA es un programa de línea de comandos (CLI) de **lingüística aplicada a la investigación**: un instrumento que mide cómo evoluciona el lenguaje emocional de la gente corriente en internet — foros, comunidades, tablones de comentarios — bajo una hipótesis falsable: que ciertos cambios colectivos en ese lenguaje pueden preceder a ciertos acontecimientos.

La hipótesis es **falsable por diseño**. SIBILA sella sus señales en un registro encadenado por hashes **antes** de que puedan cumplirse o fallar, de modo que cualquiera pueda comprobar después qué se dijo, cuándo se dijo y si acertó. El programa no pide fe: pide verificación.

**Qué NO es.** No es un oráculo. No es un producto comercial. No es un agregador de prensa: por decisión expresa de su creador, los medios de comunicación (periódicos, radios, medios oficiales, artículos de opinión) están **prohibidos como fuente de señal** — «eso no es intuición colectiva, es ingeniería social». Los datos de prensa (GDELT) sirven únicamente como referencia externa de validación —fecha de primera cobertura de un tema—, nunca como entrada del modelo.

## 2. Origen e idea

SIBILA nace de la idea de su creador: la intuición colectiva existe y deja rastro en el lenguaje antes de que los hechos ocurran; si se mide con disciplina —fuentes correctas, método explícito, predicciones selladas por escrito y por anticipado—, esa hipótesis puede ponerse a prueba con honestidad en lugar de convertirse en superstición.

El proyecto se gobernó desde el primer día con reglas escritas (`equipo/DECISIONES.md`, decisiones D-001 en adelante): el creador decide nombres, versiones y rumbo; nadie audita su propio trabajo; lo no registrado no existe; y una meta-regla por encima de todas —**sin ego**—: autocrítica obligatoria, aceptar ideas mejores vengan de quien vengan, y rectificar cuanto antes.

## 3. Autoría y atribución

En palabras del creador, que fijan la atribución correcta del trabajo:

> «SIBILA fue desarrollado mediante la programación de Kimi, a partir de las ideas de programación de Kimi y de mi interacción, dirección, seguimiento, decisiones y control como creador del proyecto. ChatGPT colaboró proporcionando ideas, revisiones, verificaciones y auditorías.»

Desglosado:

- **El creador (Yosu Gem)** — idea original, propósito, interacción continua, dirección, seguimiento, **todas las decisiones** y el control del proyecto de principio a fin. La gobernanza del proyecto (qué se hace, qué no se hace, cuándo se para) es suya.
- **Kimi** (agente de IA de Moonshot AI) — **programación completa del código** del programa y **diseño técnico** (idea general de la programación, elección de herramientas, campos y áreas del sistema), ejecutado bajo las indicaciones y el control del creador. Las pruebas técnicas y verificaciones del cierre documentadas en `equipo/EVIDENCIA_CIERRE_DIA1_v1.md` fueron ejecutadas por Kimi y por sub-agentes verificadores de Kimi.
- **ChatGPT («Sol»)** — colaboración mediante **ideas, revisiones, verificaciones y auditorías** sobre el diseño, los documentos y las decisiones del proyecto.

Ningún agente de IA es autor del proyecto: la autoría y la responsabilidad pertenecen al creador. Las contribuciones se describen tal como ocurrieron; **no se atribuye a ningún agente verificaciones que no haya realizado**. (Nota de privacidad: el creador aparece como «el creador» / Yosu Gem por decisión propia —seudónimo público decidido el 2026-10-13, D-072—; no se publican su nombre ni apellidos.)

## 4. Qué hace el programa

Un solo comando, `sibila corre`, ejecuta el pipeline diario completo (también disponible por pasos: `ingesta`, `procesa`, `detecta`, `registro`, `informe`, `alerta`):

1. **Ingesta** — recolecta textos públicos de las fuentes habilitadas (ver §5), con deduplicación en el punto de ingesta (misma URL o mismo contenido no entra dos veces).
2. **Procesado** — limpieza del texto, **detección de idioma** (fastText, modelo `lid.176`: 176 idiomas; detector de respaldo lingua para 8 idiomas frecuentes), puntuación de calidad, heurística anti-bots, eliminación de palabras vacías (stopwords ES/EN), extracción de n-gramas y **análisis emocional** (léxicos NRC verificados por hash; VADER para inglés).
3. **Detección temporal** — sobre las series diarias: z-score robusto, CUSUM y test de Mann-Kendall, para señalar cambios inusuales y tendencias.
4. **Registro sellado** — las señales se escriben como predicciones en un fichero encadenado por hashes (`predicciones.jsonl`), anclado en un repositorio git interno (y OpenTimestamps si está disponible). El registro es **intocable**: verificarlo es un comando (`sibila registro verificar`) y forma parte del pipeline diario.
5. **Informe** — informe del período en siete secciones: Resumen, Tensión, Emergentes, Alertas, Anomalías, Predicciones y Exportación.
6. **Alertas** — avisos por Telegram o correo (SMTP), con enfriamiento (*cooldown*) y digest semanal con anti-duplicación de 7 días. Sin credenciales, el programa funciona igual: los intentos quedan registrados como fallo visible, nunca en silencio.

Garantías transversales: base de datos SQLite con comprobación de integridad (`sibila check` → verde/rojo); manifiesto SHA-256 de todo el paquete (`sibila paquete verificar`); recursos de datos (modelo de idioma y léxicos) verificados por SHA-256 tras la descarga; y **modo degradado honesto**: si faltan los recursos de idioma y el procesamiento analítico no pudo realizarse, el día sale en **ROJO con explicación y remediación**, nunca en verde falso.

## 5. Fuentes de información

Las cuatro fuentes iniciales, todas de conversación pública y dominio mayoritariamente anglófono:

| Fuente | Qué aporta |
|---|---|
| Reddit (`r/worldnews`) | Actualidad global discutida por usuarios |
| Lobsters | Comunidad técnica |
| Mastodon.social (etiqueta «ai») | Conversación federada sobre IA |
| 4chan (`/pol/`) | Tablón anónimo — **conector disponible y probado, pero no habilitado en la configuración por defecto** (D-075: señal ruidosa y riesgo reputacional; se activa manualmente en `fuentes.toml` si se desea) |

Son conectores **enchufables** bajo un contrato de interfaz: añadir o retirar uno no altera el resto del programa. La elección responde a dónde se concentra el volumen de conversación pública accesible; la prensa queda excluida como señal por decisión del creador (§1).

## 6. Alcance de idiomas

**SIBILA opera hoy en dos idiomas: español e inglés.** No es un descuido: es una decisión de diseño, y conviene entenderla antes de juzgarla.

### Qué hace el programa con los idiomas

El pipeline distingue tres niveles:

1. **Detección amplia.** El detector de idioma (fastText, modelo `lid.176`) reconoce 176 idiomas, con un segundo detector de respaldo (lingua) para los 8 más frecuentes en las fuentes (ES, EN, PT, FR, DE, IT, CA, EU). Nada se descarta por idioma en la entrada: un texto en cualquier idioma se identifica y se etiqueta. *(El conjunto de respaldo iba a incluir el gallego, pero la librería lingua 2.2.0 no lo soporta —el intento rompía con `AttributeError`—; se retiró y quedó documentado. fastText sí detecta gallego: está entre los 176.)*
2. **Análisis profundo, solo ES/EN.** El análisis emocional —el corazón del método predictivo de SIBILA— se apoya en léxicos contrastados (NRC-VAD y NRC Emotion Lexicon) que existen con garantías en inglés (original) y español (traducción verificada). Fuera de ES/EN **no se inventa emoción**: el documento se etiqueta con su idioma y aporta volumen, pero no serie emocional.
3. **Fuentes.** Las fuentes iniciales son de dominio mayoritariamente anglófono, que es donde se concentra el volumen de conversación pública de los conectores incluidos.

### Por qué se hizo así

Un análisis emocional con léxicos no verificados no es un análisis peor: es un análisis falso. Medir la «emoción» de un texto en portugués con un léxico inglés produciría cifras con aspecto científico y contenido arbitrario — exactamente el tipo de espejismo que SIBILA existe para evitar. Se prefirió decir «esto no lo medimos» antes que medirlo mal.

### Lo que el creador quiere hacer

La ambición declarada del proyecto es **ampliar a los principales idiomas de internet** (portugués, francés, alemán, italiano y los que el uso real aconseje): las señales tempranas no respetan fronteras lingüísticas, y una parte de la conversación mundial simplante no ocurre en inglés ni en español.

### Las limitaciones reales (lo que hace falta para cada idioma nuevo)

1. **Fuentes** en ese idioma (configuración; la parte fácil).
2. **Listas de stopwords** propias y versionadas (sin ellas, los n-gramas se llenan de palabras vacías).
3. **Léxicos de emoción verificados** para ese idioma — la parte dura: hay que localizarlos, comprobar su licencia, fijar su hash y validar su cobertura mínima sobre corpus real. NRC Emotion Lexicon tiene traducciones a muchos idiomas; NRC-VAD, en cambio, solo tiene inglés original y español traducido.
4. **Pruebas** específicas por idioma (positivas y negativas), como las que rigen para ES/EN.

### Cómo puedes mejorarlo

Si quieres añadir un idioma, el camino es el de arriba, en ese orden, y la arquitectura ya lo espera: la detección no excluye ningún idioma, las stopwords son listas versionadas intercambiables (`STOPWORDS_VERSION`), y los léxicos se cargan con verificación de integridad — añadir uno nuevo es añadir su fichero verificado y su par de claves, no reescribir el motor. Las contribuciones que no traigan léxico verificado y pruebas no se aceptarán como análisis emocional: podrán aportar detección y volumen, con la limitación marcada.

## 7. Herramientas y decisiones técnicas

- **Python 3.12**, **SQLite** (PostgreSQL documentado como opción), interfaz **CLI** única `sibila` con subcomandos y salidas verde/rojo.
- Pensado para **Windows** (instalación con script único, operable sin conocimientos técnicos); el desarrollo y toda la verificación del cierre se hicieron en **Linux** (la verificación en Windows real está en curso: primera prueba ejecutada, correcciones D-077 aplicadas, segunda prueba pendiente — ver §9).
- Dependencias fijadas por versión; los recursos de datos (modelo de idioma, léxicos) viajan aparte y se verifican por **SHA-256**.
- Sin Docker, sin servicios pesados, sin API REST, sin dashboard (fuera de alcance por decisión del creador).
- Registro de predicciones encadenado por hashes con anclaje git/OpenTimestamps: la falsabilidad es un mecanismo técnico, no una promesa.

## 8. Estado actual (a 12 de octubre de 2026)

Verificado en el cierre del desarrollo (evidencia completa en `equipo/EVIDENCIA_CIERRE_DIA1_v1.md`; el acta de cierre está archivada en `equipo/ACTA_CIERRE_SIBILA_v1.md`):

- **Batería de pruebas: 735 superadas, 3 omitidas** (las 3 omisiones son correctas y explicadas: dos requieren los léxicos NRC reales, aún ausentes; una prueba la degradación sin lingua y solo corre sin lingua instalada).
- **Reparaciones del cierre (Día 1), todas verificadas con pruebas positivas y negativas, mordidas de mutación y reversión byte-exacta por hash:** carga del modelo de idioma por la API correcta (CRIT-1); 5 claves de configuración de alertas que eran inalcanzables (CRIT-2); control anti falso-éxito — un día sin procesamiento analítico real sale ROJO, no verde (ALTO-1); actualización de `urllib3` 2.7.0 → 2.8.0 por 3 CVE (barrido OSV en vivo: 2.8.0 limpia); y CRIT-3: el respaldo de idiomas incluía un código inexistente en lingua (gallego), corregido a 8 idiomas.
- **Verificación cruzada con agentes independientes:** reproducción completa en entorno propio (PASS), verificación de seguridad de dependencias contra OSV y PyPI (PASS), y revisión de lógica que encontró 3 defectos críticos en la primera versión del control anti falso-éxito — corregidos y confirmados en segunda pasada con reproducción propia.
- **Inglés de extremo a extremo: OPERATIVO (verificado por agente independiente, Día 2).** Detección con el modelo real (5/5 frases inglesas variadas sobre el umbral 0.80, confianzas 0.81–0.99), stopwords inglesas (lista `sw-1`, 161 palabras), n-gramas sin contaminación de palabras vacías, emoción inglesa con VADER real (confirmado matemáticamente que VADER entra en la valencia; sin VADER no se fabrica dato — anti-sesgo verificado) y pipeline completo con exit 0 y series `emo_stats`/`term_stats` pobladas en `lang='en'`. Prueba adversaria superada: léxicos con hash incorrecto → exit 1 con fallo visible, nunca silencioso. Limitaciones exactas: la emoción en producción depende de los léxicos NRC reales (ausentes, ver §9); sin lingua instalada, los textos ingleses con confianza de detección < 0.80 quedan sin idioma en vez de caer al respaldo.
- **Referencia congelada** (`referencia/arbol_auditado_20260920/`, 131 ficheros): intacta en cada sesión; nunca alterada.

## 9. Limitaciones y trabajo pendiente

Registrado con detalle (estado, razón, consecuencia, requisitos y riesgo) en el Anexo D del `MANUAL_DE_USUARIO.md`. Lo esencial:

- **Léxicos NRC reales ausentes en la instalación típica si la descarga falla**: sin ellos no hay análisis emocional en producción. Las pruebas de emoción usan léxicos de fixture. Su descarga automática funciona (D-077, 2026-10-15: el HTTP 406 era el rechazo del User-Agent de python-requests; resuelto con cabeceras de navegador y hashes verificados contra descarga real); la descarga manual queda como ruta alternativa. Instalarlos es un paso documentado, no un cambio de código.
- **Jergas — generacionales (sociolectos de edad) y de grupos o tribus urbanas: posible trabajo futuro; no implantado ni validado** (planteado por el creador el 2026-10-12, ampliado el 2026-10-13). Cada generación —y cada grupo o tribu urbana— usa palabras y locuciones propias como marcador de identidad —*guay*, *mola mazo*, *tope*, *de puta madre*, *te cagas*…—, a menudo con un significado distinto del de diccionario (cambio semántico, intensificadores, locuciones multi-palabra). Hoy la capa de emoción (léxicos NRC, formales) no las conoce; en cambio la capa de n-gramas **sí las captura sin diccionario**: su aparición, frecuencia y series temporales quedan en `term_stats`, y la detección de *emergentes* podría registrar el nacimiento de una de estas palabras. Lo pendiente sería un léxico de jergas con valencia emocional por cohorte o grupo —y su mantenimiento continuo, porque la jerga nace y muere con su comunidad—. **El análisis de estas jergas queda como posible trabajo futuro y no está implantado ni validado** (D-019, D-069, D-075); detalle en el Anexo D del manual.
- **Verificación en Windows real: en curso** (batería W1–W14; primera prueba real ejecutada en Windows 11 el 2026-10-14/15 con defectos encontrados y corregidos en D-077 — plantillas, XML de tareas en UTF-16, NRC 406, mensaje de init, MED-1 y MED-3 —; queda pendiente la segunda prueba real que confirme las correcciones. El cierre se verificó en Linux y **ningún documento afirma que SIBILA funciona en Windows** hasta que esa prueba termine).
- **12 meses de datos reales: no realizados.** Sin ese período sellado y su contraste, **la capacidad predictiva de SIBILA NO está validada** — y este proyecto nunca lo ha afirmado.
- **Auditoría humana independiente: pendiente.** Las verificaciones del cierre fueron ejecutadas por agentes de IA con evidencia reproducible; una auditoría humana sigue siendo deseable.
- El corpus sintético de pruebas prueba la **fontanería** del pipeline (ingesta→series→detección→registro), no la lingüística: sus textos artificiales quedan por debajo del umbral de confianza del detector, y el programa responde correctamente en ROJO.
- Detalles menores documentados: la CLI se ejercitó *in-process* en las pruebas (repetición por subproceso pendiente); un día 100% irrecuperable queda ROJO de forma permanente por diseño (*fail-closed*); `not` figura como stopword inglesa (la negación no aparece en n-gramas — no afecta a la emoción, que se calcula sobre el texto completo); el extractor de n-gramas exige texto ya limpiado por el pipeline (usarlo sobre texto crudo mutila mayúsculas sin error — trampa documentada para reutilizadores).

## 10. Cierre del desarrollo

Por orden del creador (D-064), el desarrollo de SIBILA se cierra aquí: **programa utilizable en sus funciones comprobadas, defectos visibles, documentación completa, trabajo pendiente registrado — sin declarar VALIDA ninguna versión y sin presentar como demostradas las aspiraciones originales.** El cierre no exigía que SIBILA alcanzara todas sus metas: exigía que lo hecho fuera real, lo no hecho fuera visible, y todo quedara en condiciones de ser retomado o auditado por cualquiera.

## Documentación del proyecto

La documentación de SIBILA son **seis documentos bilingües** (español e inglés, mismo contenido):

| Español | Inglés | Contenido |
|---|---|---|
| `LEEME.md` | `README.md` | Portada: qué es, estado y arranque rápido |
| `ACERCA.md` | `ABOUT.md` | Este documento: origen, autoría, qué hace, idiomas, estado, limitaciones |
| `MANUAL_DE_USUARIO.md` | `USER_MANUAL.md` | Instalación, configuración, uso de la CLI y anexos técnicos (arquitectura, seguridad, pruebas, pendientes, conservación) |

*Gobernanza histórica del proyecto: `equipo/DECISIONES.md` (D-001 en adelante). Evidencias del cierre: `equipo/EVIDENCIA_CIERRE_DIA1_v1.md` y el acta final (`equipo/ACTA_CIERRE_SIBILA_v1.md`).*
