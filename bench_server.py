"""Adaptadores MCP da bancada, executados no Python portátil isolado."""
from pathlib import Path
import base64,io,json,os,subprocess,sys,time

ROOT=Path(sys.argv[1]).resolve().parent if len(sys.argv)>1 else Path(__file__).parent/'Ferramentas'
sys.path.insert(0,str(ROOT/'_Runtime'/'site-packages'))
import bench_catalog

def spec(name,description,props=None,required=None):
    return dict(name=name,description=description,inputSchema=dict(type='object',properties=props or {},required=required or [],additionalProperties=False))
S={'type':'string'};I={'type':'integer'};B={'type':'boolean'}
def definitions(kind):
    common=[spec('estado','Estado real do software, caminhos e dependências; não liga a hardware.')]
    if kind in ('Pillow','Rembg','ImageMagick','ImageMagickMCP'):
        common += [spec('imagem_info','Dimensões, formato e transparência de uma imagem.',{'path':S},['path']),
            spec('imagem_editar','Transforma uma imagem. Nunca substitui o original. Devolve pré-visualização MCP.',
                 dict(path=S,output=S,operation={'type':'string','enum':['resize','crop','rotate','convert','grayscale','remove_background']},width=I,height=I,x=I,y=I,angle={'type':'number'}),['path','output','operation'])]
    if kind in ('Serial','BusPirate'):
        common += [spec('portas','Lista portas COM com VID/PID e números de série.'),
            spec('serial_transferir','Abre uma porta, escreve opcionalmente bytes e captura até 10 segundos. Não é captura passiva de outra aplicação. Bus Pirate: usar comandos compatíveis com a revisão.',
                dict(port=S,baudrate=I,write_hex=S,seconds={'type':'number'},max_bytes=I,dtr=B,rts=B),['port'])]
    if kind=='PyFtdi':
        common += [spec('ftdi_listar','Lista interfaces FTDI via libusb.'),
            spec('i2c_transferir','Transferência I²C via FTDI MPSSE; exige driver libusb e URL ftdi.',dict(url=S,address=I,write_hex=S,read_bytes=I,frequency=I),['url','address']),
            spec('spi_transferir','Transferência SPI FTDI MPSSE.',dict(url=S,write_hex=S,read_bytes=I,cs=I,mode=I,frequency=I),['url'])]
    if kind=='CAN':
        common += [spec('can_interfaces','Deteta interfaces CAN configuradas.'),
            spec('can_transferir','Envia opcionalmente uma frame CAN e captura frames. virtual_echo permite teste sem hardware.',dict(interface=S,channel=S,arbitration_id=I,data_hex=S,extended=B,bitrate=I,seconds={'type':'number'},virtual_echo=B),['interface','channel']),
            spec('dbc_decode','Descodifica uma frame com um ficheiro DBC.',dict(path=S,frame_id=I,data_hex=S),['path','frame_id','data_hex'])]
    if kind=='Modbus':
        common += [spec('modbus_ler','Lê holding/input registers ou coils/discrete inputs via TCP, RTU ou ASCII. Só leitura.',dict(transport={'type':'string','enum':['tcp','rtu','ascii']},host=S,port=I,serial_port=S,baudrate=I,device_id=I,address=I,count=I,table={'type':'string','enum':['holding','input','coils','discrete']}),['transport','address'])]
    if kind=='VISA':
        common += [spec('visa_recursos','Lista instrumentos VISA, backend pyvisa-py.'),spec('scpi_query','Envia uma query SCPI e lê a resposta. Confirmar comandos do modelo do instrumento.',dict(resource=S,command=S,timeout_ms=I),['resource','command'])]
    if kind=='GIMP':
        common += [spec('gimp_chamar','Chama o plugin gimp-mcp original em localhost:9877. Requer GIMP aberto e Tools → MCP → Start Server.',dict(command=S,params={'type':'object','additionalProperties':True}),['command'])]
    common += [spec('executar_cli','Executa argumentos no executável configurado desta ferramenta. Sem shell. Máximo 45 segundos; não serve para trabalhos/gui de longa duração.',dict(args={'type':'array','items':S,'maxItems':128},timeout=I),['args'])]
    return common

def bounded(value,default,low,high):return max(low,min(high,float(default if value is None else value)))
def run(kind,name,a):
    item=next(r for r in bench_catalog.inventory(ROOT) if r['key']==kind)
    if name=='estado':return item
    if name in ('ftdi_listar','i2c_transferir','spi_transferir','visa_recursos','scpi_query'):
        import libusb_package,usb.backend.libusb1
        usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
    if name=='executar_cli':
        if not item['executable']:raise ValueError('Executável não instalado/configurado. Abrir Ferramentas → Configurar executável.')
        args=a['args']
        if not isinstance(args,list) or len(args)>128 or not all(isinstance(x,str) and '\x00' not in x for x in args):raise ValueError('Argumentos inválidos.')
        env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'_Runtime'/'site-packages')
        env['PATH']=str(ROOT/'_Runtime'/'site-packages'/'libusb_package')+os.pathsep+env.get('PATH','')
        command=[item['executable'],*args]
        if item.get('backend')=='wsl':
            opts=json.loads((ROOT/kind/'configuracao.json').read_text(encoding='utf-8'))
            import ntpath
            translated=[]
            for arg in args:
                if ntpath.splitdrive(arg)[0]:
                    converted=subprocess.run([item['executable'],'-d',opts['distribution'],'--exec','wslpath','-u',arg],capture_output=True,check=True,timeout=10)
                    arg=converted.stdout.decode('utf-8').strip()
                translated.append(arg)
            command=[item['executable'],'-d',opts['distribution'],'--exec',opts['command'],*translated]
        process=subprocess.run(command,env=env,capture_output=True,timeout=bounded(a.get('timeout'),30,1,45),creationflags=0x08000000 if os.name=='nt' else 0)
        return dict(exit_code=process.returncode,stdout=process.stdout[-100000:].decode('utf-8','replace'),stderr=process.stderr[-20000:].decode('utf-8','replace'))
    if name.startswith('imagem_'):
        from PIL import Image,ImageOps
        path=Path(a['path']).resolve()
        with Image.open(path) as original:
            original.load()
            if name=='imagem_info':return dict(path=str(path),format=original.format,size=list(original.size),mode=original.mode,alpha='A' in original.getbands(),alpha_extrema=original.getchannel('A').getextrema() if 'A' in original.getbands() else None)
            output=Path(a['output']).resolve()
            if output==path or output.exists():raise ValueError('Escolhe um novo ficheiro de saída; não substitui ficheiros existentes.')
            op=a['operation'];im=ImageOps.exif_transpose(original)
            if op=='resize':im=im.resize((int(bounded(a.get('width'),im.width,1,16000)),int(bounded(a.get('height'),im.height,1,16000))),Image.Resampling.LANCZOS)
            elif op=='crop':
                x=int(a.get('x',0));y=int(a.get('y',0));w=int(bounded(a.get('width'),im.width,1,16000));h=int(bounded(a.get('height'),im.height,1,16000));im=im.crop((x,y,x+w,y+h))
            elif op=='rotate':im=im.convert('RGBA').rotate(float(a.get('angle',0)),expand=True,resample=Image.Resampling.BICUBIC)
            elif op=='grayscale':im=ImageOps.grayscale(im)
            elif op=='remove_background':
                os.environ['U2NET_HOME']=str(ROOT/'Rembg'/'models')
                os.environ.setdefault('OMP_NUM_THREADS','2')
                os.environ.setdefault('NUMBA_NUM_THREADS','2')
                # This operation does not use alpha matting; eager compilation
                # of unused pymatting kernels would exceed MCP's response limit.
                os.environ['NUMBA_DISABLE_JIT']='1'
                from rembg import remove,new_session
                im=remove(im,session=new_session('u2netp'),alpha_matting=False)
            elif op!='convert':raise ValueError('Operação desconhecida.')
            output.parent.mkdir(parents=True,exist_ok=True)
            if output.suffix.lower() in ('.jpg','.jpeg'):im=im.convert('RGB')
            # Exclusive creation prevents overwriting attachments or concurrent results.
            with output.open('xb') as dest:im.save(dest,format=Image.registered_extensions().get(output.suffix.lower(),'PNG'))
            preview=im.copy();preview.thumbnail((640,640));buf=io.BytesIO();preview.save(buf,format='PNG')
            return {'_image':base64.b64encode(buf.getvalue()).decode(),'path':str(output),'size':list(im.size),'alpha':'A' in im.getbands()}
    if name=='portas':
        from serial.tools.list_ports import comports
        return [dict(port=p.device,description=p.description,vid=p.vid,pid=p.pid,serial=p.serial_number) for p in comports()]
    if name=='serial_transferir':
        import serial
        duration=bounded(a.get('seconds'),1,0.05,10);limit=int(bounded(a.get('max_bytes'),65536,1,65536))
        with serial.serial_for_url(a['port'],baudrate=int(a.get('baudrate',115200)),timeout=.1) as port:
            if 'dtr' in a:port.dtr=a['dtr']
            if 'rts' in a:port.rts=a['rts']
            data=bytes.fromhex(a.get('write_hex',''));written=port.write(data) if data else 0
            end=time.monotonic()+duration;received=bytearray()
            while time.monotonic()<end and len(received)<limit:received.extend(port.read(min(port.in_waiting or 1,limit-len(received))))
            return dict(written=written,bytes=len(received),hex=received.hex(),text=received.decode('utf-8','replace'))
    if name=='ftdi_listar':
        from pyftdi.ftdi import Ftdi
        return [str(x) for x in Ftdi.list_devices()]
    if name=='i2c_transferir':
        from pyftdi.i2c import I2cController
        ctl=I2cController()
        try:
            ctl.configure(a['url'],frequency=int(a.get('frequency',100000)))
            port=ctl.get_port(int(a['address']));data=port.exchange(bytes.fromhex(a.get('write_hex','')),int(bounded(a.get('read_bytes'),0,0,65536)))
            return dict(hex=bytes(data).hex())
        finally:ctl.terminate()
    if name=='spi_transferir':
        from pyftdi.spi import SpiController
        ctl=SpiController()
        try:
            ctl.configure(a['url']);port=ctl.get_port(cs=int(a.get('cs',0)),freq=int(a.get('frequency',1000000)),mode=int(a.get('mode',0)))
            data=port.exchange(bytes.fromhex(a.get('write_hex','')),int(bounded(a.get('read_bytes'),0,0,65536)))
            return dict(hex=bytes(data).hex())
        finally:ctl.terminate()
    if name=='can_interfaces':
        import can
        return can.detect_available_configs()
    if name=='can_transferir':
        import can
        opts=dict(interface=a['interface'],channel=a['channel'])
        if 'bitrate' in a:opts['bitrate']=a['bitrate']
        if a['interface']=='virtual':opts['receive_own_messages']=bool(a.get('virtual_echo'))
        with can.Bus(**opts) as bus:
            if 'arbitration_id' in a:bus.send(can.Message(arbitration_id=a['arbitration_id'],data=bytes.fromhex(a.get('data_hex','')),is_extended_id=bool(a.get('extended'))),timeout=1)
            end=time.monotonic()+bounded(a.get('seconds'),1,.05,10);frames=[]
            while time.monotonic()<end and len(frames)<1000:
                frame=bus.recv(timeout=min(.1,max(0,end-time.monotonic())))
                if frame:frames.append(dict(id=frame.arbitration_id,data_hex=frame.data.hex(),extended=frame.is_extended_id,timestamp=frame.timestamp))
            return dict(frames=frames)
    if name=='dbc_decode':
        import cantools
        db=cantools.database.load_file(a['path']);return db.decode_message(a['frame_id'],bytes.fromhex(a['data_hex']))
    if name=='modbus_ler':
        from pymodbus.client import ModbusTcpClient,ModbusSerialClient
        from pymodbus import FramerType
        if a['transport']=='tcp':client=ModbusTcpClient(a.get('host','127.0.0.1'),port=int(a.get('port',502)),timeout=3)
        else:client=ModbusSerialClient(a['serial_port'],baudrate=int(a.get('baudrate',9600)),framer=FramerType.ASCII if a['transport']=='ascii' else FramerType.RTU,timeout=3)
        try:
            if not client.connect():raise ValueError('Não foi possível ligar ao dispositivo Modbus.')
            method={'holding':'read_holding_registers','input':'read_input_registers','coils':'read_coils','discrete':'read_discrete_inputs'}[a.get('table','holding')]
            count=int(bounded(a.get('count'),1,1,125));result=getattr(client,method)(a['address'],count=count,device_id=int(a.get('device_id',1)))
            if result.isError():raise ValueError(str(result))
            return dict(registers=getattr(result,'registers',None),bits=getattr(result,'bits',None))
        finally:client.close()
    if name in ('visa_recursos','scpi_query'):
        import pyvisa
        manager=pyvisa.ResourceManager('@py')
        try:
            if name=='visa_recursos':return list(manager.list_resources())
            with manager.open_resource(a['resource']) as resource:
                resource.timeout=int(bounded(a.get('timeout_ms'),3000,100,15000))
                if a['resource'].endswith('::SOCKET'):
                    resource.read_termination='\n';resource.write_termination='\n'
                return dict(response=resource.query(a['command']))
        finally:manager.close()
    if name=='gimp_chamar':
        import socket
        payload=json.dumps(dict(type=a['command'],params=a.get('params',{}))).encode()
        with socket.create_connection(('127.0.0.1',9877),timeout=5) as sock:
            sock.sendall(payload);sock.settimeout(15);data=bytearray()
            while len(data)<8*1024*1024:
                chunk=sock.recv(65536)
                if not chunk:break
                data.extend(chunk)
                try:return json.loads(data)
                except ValueError:pass
        raise ValueError('Resposta inválida do plugin GIMP.')
    raise ValueError('Operação indisponível nesta ferramenta.')

def main():
    for stream in (sys.stdin,sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='replace')
    kind=Path(sys.argv[1]).name;allowed={t['name'] for t in definitions(kind)}
    for line in sys.stdin:
        try:
            msg=json.loads(line)
            if 'id' not in msg:continue
            method=msg.get('method')
            if method=='initialize':result=dict(protocolVersion='2025-11-25',capabilities={'tools':{}},serverInfo={'name':'studio-bench-'+kind,'version':'1.0'})
            elif method=='server/discover':result=dict(resultType='complete',supportedVersions=['2026-07-28'],capabilities={'tools':{}},_meta={'io.modelcontextprotocol/serverInfo':{'name':'studio-bench-'+kind,'version':'1.0'}})
            elif method=='tools/list':result={'tools':definitions(kind)}
            elif method=='tools/call':
                try:
                    params=msg.get('params',{});name=params.get('name')
                    if name not in allowed:raise ValueError('Operação não pertence a esta ferramenta.')
                    value=run(kind,name,params.get('arguments') or {});image=value.pop('_image',None) if isinstance(value,dict) else None
                    content=[dict(type='text',text=json.dumps(value,ensure_ascii=False))]
                    if image:content.append(dict(type='image',mimeType='image/png',data=image))
                    result=dict(content=content,isError=False)
                except Exception as exc:result=dict(content=[dict(type='text',text=str(exc))],isError=True)
            else:
                print(json.dumps(dict(jsonrpc='2.0',id=msg['id'],error=dict(code=-32601,message='Método desconhecido'))),flush=True);continue
            print(json.dumps(dict(jsonrpc='2.0',id=msg['id'],result=result),ensure_ascii=False),flush=True)
        except Exception as exc:
            print(str(exc),file=sys.stderr,flush=True)
if __name__=='__main__':main()
