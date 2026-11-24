import sys,json,tempfile,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import api,config
from bench_catalog import runtime
root=Path(__file__).resolve().parents[1];app=api.Api()
try:
 with tempfile.TemporaryDirectory() as temp:
  folder=Path(temp);src=folder/'input.png';out=folder/'out.png'
  subprocess.run([str(runtime(root/'Ferramentas')),'-c',"import sys;sys.path.insert(0,sys.argv[1]);from PIL import Image,ImageDraw;im=Image.new('RGB',(96,96),'white');d=ImageDraw.Draw(im);d.ellipse((24,12,72,76),fill='red');im.save(sys.argv[2])",str(root/'Ferramentas/_Runtime/site-packages'),str(src)],check=True)
  row=next(r for r in app.get_folder_tools()['tools'] if Path(r['path']).name=='Rembg')
  result=app._folder_tools.execute(config.load_config(),row['id'],'imagem_editar',dict(path=str(src),output=str(out),operation='remove_background'),lambda *a:True)
  assert not result.get('isError'),result
  meta=json.loads(next(c['text'] for c in result['content'] if c['type']=='text'));assert meta['alpha'];print('PASS rembg CPU + modelo local: PNG RGBA e preview MCP.',flush=True)
  info=app._folder_tools.execute(config.load_config(),row['id'],'imagem_info',dict(path=str(out)),lambda *a:True)
  value=json.loads(info['content'][0]['text']);assert value['alpha_extrema'][0]<10 and value['alpha_extrema'][1]>245,value
  row=next(r for r in app.get_folder_tools()['tools'] if Path(r['path']).name=='ImageMagickMCP');result=app._folder_tools.execute(config.load_config(),row['id'],'info',dict(input=str(out)),lambda *a:True);assert not result.get('isError'),result;print('PASS servidor MCP original ImageMagick: info imagem editada.',flush=True)
finally:app._folder_tools.close();app._mcp.close()
