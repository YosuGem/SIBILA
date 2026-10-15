@echo off
rem ============================================================
rem  SIBILA - Instalador T2 minimo (Bloque 3, plan Hopper seccion 3)
rem  Sin pasos manuales: cada paso verifica o aborta con exit 1.
rem  No requiere admin. Prerequisito: Python 3.12 de python.org
rem  (con py launcher). Instalar en ruta corta, FUERA de OneDrive
rem  (recomendado C:\sibila o %USERPROFILE%\sibila).
rem ============================================================
chcp 65001 >nul
setlocal
rem PYTHONUTF8=1 solo en ESTA sesion del bat (rev. Hamilton M2: setlocal va ANTES,
rem si no la variable fugaba a la consola que llamo al instalador)
set PYTHONUTF8=1
cd /d %~dp0
set "PY=.venv\Scripts\python.exe"

echo === SIBILA - instalacion ===

rem --- 0. Plantillas en destino (D-048/H4): sin ellas, ingesta --en-vivo falla
rem Idempotente: existentes NO se pisan (misma regla que config.local.toml)
if not exist config.toml (
  if exist plantillas\config.toml (
    copy /y plantillas\config.toml config.toml >nul
    echo [OK] config.toml materializado desde plantillas
  ) else (
    echo [FALLO] falta config.toml y la plantilla plantillas\config.toml
    exit /b 1
  )
) else (
  echo [OK] config.toml ya existe: no se pisa
)
if not exist fuentes.toml (
  if exist plantillas\fuentes.toml (
    copy /y plantillas\fuentes.toml fuentes.toml >nul
    echo [OK] fuentes.toml materializado desde plantillas
  ) else (
    echo [FALLO] falta fuentes.toml y la plantilla plantillas\fuentes.toml
    exit /b 1
  )
) else (
  echo [OK] fuentes.toml ya existe: no se pisa
)

rem --- 1. Python 3.12 presente
py -3.12 -V >nul 2>&1
if errorlevel 1 (
  echo [FALLO] No encuentro Python 3.12. Instalalo desde python.org ^(marcando "py launcher"^) y reintenta.
  exit /b 1
)
echo [OK] Python 3.12 encontrado

rem --- 2. Entorno virtual
if not exist .venv (
  py -3.12 -m venv .venv
  if errorlevel 1 ( echo [FALLO] No se pudo crear .venv & exit /b 1 )
)
echo [OK] Entorno virtual listo

rem --- 2b. sibila importable desde CUALQUIER carpeta (MED-3, D-077):
rem un .pth en site-packages con la ruta raiz hace que
rem ".venv\Scripts\python.exe -m sibila ..." funcione aunque la consola
rem este en otro directorio (la config siempre se ancla a ESTA raiz).
rem La ruta se escribe sin espacio final (redireccion antes del echo).
if not exist .venv\Lib\site-packages mkdir .venv\Lib\site-packages
> ".venv\Lib\site-packages\sibila_raiz.pth" echo %CD%
echo [OK] sibila_raiz.pth escrito ^(doctor/check funcionan desde cualquier cwd^)

rem --- 3. Dependencias (SIN --only-binary: sgmllib3k es sdist puro, plan V2)
rem Opt-out lingua (306 MB): SIBILA_SIN_LINGUA=1 instala requirements-nucleo.txt
if "%SIBILA_SIN_LINGUA%"=="1" (
  findstr /V /C:"lingua-language-detector" requirements.txt > requirements-nucleo.txt
  "%PY%" -m pip install -r requirements-nucleo.txt
) else (
  "%PY%" -m pip install -r requirements.txt
)
if errorlevel 1 ( echo [FALLO] pip install fallo; revisa la red y reintenta & exit /b 1 )
echo [OK] Dependencias instaladas

rem --- 3b. Recursos de datos (lid.176.ftz + lexicos NRC, SHA-256 fijado)
rem Fallo de red NO aborta (degradado documentado): doctor lo reflejara.
"%PY%" tools\descargar_recursos.py
if "%SIBILA_SIN_LINGUA%"=="1" (
  "%PY%" -c "from sibila import config; import pathlib; d=config.load_config().data_dir/'recursos'; d.mkdir(parents=True, exist_ok=True); (d/'SIN_LINGUA').write_text('skip explicito', encoding='ascii')"
  echo [OK] centinela SIN_LINGUA escrito ^(fallback de idioma desactivado^)
)

rem --- 4. Sonda de imports (siempre con el python del venv: rev. Liskov 6)
rem El modulo de fasttext-predict se llama "fasttext" (D-048/H1)
"%PY%" -c "import feedparser, requests, sgmllib, fasttext, vaderSentiment" 2>nul
if errorlevel 1 ( echo [FALLO] Las dependencias no se importan; instala de nuevo & exit /b 1 )
if "%SIBILA_SIN_LINGUA%"=="1" (
  echo [OK] feedparser, requests, sgmllib, fasttext y vaderSentiment importables ^(lingua: skip explicito^)
) else (
  "%PY%" -c "import lingua" 2>nul
  if errorlevel 1 ( echo [FALLO] lingua no se importa; instala de nuevo o define SIBILA_SIN_LINGUA=1 & exit /b 1 )
  echo [OK] feedparser, requests, sgmllib, fasttext, vaderSentiment y lingua importables
)

rem --- 5. Secretos: genera config.local.toml SOLO si no existe (idempotente)
if not exist config.local.toml (
  "%PY%" tools\generar_secretos.py config.local.toml
  if errorlevel 1 ( echo [FALLO] No se pudo generar config.local.toml & exit /b 1 )
  icacls config.local.toml /inheritance:r /grant:r "%USERNAME%:F" >nul 2>&1
) else (
  echo [OK] config.local.toml ya existe: no se toca
)

rem --- 6. Base de datos
"%PY%" -m sibila init
if errorlevel 1 ( echo [FALLO] init fallo & exit /b 1 )

rem --- 7. PUERTA: check debe dar VERDE
if not exist logs mkdir logs
"%PY%" -m sibila check > logs\check_instalacion.log 2>&1
findstr /C:"check: VERDE" logs\check_instalacion.log >nul
if errorlevel 1 (
  echo [FALLO] check no dio VERDE. Mira logs\check_instalacion.log y NO instales la tarea todavia.
  exit /b 1
)
echo [OK] check: VERDE

rem --- 7b. doctor (informe post-instalacion; NO es puerta: la puerta es check)
"%PY%" -m sibila doctor > logs\doctor_instalacion.log 2>&1
type logs\doctor_instalacion.log

rem --- 7c. Integridad del paquete EN DESTINO (rev. Hamilton M2): el
rem manifiesto se verifica donde se usa, no solo donde se genero.
"%PY%" -m sibila paquete verificar > logs\paquete_verificar.log 2>&1
if errorlevel 1 (
  echo [FALLO] paquete verificar: el paquete en destino no coincide con el manifiesto. Mira logs\paquete_verificar.log
  exit /b 1
)
echo [OK] paquete verificado en destino

rem --- 8. Tareas programadas diarias (D-077): el XML final que consume
rem schtasks se escribe en UTF-16 LE con BOM: en la prueba real W11 de
rem Windows 11, schtasks RECHAZO la variante UTF-8 sin BOM y acepto UTF-16.
rem La sustitucion de placeholders la hace tools\preparar_tarea.py (logica
rem unica y testeada, T-INS-7); la fecha de manana la calcula PowerShell.
rem Se regenera SIEMPRE (rev. Hamilton N2 / Dijkstra M3: reinstalar en otra
rem carpeta con el XML viejo dejaba la tarea apuntando a la ruta anterior).
rem Guarda (rev. Dijkstra M4, ahora en preparar_tarea.py): una ruta con
rem &, < o > romperia el XML -> error claro y exit 1.
for /f "usebackq" %%I in (`powershell -NoProfile -Command "(Get-Date).AddDays(1).ToString('yyyy-MM-dd')"`) do set "MANANA=%%I"
"%PY%" tools\preparar_tarea.py tarea_ingesta.xml tarea_ingesta.final.xml "%CD%" "%MANANA%T07:00:00"
if errorlevel 1 ( echo [FALLO] No se pudo preparar la tarea XML ^(mira el mensaje de arriba^) & exit /b 1 )
schtasks /create /tn "SibilaIngesta" /xml tarea_ingesta.final.xml /f >nul
if errorlevel 1 ( echo [FALLO] schtasks fallo; crea la tarea a mano con tarea_ingesta.final.xml & exit /b 1 )
echo [OK] Tarea "SibilaIngesta" creada ^(diaria, 07:00 local; si el PC esta apagado corre al encender^)

rem --- 8b. Tarea SibilaDiario (pipeline completo 07:45; ExecutionTimeLimit PT2H, D-048/H6)
"%PY%" tools\preparar_tarea.py tarea_diaria.xml tarea_diaria.final.xml "%CD%" "%MANANA%T07:45:00"
if errorlevel 1 ( echo [FALLO] No se pudo preparar la tarea diaria XML & exit /b 1 )
schtasks /create /tn "SibilaDiario" /xml tarea_diaria.final.xml /f >nul
if errorlevel 1 ( echo [FALLO] schtasks fallo; crea la tarea a mano con tarea_diaria.final.xml & exit /b 1 )
echo [OK] Tarea "SibilaDiario" creada ^(diaria, 07:45 local: pipeline completo + digest^)

echo.
echo === Instalacion completa. Primera ingesta de prueba: ===
echo     schtasks /run /tn SibilaIngesta
echo     schtasks /run /tn SibilaDiario
echo     y manana por la manana: "%PY%" resumen.py
echo     cuadro completo: "%PY%" -m sibila informe
echo     si doctor dio avisos de recursos: "%PY%" tools\descargar_recursos.py
exit /b 0
