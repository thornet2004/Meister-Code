"""Arranca servidores Python externos com as extensões .pth do runtime local."""
import os,runpy,site,sys
from pathlib import Path
packages=Path(sys.argv[1]).resolve()
site.addsitedir(str(packages))
handles=[]
for folder in (packages/'pywin32_system32',packages/'libusb_package'):
    if os.name=='nt' and folder.is_dir():handles.append(os.add_dll_directory(str(folder)))
script=sys.argv[2];sys.argv=sys.argv[2:]
for stream in (sys.stdin,sys.stdout,sys.stderr):
    if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='replace')
runpy.run_path(script,run_name='__main__')
