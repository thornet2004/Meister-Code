"""Instalação portátil explícita: origens oficiais, SHA-256 e registo local."""
import concurrent.futures,hashlib,json,os,subprocess,zipfile
from pathlib import Path
import requests
import bench_catalog
ROOT=Path(__file__).resolve().parent/'Ferramentas'
PACKAGES=[
 ('ImageMagick','7.1.2-35','https://github.com/ImageMagick/ImageMagick/releases/download/7.1.2-35/ImageMagick-7.1.2-35-portable-Q16-HDRI-x64.7z','34db4364da26c88d6b8cc5bbc1fff22b85d00d3b399c82fe85ee4790efacbbf1'),
 ('OpenOCD','0.12.0-7','https://github.com/xpack-dev-tools/openocd-xpack/releases/download/v0.12.0-7/xpack-openocd-0.12.0-7-win32-x64.zip','6bfd3c97135aafef8affc9af1acf34fd0e2b9ca26044506f6abd7f95b7630052'),
 ('ImHex','1.38.1','https://github.com/WerWolv/ImHex/releases/download/v1.38.1/imhex-1.38.1-Windows-Portable-x86_64.zip','32520e57712894bc8304c4b01553223e7dda25852326184f99dfd72a09a80187'),
 ('Ghidra','12.1.4','https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip','ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db'),
 ('RTL433','25.12','https://github.com/merbanan/rtl_433/releases/download/25.12/rtl_433-win-x64-25.12.zip','ed42651d2a2a94f6419f7675955bd65449d8247e27822c65c363595b715b7de6'),
 ('SerialSniffer','1.2','https://github.com/DataAcquisitionTechnologies/serial-port-monitor/releases/download/v1.2/SerialSniffer_V1.2.exe','ed5447a548765cfbd206708fa452d2c67d20251ca5cf83f9ca2fb075d6efc932'),
 ('Packetry','0.5.0','https://github.com/greatscottgadgets/packetry/releases/download/v0.5.0/Packetry-Installer-for-Windows.zip','63b4bb880b188a0cd3003f6450bca1137dbf60cd76f5f823b4ba5b11d7521e81'),
 ('Sigrok','0.7.2','https://sigrok.org/download/binary/sigrok-cli/sigrok-cli-0.7.2-x86_64-installer.exe',''),
 ('PulseView','0.4.2','https://sigrok.org/download/binary/pulseview/pulseview-0.4.2-64bit-static-release-installer.exe',''),
 ('GIMP','3.2.8','https://mirrors.ukfast.co.uk/sites/gimp.org/pub/gimp/v3.2/windows/gimp-3.2.8-setup.exe','1d78874295661d791eaf149982e9b3564888631ea29186da5ff99e8114020a5b'),
]
SOURCES={
 'ImageMagickMCP':('bthurlow/imagemagick-mcp','71ad5ec845ce4e20c3ea21025b8caf1aa29f1615'),
 'GIMP':('gimp-mcp/gimp-mcp','7325865385541a01aaf336ebc93b00332297f77f'),
 'Binwalk':('ReFirmLabs/binwalk','26713972e3f9f52dc37d4a421c4554b0bd9e82ef'),
 'Glasgow':('GlasgowEmbedded/glasgow','cc9a083c827ba729d390c925af2af1e07ee1de97'),
 'Lemon':('qingningmneg/LemonSerialMonitor','139de5373a28db3a9a378fa3560dafe947c60ff7'),
 'URH':('jopohl/urh','1403d92987cc3d01d41aff64250955ce455dabd2'),
 'PortSniffer':('enlyze/PortSniffer','acc298dbb4a387e03b3404c1812f60e245738d2b'),
}
def download(url,dest,expected=''):
    dest.parent.mkdir(parents=True,exist_ok=True)
    if not dest.exists():
        temp=dest.with_suffix(dest.suffix+'.part.'+str(os.getpid()))
        for attempt in range(3):
            try:
                session=requests.Session();session.mount('https://',requests.adapters.HTTPAdapter(max_retries=2))
                with session.get(url,stream=True,timeout=(30,45)) as res:
                    res.raise_for_status()
                    with temp.open('wb') as out:
                        for chunk in res.iter_content(1024*1024):out.write(chunk)
                temp.replace(dest)
                break
            except requests.RequestException:
                if attempt==2:raise
    digest=hashlib.file_digest(dest.open('rb'),'sha256').hexdigest()
    if expected and digest!=expected:raise ValueError('SHA256 incorreto: '+str(dest))
    return digest
def package(item):
    key,version,url,sha=item;folder=ROOT/key;target=folder/'app';target.mkdir(parents=True,exist_ok=True)
    archive=folder/'downloads'/url.rsplit('/',1)[1]
    digest=download(url,archive,sha)
    if archive.suffix=='.zip':
        with zipfile.ZipFile(archive) as z:z.extractall(target)
    elif archive.suffix=='.7z':
        subprocess.run([str(ensure_7zip()),'x',str(archive),'-o'+str(target),'-y'],check=True,capture_output=True,timeout=180)
    elif key in ('Sigrok','PulseView'):
        # Extract NSIS; no registry changes, elevation or driver installation.
        subprocess.run([str(ensure_7zip()),'x',str(archive),'-o'+str(target),'-y'],check=True,capture_output=True,timeout=180)
    elif key=='GIMP':
        env=os.environ.copy();env['__COMPAT_LAYER']='RunAsInvoker'
        subprocess.run([str(archive),'/CURRENTUSER','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/DIR='+str(target)],env=env,check=True,timeout=600,creationflags=0x08000000)
    else:
        import shutil;shutil.copy2(archive,target/'SerialSniffer.exe')
    (folder/'instalacao.json').write_text(json.dumps(dict(version=version,url=url,sha256=digest,verified_publisher_digest=bool(sha)),indent=2),encoding='utf-8')
    return key+' instalado'

def ensure_7zip():
    folder=ROOT/'_Runtime'/'7zip';exe=folder/'full'/'7z.exe'
    if exe.exists():return exe
    download('https://github.com/ip7z/7zip/releases/download/26.05/7zr.exe',folder/'7zr.exe','9bf582b894dfa665f852d7e9112b02290a1c303c2d95a21fcdc41ffcb03143b7')
    setup=folder/'7z2605-x64.exe'
    download('https://github.com/ip7z/7zip/releases/download/26.05/7z2605-x64.exe',setup,'')
    # Release digest obtained from GitHub's official metadata.
    meta=requests.get('https://api.github.com/repos/ip7z/7zip/releases/tags/26.05',timeout=30).json()
    expected=next(a['digest'].split(':')[1] for a in meta['assets'] if a['name']==setup.name)
    download('',setup,expected)
    subprocess.run([str(folder/'7zr.exe'),'x',str(setup),'-o'+str(exe.parent),'-y'],check=True,capture_output=True,timeout=60)
    return exe
def source(item):
    key,(repo,commit)=item;folder=ROOT/key
    archive=folder/'downloads'/(commit+'.zip')
    digest=download('https://codeload.github.com/'+repo+'/zip/'+commit,archive)
    target=folder/'source';target.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as z:z.extractall(target)
    (folder/'fonte.json').write_text(json.dumps(dict(repository=repo,commit=commit,sha256=digest),indent=2),encoding='utf-8')
    return key+' fonte incluída (não equivale a executável instalado)'
if __name__=='__main__':
    bench_catalog.provision(ROOT)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        tasks=[pool.submit(package,p) for p in PACKAGES]+[pool.submit(source,p) for p in SOURCES.items()]
        for future in concurrent.futures.as_completed(tasks):
            try:print(future.result(),flush=True)
            except Exception as exc:print('ERRO: '+str(exc),flush=True)
