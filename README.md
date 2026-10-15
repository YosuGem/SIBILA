# SIBILA

**Experimental open-source CLI program for applied-linguistics research: it listens to what ordinary people post in public forums, measures how emotional and thematic language shifts day by day, and seals predictions in an immutable, hash-chained registry so that results can be evaluated honestly afterwards.**

> **ATTENTION — THIS PROGRAM IS UNFINISHED.** It works and its test suite is green, but it has **not** completed a natural 24-hour scheduled cycle, it has **not** passed the planned independent audit and it has **not** accumulated the 12 months of real data needed to evaluate its predictions. Its predictive capability is **not validated**. A detailed list of what is missing is in the sections *Current status* and *Known limitations* below and in `docs/USER_MANUAL.md` (Annex C and D). Please read them before relying on anything this program produces.

---

## What SIBILA is and what it actually does

SIBILA is a research tool, not a news reader. Instead of press — a prepared narrative — it listens to public conversations and watches the *language* itself:

- **Ingests public sources** in short batches (minutes per session, not 24/7): Reddit (`r/worldnews`), Lobsters and Mastodon (hashtag `#ai`) are enabled by default. A 4chan connector exists but is **disabled by default**. GDELT is used only as an optional reference to contrast predictions, never as content.
- **Processes language**: language detection (fastText `lid.176`, 176 languages), deduplication (hand-written SimHash + MinHash-LSH, pure stdlib), quality and bot heuristics, emotion scoring (NRC VAD lexicons for Spanish and English, VADER for English), n-grams.
- **Detects statistical changes**: day-of-week baselines, robust z-score, CUSUM, Mann-Kendall and Theil-Sen, hand-written on the standard library.
- **Seals predictions**: every signal becomes an immutable prediction in an append-only JSONL chain (SHA-256, genesis of 64 zeros), cross-checked against SQLite, with optional git/OpenTimestamps anchoring. Nobody — not even the author — can rewrite the history afterwards. Whether the approach works is not declared: it is *measured*, with the sealed registry as judge.
- **Reports and alerts**: alert rules with cooldown (Telegram/SMTP), weekly digest and weekly report in Markdown/JSON/CSV.
- **Verifiable package**: SHA-256 manifest of every shipped file (`paquete verificar`) and a self-diagnostic command (`doctor`).

## Main functions

| Area | What you get |
|---|---|
| Ingestion | Batch connectors with opaque cursors stored in the same transaction as the data |
| Processing | Language ID, dedup, quality, bots, emotion (ES/EN), n-grams, stopwords |
| Detection | z_r, CUSUM, Mann-Kendall with maturity gates (28 days of history before confirming) |
| Sealed registry | Hash-chained predictions, full verification, crash reconciliation, optional anchoring |
| Reports | Weekly report (MD/JSON/CSV), optional GDELT contrast (`n/d` when absent, never invented) |
| Operations | Windows scheduled tasks, degraded mode with explicit warnings, no false success: a day with nothing processed cannot come back green |

## Requirements

- **Windows 11** (the designed target: installer, `.bat` files and scheduled tasks; installation and operation verified in two real Windows 11 test sessions) or **Linux** (development platform).
- **Python 3.12** (`py -3.12` on Windows).
- Internet connection for installation, ingestion, alerts and the GDELT reference. **No telemetry**: the program never calls home.
- Optional: **git** (registry anchoring), **OpenTimestamps** client (external timestamping). Without them the program keeps working with clear warnings; neither is ever a failure.

## Install, configure, run, check

1. Unzip to a short path outside cloud-synced folders, e.g. `C:\sibila`.
2. Run `instalar.bat`. It creates the virtual environment, installs pinned dependencies, downloads the language model and the NRC lexicons (SHA-256 verified), generates your local secrets (`config.local.toml` — never leaves your PC), creates the database, demands a green `check`, verifies the package integrity *at destination* and registers two daily scheduled tasks (`SibilaIngesta` 07:00, `SibilaDiario` 07:45).
3. Edit `config.local.toml` to set alert channels (optional). Secrets live only there or in `SIBILA_*` environment variables — never in `config.toml`.
4. Run the pipeline manually with `.venv\Scripts\python.exe -m sibila corre`, or let the scheduled tasks run.
5. Check health anytime: `sibila check`, `sibila doctor`, `sibila paquete verificar`, `sibila registro verificar`.

Full instructions in `docs/USER_MANUAL.md` (English) and `docs/MANUAL_DE_USUARIO.md` (castellano). Project background in `docs/ABOUT.md` and `docs/ACERCA.md`.

## Current status

- **Test suite: 737 passed / 3 skipped / 50 subtests** (the 3 skips are documented: external lexicons not vendored). The suite never touches the network; it runs on fixtures.
- **Real Windows 11 verification: two independent test sessions (2026-10-15).** The first found 6 defects (2 blocking); all were fixed and the second session passed the full W1–W14 procedure.
- Acceptance gates, mutation testing and cross-audits (reproduction PASS, security PASS) are documented in `docs/USER_MANUAL.md`, Annex C.

## Known limitations (honest list)

- **Unfinished program.** Still pending: a natural 24-hour cycle with the scheduled tasks running on their own, the independent auditor's verdict, and ~12 months of real daily data with blind resolution of the sealed predictions.
- **Predictive capability NOT validated.** The system exists to *register* predictions and evaluate them later; nothing stronger is claimed.
- **Full linguistic analysis only for Spanish and English.** Language detection covers 176 languages, but emotion/stopword analytics are ES/EN only, and the default sources are English-speaking, so most useful volume is English.
- **Immature series:** a fresh install cannot confirm signals until ~28 days of history exist.
- External services can fail (e.g. a Mastodon timeout); a source returning zero documents on an empty feed is a legitimate empty day, not an error.

## Available, optional and future

- **Available now:** everything listed in *Main functions*.
- **Optional (never a failure):** git anchoring, OpenTimestamps, the 4chan connector (disabled by default), the digest channel, the `lingua` fallback detector.
- **Future (not built yet):** a dashboard — when it is built it will be dark-mode —, the anti-echo layer (`echo_flags`, reserved for Phase 2), the generational-slang lexicon, and the items catalogued in `docs/USER_MANUAL.md` Annex D (stopwords `sw-2`, GDELT scheduling, performance work on long ranges).

## Contributing, reporting bugs, proposing improvements

- **Bugs:** open an issue describing what you ran, what you expected and what happened; attach the output of `sibila doctor` if relevant. Never attach your `config.local.toml` or any credential.
- **Improvements:** open an issue or a pull request. Keep the style: standard library first, heavy dependencies lazy and optional, every degradation explicit, no silent failures, tests without network.
- **Untouchable without discussion:** `sibila/registro/canonico.py` (the frozen canonical serialization every hash depends on) and the pinned resource hashes.

## License and terms of use

- SIBILA's code is **Apache License 2.0** — see [LICENSE](LICENSE). Attribution to the original author (**Yosu Gem**) is required in copies and derivative works — see [NOTICE](NOTICE).
- The **NRC VAD lexicons** are © National Research Council Canada, free for **non-commercial research** use; they are not redistributed here — the installer downloads them from the official site and verifies their SHA-256. The fastText `lid.176` model is distributed by its authors under the MIT license and is likewise downloaded at install time.
- SIBILA reads only public sources; respect each site's terms and robots policies when you add sources.

## A personal note from the author

*I hope you like SIBILA and find it useful, and I hope you feel like improving it. I have had to publish it before finishing the program and completing the whole testing process, because of time and resource limitations. I know nothing about programming. I have done what I could with the means within my reach. With more time and resources I could probably have gone much, much further. Over the coming months I will be less connected to the internet, especially from a computer, so I am publishing the project now so that anyone who wishes can consult it and improve it. Its behaviour still has to be checked through a long period of real operation, with daily ingestion and evaluation of its results. I also have two other programs related to the same subject that I will upload after this one. They are unfinished too. Each of them was my idea, but with the necessary and essential collaboration of different artificial intelligences: in terms of programming, each one was developed by a different artificial intelligence. When I can, I will upload the other two as well. I hope that will be in November 2026 — that is, within a month.*

---
---

# SIBILA (castellano)

**Programa experimental de código abierto, de línea de comandos, para investigación en lingüística aplicada: escucha lo que la gente corriente publica en foros públicos, mide cómo cambian el lenguaje emocional y los temas día a día y sella predicciones en un registro inmutable encadenado por hash para poder evaluar los resultados después con honestidad.**

> **ATENCIÓN — ESTE PROGRAMA ESTÁ SIN ACABAR.** Funciona y su batería de pruebas está en verde, pero **no** ha completado un ciclo natural de 24 horas con las tareas programadas, **no** ha pasado la auditoría independiente prevista y **no** ha acumulado los 12 meses de datos reales necesarios para evaluar sus predicciones. Su capacidad predictiva **no está validada**. La lista detallada de lo que falta está en las secciones *Estado actual* y *Limitaciones conocidas* de abajo y en `docs/MANUAL_DE_USUARIO.md` (anexos C y D). Léelas antes de confiar en cualquier cosa que produzca este programa.

---

## Qué es SIBILA y qué hace realmente

SIBILA es una herramienta de investigación, no un lector de noticias. En lugar de prensa —relato preparado—, escucha las conversaciones públicas y observa el *lenguaje* en sí:

- **Ingiere fuentes públicas** en lotes cortos (minutos por sesión, no 24/7): Reddit (`r/worldnews`), Lobsters y Mastodon (etiqueta `#ai`) vienen habilitadas por defecto. Existe un conector de 4chan, pero viene **desactivado por defecto**. GDELT se usa solo como referencia opcional para contrastar predicciones, nunca como contenido.
- **Procesa el lenguaje**: detección de idioma (fastText `lid.176`, 176 idiomas), deduplicación (SimHash + MinHash-LSH propios, stdlib pura), filtros de calidad y de bots, puntuación de emoción (léxicos NRC VAD para español e inglés, VADER para inglés) y n-gramas.
- **Detecta cambios estadísticos**: baseline por día de semana, z-score robusto, CUSUM, Mann-Kendall y Theil-Sen implantados a mano sobre la biblioteca estándar.
- **Sella predicciones**: cada señal se convierte en una predicción inmutable en una cadena JSONL append-only (SHA-256, génesis de 64 ceros), cruzada con SQLite y con anclaje opcional en git/OpenTimestamps. Nadie —ni el propio autor— puede reescribir la historia después. La verdad o mentira del enfoque no se declara: se *mide*, con el registro sellado como juez.
- **Informes y alertas**: reglas con cooldown (Telegram/SMTP), digest semanal e informe semanal en Markdown/JSON/CSV.
- **Paquete verificable**: manifiesto SHA-256 de todos los archivos distribuidos (`paquete verificar`) y autodiagnóstico (`doctor`).

## Funciones principales

| Área | Qué obtienes |
|---|---|
| Ingesta | Conectores por lotes con cursores opacos guardados en la misma transacción que los datos |
| Procesado | Idioma, deduplicación, calidad, bots, emoción (ES/EN), n-gramas, stopwords |
| Detección | z_r, CUSUM, Mann-Kendall con puertas de madurez (28 días de historia antes de confirmar) |
| Registro sellado | Predicciones encadenadas por hash, verificación completa, reconciliación tras fallo y anclaje opcional |
| Informes | Informe semanal (MD/JSON/CSV), contraste GDELT opcional (`n/d` si falta, jamás inventado) |
| Operación | Tareas programadas de Windows, modo degradado con avisos explícitos, sin falso éxito: un día sin nada procesable no puede salir en verde |

## Requisitos

- **Windows 11** (destino de diseño: instalador, `.bat` y tareas programadas; instalación y funcionamiento verificados en dos pruebas reales de Windows 11) o **Linux** (plataforma de desarrollo).
- **Python 3.12** (`py -3.12` en Windows).
- Conexión a internet para instalar, ingerir, alertar y la referencia GDELT. **Sin telemetría**: el programa nunca llama a casa.
- Opcional: **git** (anclaje del registro) y cliente **OpenTimestamps** (sello de tiempo externo). Sin ellos el programa sigue funcionando con avisos claros; nunca son un fallo.

## Instalación, configuración, ejecución y comprobación

1. Descomprime en una ruta corta fuera de carpetas sincronizadas, p. ej. `C:\sibila`.
2. Ejecuta `instalar.bat`. Crea el entorno virtual, instala dependencias pinneadas, descarga el modelo de idioma y los léxicos NRC (SHA-256 verificado), genera tus secretos locales (`config.local.toml` — nunca sale de tu PC), crea la base de datos, exige un `check` en verde, verifica la integridad del paquete *en destino* y registra dos tareas programadas diarias (`SibilaIngesta` 07:00, `SibilaDiario` 07:45).
3. Edita `config.local.toml` para activar canales de alerta (opcional). Los secretos viven solo ahí o en variables `SIBILA_*` — nunca en `config.toml`.
4. Ejecuta el pipeline a mano con `.venv\Scripts\python.exe -m sibila corre` o deja que corran las tareas programadas.
5. Comprueba la salud cuando quieras: `sibila check`, `sibila doctor`, `sibila paquete verificar`, `sibila registro verificar`.

Instrucciones completas en `docs/MANUAL_DE_USUARIO.md` (castellano) y `docs/USER_MANUAL.md` (English). Contexto del proyecto en `docs/ACERCA.md` y `docs/ABOUT.md`.

## Estado actual

- **Batería de pruebas: 737 passed / 3 skipped / 50 subtests** (los 3 skips están documentados: léxicos externos que no se redistribuyen). La batería nunca toca la red; trabaja con fixtures.
- **Verificación real en Windows 11: dos sesiones de prueba independientes (2026-10-15).** La primera encontró 6 defectos (2 bloqueantes); se corrigieron todos y la segunda superó el procedimiento completo W1–W14.
- Puertas de aceptación, pruebas de mutación y auditorías cruzadas (reproducción PASS, seguridad PASS) documentadas en `docs/MANUAL_DE_USUARIO.md`, anexo C.

## Limitaciones conocidas (lista honesta)

- **Programa sin acabar.** Siguen pendientes: un ciclo natural de 24 horas con las tareas programadas corriendo solas, el veredicto del auditor independiente y unos 12 meses de datos reales diarios con resolución ciega de las predicciones selladas.
- **Capacidad predictiva NO validada.** El sistema existe para *registrar* predicciones y evaluarlas después; no se afirma nada más fuerte que eso.
- **Análisis lingüístico completo solo en español e inglés.** La detección cubre 176 idiomas, pero la analítica de emoción y stopwords es solo ES/EN y las fuentes por defecto son anglófonas, así que el volumen útil mayoritario es inglés.
- **Series inmaduras:** una instalación reciente no puede confirmar señales hasta reunir unos 28 días de historia.
- Los servicios externos pueden fallar (p. ej. un timeout de Mastodon); una fuente que devuelve cero documentos con el feed vacío es un día hueco legítimo, no un error.

## Disponible, opcional y futuro

- **Disponible ahora:** todo lo listado en *Funciones principales*.
- **Opcional (nunca es fallo):** anclaje git, OpenTimestamps, el conector de 4chan (desactivado por defecto), el canal digest y el detector de reserva `lingua`.
- **Futuro (aún no construido):** un dashboard —cuando se haga será en modo oscuro—, la capa anti-eco (`echo_flags`, reservada para la Fase 2), el léxico de jerga generacional y los ítems catalogados en el anexo D de `docs/MANUAL_DE_USUARIO.md` (stopwords `sw-2`, programación de GDELT y trabajo de rendimiento en rangos largos).

## Cómo contribuir, informar de errores y proponer mejoras

- **Errores:** abre un issue describiendo qué ejecutaste, qué esperabas y qué ocurrió; adjunta la salida de `sibila doctor` si es relevante. No adjuntes nunca tu `config.local.toml` ni credencial alguna.
- **Mejoras:** abre un issue o un pull request. Mantén el estilo: biblioteca estándar primero, dependencias pesadas perezosas y opcionales, toda degradación explícita, nada de fallos silenciosos, pruebas sin red.
- **Intocable sin discusión previa:** `sibila/registro/canonico.py` (la serialización canónica congelada de la que dependen todos los hashes) y los hashes pinneados de los recursos.

## Licencia y condiciones de uso

- El código de SIBILA es **Apache License 2.0** — ver [LICENSE](LICENSE). La atribución al autor original (**Yosu Gem**) es obligatoria en copias y obras derivadas — ver [NOTICE](NOTICE).
- Los **léxicos NRC VAD** son © National Research Council Canada, gratuitos para uso de **investigación no comercial**; no se redistribuyen aquí — el instalador los descarga del sitio oficial y verifica su SHA-256. El modelo fastText `lid.176` se distribuye por sus autores bajo licencia MIT y también se descarga en la instalación.
- SIBILA lee solo fuentes públicas; respeta los términos y las políticas de robots de cada sitio al añadir fuentes.

## Nota personal del autor

*Espero que SIBILA os guste y os resulte útil. Y espero que os animéis a mejorarlo. He tenido que publicarlo antes de terminar el programa y de completar todo el proceso de pruebas por limitaciones de tiempo y de recursos. No tengo ni idea de programación. He hecho lo que he podido con los medios disponibles a mi alcance. Con más tiempo y recursos probablemente habría podido llegar muchísimo más lejos. Durante los próximos meses estaré menos conectado a internet, especialmente desde el ordenador, por lo que publico ahora el proyecto para que pueda ser consultado y mejorado por quien quiera. Sigue pendiente comprobar su comportamiento mediante un periodo prolongado de funcionamiento real, con ingesta diaria y evaluación de sus resultados. También tengo otros dos programas relacionados con lo mismo que subiré después de este. También están sin acabar. Cada uno de ellos ha sido idea mía, pero con la necesaria e imprescindible colaboración de inteligencias artificiales distintas. Cada uno lo ha desarrollado en cuestión de programación una inteligencia artificial distinta. Cuando pueda también subiré los otros dos. Espero que sea en noviembre de 2026, es decir, dentro de un mes.*
