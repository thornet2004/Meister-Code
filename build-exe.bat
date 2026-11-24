@echo off
REM Gera um .exe autonomo (sem consola) do Studio de Media com PyInstaller.
REM Resultado: dist\Studio de Media.exe  (copiavel para outro PC)
cd /d "%~dp0"

echo Instalando/atualizando o PyInstaller...
python -m pip install --upgrade pyinstaller >nul 2>&1

echo.
echo A empacotar (pode demorar 1-3 minutos)...
python -m PyInstaller --noconfirm --clean "Studio de Media.spec"
if errorlevel 1 exit /b 1

echo.
if exist "dist\Studio de Media.exe" (
    echo Pronto! O executavel esta em:  dist\Studio de Media.exe
    echo Podes copia-lo para outro PC ^(Windows 10/11 com WebView2^).
) else (
    echo Algo correu mal no build. Ve as mensagens acima.
)
echo.
pause
