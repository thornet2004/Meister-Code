"""Validação real dos adaptadores instalados, sem depender de hardware ligado."""
import json,sys,tempfile,subprocess,socketserver,struct,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import api,config,bench_catalog
ROOT=Path(__file__).resolve().parents[1]
app=api.Api();report={}
def execute(key,operation,args=None):
    row=next(r for r in app._folder_tools.status(config.load_config()) if Path(r['path']).name==key)
    value=app._folder_tools.execute(config.load_config(),row['id'],operation,args or {},lambda *args:True)
    assert not value.get('isError'),(key,operation,value)
    return value
def value(result):return json.loads(next(p['text'] for p in result['content'] if p['type']=='text'))
class Modbus(socketserver.BaseRequestHandler):
    def handle(self):
        data=self.request.recv(1024);tid,protocol,length,unit=struct.unpack('>HHHB',data[:7]);function=data[7];address,count=struct.unpack('>HH',data[8:12]);body=bytes([function,count*2])+b''.join(struct.pack('>H',100+address+i) for i in range(count));self.request.sendall(struct.pack('>HHHB',tid,protocol,len(body)+1,unit)+body)
class SCPI(socketserver.BaseRequestHandler):
    def handle(self):
        data=self.request.recv(1024)
        if data.strip()==b'*IDN?':self.request.sendall(b'STUDIO,SIMULATOR,001,1.0\n')
try:
    inventory=app.get_tools_inventory();assert inventory['ok'],inventory
    for item in inventory['bench']:
        manifest=json.loads((Path(item['path'])/'ferramenta.json').read_text(encoding='utf-8'))
        if manifest['server'].get('adapter')!='bench':continue
        status=value(execute(item['key'],'estado'));assert status['key']==item['key']
    report['mcp_adapters_discovered']=len(inventory['bench'])
    with tempfile.TemporaryDirectory(prefix='bench-smoke-') as temp:
        folder=Path(temp);image=folder/'source.png';output=folder/'resized.png'
        script="import sys;sys.path.insert(0,sys.argv[1]);from PIL import Image;Image.new('RGBA',(80,40),(255,40,0,128)).save(sys.argv[2])"
        subprocess.run([str(bench_catalog.runtime(ROOT/'Ferramentas')),'-c',script,str(ROOT/'Ferramentas/_Runtime/site-packages'),str(image)],check=True)
        result=execute('Pillow','imagem_editar',dict(path=str(image),output=str(output),operation='resize',width=20,height=10))
        assert any(p['type']=='image' for p in result['content']),result
        media=[];clean=app._capture_mcp_images(result,media,folder/'meta',folder/'media')
        assert media and not any(p.get('data') for p in clean['content'])
        info=value(execute('Pillow','imagem_info',dict(path=str(output))))
        assert info['size']==[20,10] and info['alpha_extrema']==[128,128],info
        assert any(m['role']=='user' and isinstance(m['content'],list) for m in api._build_model_messages([dict(role='assistant',text='imagem',media=[dict(path=media[0]['path'],type='image')])],{},[]))
        report['image_edit_and_multimodal_preview']=True
        serial=value(execute('Serial','serial_transferir',dict(port='loop://',baudrate=115200,write_hex='010203aaff',seconds=.15)))
        assert serial['hex']=='010203aaff',serial;report['serial_loopback']=serial['hex']
        can=value(execute('CAN','can_transferir',dict(interface='virtual',channel='studio-test',arbitration_id=291,data_hex='0102',virtual_echo=True,seconds=.15)))
        assert can['frames'][0]['data_hex']=='0102',can;report['can_virtual']=True
        with socketserver.TCPServer(('127.0.0.1',0),Modbus) as server:
            t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
            try:
                modbus=value(execute('Modbus','modbus_ler',dict(transport='tcp',host='127.0.0.1',port=server.server_address[1],address=2,count=3)))
                assert modbus['registers']==[102,103,104],modbus;report['modbus_tcp_simulator']=True
            finally:server.shutdown()
        with socketserver.TCPServer(('127.0.0.1',0),SCPI) as server:
            t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
            try:
                scpi=value(execute('VISA','scpi_query',dict(resource='TCPIP0::127.0.0.1::'+str(server.server_address[1])+'::SOCKET',command='*IDN?')))
                assert 'SIMULATOR' in scpi['response'],scpi;report['scpi_tcp_simulator']=True
            finally:server.shutdown()
        for key,args,needle in [('ImageMagick',['-version'],'ImageMagick'),('Sigrok',['--version'],'sigrok-cli'),('OpenOCD',['--version'],'Open On-Chip'),('RTL433',['-V'],'rtl_433')]:
            res=value(execute(key,'executar_cli',dict(args=args)));assert needle.lower() in (res['stdout']+res['stderr']).lower(),(key,res)
            report[key+'_cli']=res['exit_code']
        demo=value(execute('Sigrok','executar_cli',dict(args=['--driver','demo','--samples','32','--channels','D0,D1','-O','csv'])))
        assert demo['exit_code']==0 and demo['stdout'],demo;report['sigrok_demo_capture']=True
    report['hardware_contacted']=False
    (ROOT/'tests/bench-smoke-result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
finally:
    app._folder_tools.close();app._mcp.close()
