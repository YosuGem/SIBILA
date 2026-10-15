@echo off
rem SIBILA - ingesta diaria (lanzada por la tarea "SibilaIngesta", plan Bloque 3 seccion 4)
rem Salida a logs\ingesta_tarea.log en UTF-8 (PYTHONUTF8=1 solo en esta sesion del bat).
rem El exit code llega al Programador de tareas: 1 = fallo -> RestartOnFailure (3 x 5 min).
cd /d %~dp0
set PYTHONUTF8=1
if not exist logs mkdir logs
".venv\Scripts\python.exe" -c "from datetime import datetime,timezone; print('=== ingesta', datetime.now(timezone.utc).strftime('%%Y-%%m-%%dT%%H:%%M:%%SZ'), '(UTC) ===')" >> logs\ingesta_tarea.log 2>&1
".venv\Scripts\python.exe" -m sibila ingesta --en-vivo >> logs\ingesta_tarea.log 2>&1
exit /b %ERRORLEVEL%
