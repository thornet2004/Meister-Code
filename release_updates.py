"""Explicit release checks/downloads. No automatic execution or invented feed."""
from __future__ import annotations
import hashlib,json,os,re,threading,time,uuid
from pathlib import Path
from urllib.parse import urlsplit
import requests,config
from app_version import VERSION
from coding_tools import atomic

MAX_SETUP=256*1024*1024
def version(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}',value):raise ValueError('Versão deve usar major.minor.patch.')
    return tuple(map(int,value.split('.')))
def https(url):
    p=urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.fragment or p.query:raise ValueError('Usa um endereço HTTPS sem credenciais, parâmetros ou fragmentos.')
    return url
def fetch(url):
    for _ in range(5):
        response=requests.get(https(url),timeout=(10,30),stream=True,allow_redirects=False)
        if response.status_code in (301,302,303,307,308):
            from urllib.parse import urljoin
            target=urljoin(url,response.headers.get('Location',''));response.close();url=https(target);continue
        try:response.raise_for_status()
        except Exception:response.close();raise ValueError('Falha HTTP ao obter a release.') from None
        return response
    raise ValueError('Demasiados redirecionamentos.')
def manifest(data):
    if not isinstance(data,dict) or data.get('schema')!=1:raise ValueError('Manifesto requer schema: 1.')
    version(data.get('version'));url=https(data.get('url',''));sha=data.get('sha256','')
    if not re.fullmatch(r'[a-fA-F0-9]{64}',sha):raise ValueError('SHA-256 inválido.')
    if type(data.get('size')) is not int or not 1<=data['size']<=MAX_SETUP:raise ValueError('Tamanho de instalador inválido.')
    if data.get('platform')!='windows-x64':raise ValueError('Plataforma de release incompatível.')
    return dict(schema=1,version=data['version'],url=url,sha256=sha.lower(),size=data['size'],platform='windows-x64',notes=str(data.get('notes',''))[:4000])

class Updates:
    def __init__(self):self.lock=threading.Lock();self.busy=False;self.release=None;self.download=None
    def check(self,url):
        with self.lock:
            if self.busy:raise ValueError('Já existe uma operação de atualização.')
            self.busy=True;self.release=None;self.download=None
        try:
            with fetch(url) as response:
                raw=bytearray()
                for chunk in response.iter_content(16384):
                    raw.extend(chunk)
                    if len(raw)>65536:raise ValueError('Manifesto demasiado grande.')
            data=manifest(json.loads(raw));self.release=data
            return dict(current=VERSION,available=version(data['version'])>version(VERSION),release=data)
        finally:self.busy=False
    def stage(self):
        with self.lock:
            if self.busy:raise ValueError('Já existe uma operação de atualização.')
            if not self.release or version(self.release['version'])<=version(VERSION):raise ValueError('Verifica primeiro uma versão mais recente.')
            self.busy=True;release=dict(self.release);self.download=None
        part=None
        try:
            folder=config.config_dir()/'updates';folder.mkdir(exist_ok=True);part=folder/(uuid.uuid4().hex+'.part')
            sha=hashlib.sha256();size=0;deadline=time.monotonic()+300
            with fetch(release['url']) as response,part.open('xb') as out:
                for chunk in response.iter_content(65536):
                    size+=len(chunk)
                    if size>release['size'] or time.monotonic()>deadline:raise ValueError('Download excedeu o tamanho ou tempo permitido.')
                    sha.update(chunk);out.write(chunk)
            if size!=release['size'] or sha.hexdigest()!=release['sha256']:raise ValueError('O instalador não corresponde ao tamanho/SHA-256 do manifesto.')
            target=folder/('Meister-IA-IDE-'+release['version']+'-Setup.exe');os.replace(part,target)
            atomic(target.with_suffix('.json'),json.dumps(release).encode());self.download=dict(path=str(target),**release);return dict(path=str(target),version=release['version'],verified=True)
        finally:
            try:
                if part:part.unlink(missing_ok=True)
            finally:self.busy=False
    def ready(self):
        data=self.download
        if not data:raise ValueError('Descarrega e verifica o instalador primeiro.')
        p=Path(data['path'])
        if p.stat().st_size!=data['size'] or hashlib.sha256(p.read_bytes()).hexdigest()!=data['sha256']:raise ValueError('O instalador foi alterado depois da verificação.')
        return p
