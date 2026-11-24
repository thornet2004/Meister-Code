@echo off
REM Instala as dependencias da app (correr uma vez, na primeira utilizacao).
REM Este abre consola de proposito, para veres o progresso/erros.
cd /d "%~dp0"
echo Instalando requisitos do Studio de Media...
echo.
python -m pip install -r requirements.txt
echo.
if errorlevel 1 (
    echo.
    echo Houve um erro na instalacao. Confirma que o Python esta instalado
    echo e acessivel no PATH ^(abre um terminal e escreve: python --version^).
) else (
    echo Pronto! Ja podes abrir a app com duplo-clique em "Studio de Media.lnk" ou em "dist\Studio de Media.exe".
)
echo.
pause
