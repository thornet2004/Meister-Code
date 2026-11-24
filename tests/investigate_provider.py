"""Explicit synthetic live probe; never reads or sends chat/project contents."""
import json,sys,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import config,providers
from coding_tools import read_json
from providers import openrouter

def main():
    cfg=read_json(config.config_path());selection=cfg['chat'];p=next(p for p in cfg['providers'] if p['id']==selection['provider_id']);m=next(m for m in p['models'] if m['id']==selection['model_id']);assert p['kind']=='openrouter';real=openrouter._chat_post;observations=[]
    def request(*args,**kwargs):
        response=real(*args,**kwargs);original=response.iter_lines;body=kwargs.get('json',{});row=dict(max_tokens=body.get('max_tokens'),tool_choice=body.get('tool_choice'),finish_reason=None);observations.append(row)
        def lines(*a,**kw):
            for line in original(*a,**kw):
                if line and line.startswith(b'data:'):
                    try:
                        event=json.loads(line[5:].strip())
                        for choice in event.get('choices',[]):
                            if choice.get('finish_reason'):row['finish_reason']=choice['finish_reason']
                        if event.get('usage'):row['usage']=event['usage']
                    except (ValueError,TypeError):pass
                yield line
        response.iter_lines=lines;return response
    tool=dict(type='function',function=dict(name='diagnostico_eco',description='Devolve o token recebido; não acede ao computador.',parameters=dict(type='object',properties=dict(token=dict(type='string')),required=['token'])))
    result=dict(kind=p['kind'],model=m['id'],rounds=[],observations=observations);adapter=providers.get_chat_adapter(p['kind'])
    with patch('providers.openrouter._chat_post',side_effect=request):
        for n in range(10):
            token='probe-'+uuid.uuid4().hex[:12];messages=[dict(role='system',content='Ensaio sintético de ferramentas. Chama diagnostico_eco com o token pedido. Depois responde apenas com esse token.'),dict(role='user',content=token)];first=adapter(p,m,messages,[tool],{'_on_delta':lambda s:None,'max_tokens':256});calls=first.get('tool_calls') or []
            if len(calls)!=1 or calls[0].get('name')!='diagnostico_eco' or calls[0].get('arguments')!={'token':token}:
                result.update(state='failed',stage='tool',round=n+1,observed_content=first.get('content','')[:2000],tool_count=len(calls));break
            messages.extend([first['raw_message'],dict(role='tool',tool_call_id=calls[0]['id'],content=json.dumps(dict(token=token)))]);second=adapter(p,m,messages,None,{'_on_delta':lambda s:None,'max_tokens':256})
            if token not in second.get('content','') or second.get('tool_calls'):
                result.update(state='failed',stage='final',round=n+1,observed_content=second.get('content','')[:2000]);break
            result['rounds'].append(dict(round=n+1,state='passed'))
        else:result['state']='passed'
    target=Path(__file__).with_name('provider-investigation-result.json');target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
