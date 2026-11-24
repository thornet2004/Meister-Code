"""Build from the canonical spec, then installer and an unpublished release template."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app_version import VERSION

def verify_binary_version(executable):
    from PyInstaller.utils.win32.versioninfo import read_version_info_from_executable
    try:
        info=read_version_info_from_executable(str(executable));ffi=info.ffi
        actual=(ffi.fileVersionMS>>16,ffi.fileVersionMS&65535,ffi.fileVersionLS>>16,ffi.fileVersionLS&65535)
    except Exception:raise ValueError('O executável não tem metadados de versão válidos. Reconstrói-o com o spec atual.') from None
    expected=tuple(map(int,VERSION.split('.')))+(0,)
    if actual!=expected:raise ValueError('Versão do executável '+'.'.join(map(str,actual))+' diferente da release '+VERSION+'. Reconstrói antes de empacotar.')

def main():
    p=argparse.ArgumentParser();p.add_argument('--iscc',required=True);p.add_argument('--skip-exe',action='store_true');p.add_argument('--exe');p.add_argument('--base-url',default='');args=p.parse_args();root=Path(__file__).resolve().parents[1]
    if args.exe and not args.skip_exe:p.error('--exe requer --skip-exe.')
    if args.base_url:
        from release_updates import https
        https(args.base_url)
    if not args.skip_exe:subprocess.run([sys.executable,'-m','PyInstaller','--clean','--noconfirm',str(root/'Studio de Media.spec')],cwd=root,check=True)
    # o Setup leva a versão em pasta (dist/Meister IA IDE): não descompacta nada na pasta temporária ao arrancar
    folder=Path(args.exe).resolve().parent if args.exe else root/'dist/Meister IA IDE';executable=folder/'Studio de Media.exe'
    verify_binary_version(executable)
    subprocess.run([args.iscc,'/DAppVersion='+VERSION,'/DSourceDir='+str(folder),str(root/'installer/Studio.iss')],cwd=root,check=True)
    setup=root/'dist'/('Meister-IA-IDE-'+VERSION+'-Setup.exe')
    data=dict(schema=1,version=VERSION,platform='windows-x64',url=(args.base_url.rstrip('/')+'/'+setup.name) if args.base_url else '',sha256=hashlib.sha256(setup.read_bytes()).hexdigest(),size=setup.stat().st_size,notes='')
    target=root/'dist'/('release.json' if args.base_url else 'release.template.json');target.write_text(json.dumps(data,indent=2),encoding='utf-8');print('Release:',setup,'Manifesto:',target)
if __name__=='__main__':main()
