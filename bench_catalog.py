"""Inventário da bancada; consultar não instala nem liga a equipamento."""
from pathlib import Path
import json

# id, nome, grupo, origem, pacote Python / executável, requisito externo
CATALOG = [
 ('ImageMagick','ImageMagick','Imagem','ImageMagick/ImageMagick','','magick.exe',''),
 ('ImageMagickMCP','ImageMagick MCP','Imagem','bthurlow/imagemagick-mcp','','','Servidor MCP original compilado localmente: 57 operações de edição, composição, texto e conversão.'),
 ('Pillow','Pillow','Imagem','python-pillow/Pillow','PIL','',''),
 ('Rembg','Remoção de fundo · rembg','Imagem','danielgatis/rembg','rembg','','Modelo ONNX descarregado na primeira utilização.'),
 ('GIMP','GIMP + MCP','Imagem','gimp-mcp/gimp-mcp','','gimp-console-3.exe','Editor e plugin MCP precisam de estar abertos para editar documentos GIMP.'),
 ('Serial','Portas série · pySerial','Eletrónica','pyserial/pyserial','serial','','Adaptador e driver da porta COM.'),
 ('Sigrok','sigrok-cli + descodificadores','Eletrónica','sigrokproject/sigrok-cli','','sigrok-cli.exe','Driver compatível do analisador lógico (WinUSB, conforme equipamento).'),
 ('PulseView','PulseView','Eletrónica','sigrokproject/pulseview','','pulseview.exe','Driver compatível do analisador lógico.'),
 ('SerialSniffer','SerialSniffer','Eletrónica','DataAcquisitionTechnologies/serial-port-monitor','','SerialSniffer.exe','Para intercalar outra aplicação: par COM virtual com0com e configuração das portas.'),
 ('BusPirate','Bus Pirate · terminal série','Eletrónica','DangerousPrototypes/BusPirate5-firmware','serial','','Selecionar porta, baud rate e protocolo da revisão do Bus Pirate; não instala firmware.'),
 ('PyFtdi','FTDI · I²C / SPI / GPIO','Eletrónica','eblot/pyftdi','pyftdi','','FTDI compatível + libusb/WinUSB. Windows não é oficialmente suportado pelo projeto.'),
 ('Modbus','Modbus RTU / ASCII / TCP','Protocolos','pymodbus-dev/pymodbus','pymodbus','','Interface RS485/RS232 ou endereço TCP.'),
 ('CAN','CAN + cantools','Protocolos','hardbyte/python-can','can','','Interface CAN e respetivo driver; inclui backend virtual para testes.'),
 ('VISA','Osciloscópios · VISA / SCPI','Protocolos','pyvisa/pyvisa-py','pyvisa','','Endereço VISA e comandos SCPI compatíveis com o instrumento.'),
 ('Wireshark','Wireshark / TShark / USBPcap','Protocolos','wireshark/wireshark','','tshark.exe','Captura USB exige driver USBPcap instalado; não é instalado automaticamente.'),
 ('Flashrom','flashrom · CH341A','Firmware','flashrom/flashrom','','flashrom.exe','Executável Windows compatível + driver CH341A; confirmar tensão e pinagem antes de escrever.'),
 ('OpenOCD','OpenOCD · JTAG / SWD','Firmware','xpack-dev-tools/openocd-xpack','','openocd.exe','Adaptador, driver e configuração do alvo.'),
 ('ImHex','ImHex','Firmware','WerWolv/ImHex','','imhex.exe',''),
 ('Ghidra','Ghidra','Firmware','NationalSecurityAgency/ghidra','','ghidraRun.bat','JDK 21+ compatível com esta versão; análises disponíveis no REA.'),
 ('Glasgow','Glasgow','Hardware avançado','GlasgowEmbedded/glasgow','glasgow','glasgow.exe','Placa Glasgow, driver USB e toolchain para compilar gateware.'),
 ('Cynthion','Cynthion · software de controlo','Hardware avançado','greatscottgadgets/cynthion','cynthion','cynthion.exe','Hardware Cynthion e driver USB; não atualiza firmware automaticamente.'),
 ('Packetry','Packetry · Cynthion','Hardware avançado','greatscottgadgets/packetry','','packetry.exe','Hardware Cynthion e driver USB.'),
 ('RTL433','rtl_433','Hardware avançado','merbanan/rtl_433','','rtl_433.exe','Receptor SDR compatível e driver USB.'),
 ('Lemon','Lemon Serial Monitor','Drivers opcionais','qingningmneg/LemonSerialMonitor','','LemonSerialMonitor.exe','O instalador oficial fica em Lemon/instalador e não é executado pela app (driver de kernel com assinatura de teste: mexe na segurança do Windows). Corre-o tu e depois aponta «Configurar executável» para o LemonSerialMonitor.exe.'),
 ('URH','Universal Radio Hacker','Drivers opcionais','jopohl/urh','urh','urh.exe','Projeto arquivado; SDR e backend compatível.'),
 ('PortSniffer','PortSniffer','Drivers opcionais','enlyze/PortSniffer','','PortSniffer-Tool.exe','Programa e driver na pasta; instalar o driver (PortSniffer-Tool.exe /install, com administrador) fica a cargo do utilizador.'),
]

def runtime(root):
    return next((root/'_Runtime'/'python').glob('*/python.exe'), root/'_Runtime'/'python'/'python.exe')

def executable(folder, name):
    settings = folder/'configuracao.json'
    if settings.is_file():
        try:
            value=json.loads(settings.read_text(encoding='utf-8')).get('executable','')
            if value and Path(value).is_file(): return Path(value)
        except (ValueError,OSError): pass
    if name:
        sdk=folder.parent/'_Runtime'/'site-packages'/'bin'/name
        if sdk.is_file():return sdk
        matches=sorted((folder/'app').rglob(name)) if (folder/'app').is_dir() else []
        if matches:return matches[0]
        # GIMP's console executable name can include the release suffix.
        if folder.name=='GIMP':
            matches=list((folder/'app').rglob('gimp-console-*.exe'))
            if matches:return matches[0]
    return None

def inventory(root=None):
    if root is None:
        import config
        root=config.application_root()/'Ferramentas'
    root=Path(root)
    from importlib.metadata import distributions
    versions={d.metadata.get('Name','').lower().replace('-','_'):d.version for d in distributions(path=[str(root/'_Runtime'/'site-packages')])}
    package_names={'Pillow':'pillow','Serial':'pyserial','BusPirate':'pyserial','PyFtdi':'pyftdi','Modbus':'pymodbus','CAN':'python_can','VISA':'pyvisa','Rembg':'rembg','Glasgow':'glasgow','URH':'urh','Cynthion':'cynthion'}
    result=[]
    for key,name,group,repo,module,binary,note in CATALOG:
        folder=root/key
        exe=executable(folder,binary)
        module_ok=bool(module and ((root/'_Runtime'/'site-packages'/module).is_dir()))
        ready=module_ok or bool(exe)
        backend='native'
        if key=='ImageMagickMCP':ready=bool(executable(root/'ImageMagick','magick.exe')) and any((folder/'source').glob('*/dist/index.js'))
        if key=='Rembg' and (folder/'models/u2netp.onnx').exists():note='Modelo u2netp instalado localmente. Inclui pré-visualização com transparência.'
        result.append(dict(key=key,name=name,category=group,source='https://github.com/'+repo,
            path=str(folder), installed=ready,status='Instalado' if ready else 'Integração preparada · dependência em falta',
            note=note,executable=str(exe or ''),backend=backend,module=module,version=_version(folder) or versions.get(package_names.get(key,''),''),
            source_installed=(folder/'source').is_dir(), manifest=(folder/'ferramenta.json').is_file()))
    return result

def _version(folder):
    try:return json.loads((folder/'instalacao.json').read_text(encoding='utf-8')).get('version','')
    except (ValueError,OSError):return ''

def provision(root=None):
    """Usado pelo instalador explícito; não substitui configurações existentes."""
    if root is None:
        import config
        root=config.application_root()/'Ferramentas'
    root=Path(root)
    for key,name,group,repo,module,binary,note in CATALOG:
        folder=root/key;folder.mkdir(parents=True,exist_ok=True)
        manifest=folder/'ferramenta.json'
        if not manifest.exists():
            manifest.write_text(json.dumps(dict(version=1,name=name,description=group+'. '+note,
                source='https://github.com/'+repo,enabled=True,approval='each',
                server=dict(adapter='bench',kind=key)),ensure_ascii=False,indent=2),encoding='utf-8')
        settings=folder/'configuracao.json'
        if not settings.exists():settings.write_text('{"executable": ""}',encoding='utf-8')
