@echo off
set "SCRIPT_DIR=%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    if "%*"=="" (py "%SCRIPT_DIR%interpresona_gui.py") else (py "%SCRIPT_DIR%interpresona_installer.py" %*)
    set "EXIT_CODE=%errorlevel%"
) else (
    where python >nul 2>nul
    if not errorlevel 1 (
        if "%*"=="" (python "%SCRIPT_DIR%interpresona_gui.py") else (python "%SCRIPT_DIR%interpresona_installer.py" %*)
        set "EXIT_CODE=%errorlevel%"
    ) else (
        echo Python 3 non e' installato.
        echo Installa Python 3.10 o superiore da https://www.python.org/downloads/windows/
        start "" "https://www.python.org/downloads/windows/"
        set "EXIT_CODE=1"
    )
)
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
