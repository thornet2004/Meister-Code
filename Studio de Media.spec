# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, copy_metadata
from pathlib import Path
import runpy
from PyInstaller.utils.win32.versioninfo import VSVersionInfo,FixedFileInfo,StringFileInfo,StringTable,StringStruct,VarFileInfo,VarStruct
release=runpy.run_path(str(Path(SPECPATH)/'app_version.py'))
release_version=release['VERSION'];version_tuple=tuple(map(int,release_version.split('.')))+(0,)
windows_version=VSVersionInfo(ffi=FixedFileInfo(filevers=version_tuple,prodvers=version_tuple),kids=[StringFileInfo([StringTable('040904B0',[StringStruct('FileDescription',release['APP_NAME']),StringStruct('ProductName',release['APP_NAME']),StringStruct('FileVersion',release_version),StringStruct('ProductVersion',release_version),StringStruct('OriginalFilename','MeisterCode.exe')])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])

datas = [('web', 'web')]
datas += [('bench_server.py', '.'), ('bench_catalog.py', '.'), ('bench_launcher.py', '.')]
# lista de origens das ferramentas: o pacote não leva as ferramentas, só o manifesto para as instalar
datas += [('tools_manifest.json', '.'), ('Sources_ferramentas.md', '.')]
# bloqueios do npm usados pelo instalador (servidores LSP e REA)
datas += [('installer/lsp/package.json', 'installer/lsp'), ('installer/lsp/package-lock.json', 'installer/lsp'), ('installer/rea/package.json', 'installer/rea'), ('installer/rea/package-lock.json', 'installer/rea'), ('installer/imagemagick-mcp/package-lock.json', 'installer/imagemagick-mcp')]
# ficheiros de apoio das ferramentas da lista (ferramenta.json, etc.): o instalador da app copia-os para a pasta de cada uma
import json as _json
for _tool in _json.loads((Path(SPECPATH) / 'tools_manifest.json').read_text(encoding='utf-8'))['tools']:
    for _name in ('ferramenta.json', 'configuracao.json', 'adapter.json', 'LEIA-ME.md'):
        if (Path(SPECPATH) / 'Ferramentas' / _tool['key'] / _name).is_file():
            datas.append(('Ferramentas/%s/%s' % (_tool['key'], _name), 'tool_support/' + _tool['key']))
if (Path(SPECPATH) / 'third-party-licenses').is_dir():
    datas.append(('third-party-licenses', 'third-party-licenses'))
datas += copy_metadata('mcp', recursive=True)
datas += copy_metadata('pg8000', recursive=True)
datas += copy_metadata('PyMySQL')
binaries = []
hiddenimports = ['mcp.client.auth', 'mcp.shared.auth']
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pythonnet')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('clr_loader')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('edge_tts')  # voz natural opcional (online)
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('aiohttp')  # usado pelo edge-tts
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Studio de Media',
    icon=str(Path(SPECPATH)/'web/assets/meistercode.ico'),
    version=windows_version,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# Versão em pasta (a que o Setup instala): os ficheiros ficam ao lado do executável, em _internal,
# e nada é descompactado na pasta temporária do Windows a cada arranque.
exe_folder = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Studio de Media',
    icon=str(Path(SPECPATH)/'web/assets/meistercode.ico'),
    version=windows_version,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
folder = COLLECT(exe_folder, a.binaries, a.datas, strip=False, upx=True, upx_exclude=[], name='Meister IA IDE')
