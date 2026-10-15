@echo off
rem SIBILA - pipeline diario completo (tarea "SibilaDiario", plan T2 seccion 6)
rem Encadena: ingesta -> procesa -> detecta -> registro sellar -> registro
rem anclar -> registro verificar -> alerta enviar -> alerta digest
rem (anti-duplicacion 168 h en el digest:
rem lanzarlo a diario es seguro, solo sale el semanal).
rem Log en logs\pipeline_diario.log (UTF-8). Exit 1 si un eslabon falla:
rem RestartOnFailure de la tarea lo reintenta (3 x 5 min).
rem La doble ingesta (07:00 SibilaIngesta + 07:45 aqui) esta justificada en
rem D-048/H6: la recoleccion es lo irrecuperable; lo demas es reejecutable.
cd /d %~dp0
set PYTHONUTF8=1
if not exist logs mkdir logs
set "LOG=logs\pipeline_diario.log"
set "PY=.venv\Scripts\python.exe"

"%PY%" -c "from datetime import datetime,timezone; print('=== pipeline', datetime.now(timezone.utc).strftime('%%Y-%%m-%%dT%%H:%%M:%%SZ'), '(UTC) ===')" >> %LOG% 2>&1

"%PY%" -m sibila ingesta --en-vivo >> %LOG% 2>&1
if errorlevel 1 ( echo [FALLO] ingesta >> %LOG% & exit /b 1 )
"%PY%" -m sibila procesa >> %LOG% 2>&1
if errorlevel 1 ( echo [FALLO] procesa >> %LOG% & exit /b 1 )
"%PY%" -m sibila detecta >> %LOG% 2>&1
if errorlevel 1 ( echo [FALLO] detecta >> %LOG% & exit /b 1 )
"%PY%" -m sibila registro sellar >> %LOG% 2>&1
if errorlevel 1 ( echo [FALLO] registro sellar >> %LOG% & exit /b 1 )
"%PY%" -m sibila registro anclar >> %LOG% 2>&1
if errorlevel 1 ( echo [FALLO] registro anclar >> %LOG% & exit /b 1 )
rem La integridad del JSONL se chequea a diario (D-048/H7): un ROJO temprano
rem vale mas que uno a los 3 meses.
"%PY%" -m sibila registro verificar >> %LOG% 2>&1
if errorlevel 1 ( echo [FALLO] registro verificar: registro ROTO >> %LOG% & exit /b 1 )
rem Entrega del dia (B2): respeta cooldowns (72 h/24 h); a diario es seguro.
rem Sin credenciales y nada que enviar da exit 0 con AVISO: no es fallo.
"%PY%" -m sibila alerta enviar >> %LOG% 2>&1
if errorlevel 1 ( echo [FALLO] alerta enviar >> %LOG% & exit /b 1 )
"%PY%" -m sibila alerta digest >> %LOG% 2>&1
rem El digest sin canales configurados da exit 0 con AVISO: no es fallo.
exit /b 0
