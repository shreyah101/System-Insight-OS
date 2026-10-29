@echo off
where py >nul 2>&1
if errorlevel 1 goto use_python
py -3 "%~dp0run.py" %*
goto done
:use_python
python "%~dp0run.py" %*
:done
set "run_exit=%errorlevel%"
if not "%run_exit%"=="0" pause
exit /b %run_exit%
