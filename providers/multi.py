"""Adaptadores nativos de chat com ferramentas; normalização comum da app."""
from __future__ import annotations
import copy,json,re,uuid,time
from urllib.parse import quote,urlsplit
import requests
from .base import ProviderError
from . import openrouter

PRESETS={
 'openrouter':dict(label='OpenRouter',base_url='https://openrouter.ai/api/v1',requires_key=True),
 'openai':dict(label='OpenAI · Responses',base_url='https://api.openai.com/v1',requires_key=True),
 'anthropic':dict(label='Anthropic · Claude',base_url='https://api.anthropic.com/v1',requires_key=True),
 'google':dict(label='Google · Gemini',base_url='https://generativelanguage.googleapis.com/v1beta',requires_key=True),
 'ollama':dict(label='Ollama',base_url='http://localhost:11434/v1',requires_key=False),
 'lmstudio':dict(label='LM Studio',base_url='http://localhost:1234/v1',requires_key=False),
 # serviços na nuvem que falam o formato da OpenAI (só conversa); endereços das documentações oficiais, conferidos a 19/11/2026
 'together':dict(label='Together AI',base_url='https://api.together.ai/v1',requires_key=True),
 'fireworks':dict(label='Fireworks AI',base_url='https://api.fireworks.ai/inference/v1',requires_key=True),
 'deepinfra':dict(label='DeepInfra',base_url='https://api.deepinfra.com/v1/openai',requires_key=True),
 'cometapi':dict(label='CometAPI',base_url='https://api.cometapi.com/v1',requires_key=True),
 'apimart':dict(label='APIMart',base_url='https://api.apimart.ai/v1',requires_key=True),
 'openai-compatible':dict(label='Outro · API compatível com OpenAI',base_url='',requires_key=False),
}
def settings(provider):
    kind=provider['kind'];preset=PRESETS[kind];base=(provider.get('base_url') or preset['base_url']).strip().rstrip('/');key=(provider.get('api_key') or '').strip()
    parsed=urlsplit(base)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise ProviderError('URL do provedor inválido; usa uma base HTTP/HTTPS sem credenciais ou parâmetros no endereço.')
    if preset['requires_key'] and not key:raise ProviderError('Adiciona a chave de API deste provedor nas Configurações.')
    headers={'Content-Type':'application/json'}
    if kind=='anthropic':headers.update({'x-api-key':key,'anthropic-version':'2023-06-01'})
    elif kind=='google':headers['x-goog-api-key']=key
    elif key:headers['Authorization']='Bearer '+key
    return kind,base,key,headers

def request(provider,method,path,body=None,stream=False):
    _,base,key,headers=settings(provider)
    try:
        for attempt in range(3):
            try:response=requests.request(method,base+path,headers=headers,json=body,timeout=(15,300),stream=stream)
            except requests.ConnectTimeout:
                if attempt==2:raise
                time.sleep(.4*(attempt+1));continue
            if response.status_code in (429,502,503,504) and attempt<2:
                response.close();time.sleep(.4*(attempt+1));continue
            break
    except requests.RequestException as exc:raise ProviderError('Falha de ligação ao provedor: '+str(exc).replace(key,'[chave oculta]') if key else 'Falha de ligação ao provedor: '+str(exc)) from None
    if not response.ok:
        text=(response.text or '')[:3000]
        if key:text=text.replace(key,'[chave oculta]')
        status=response.status_code;response.close();raise ProviderError('Erro HTTP '+str(status)+' do provedor: '+text)
    return response

def events(response,cancel=None):
    for line in response.iter_lines(chunk_size=1):
        if cancel and cancel.is_set():return
        if not line or not line.startswith(b'data:'):continue
        value=line[5:].strip()
        if value==b'[DONE]':return
        try:data=json.loads(value)
        except ValueError:continue
        if data.get('error') or data.get('type') in ('error','response.failed'):
            raise ProviderError('O provedor interrompeu a geração: '+json.dumps(data.get('error') or data.get('response',{}).get('error') or data,ensure_ascii=False)[:1500])
        yield data

def usage(input_tokens=0,output_tokens=0,total=None):
    return dict(prompt_tokens=int(input_tokens or 0),completion_tokens=int(output_tokens or 0),total_tokens=int(total if total is not None else (input_tokens or 0)+(output_tokens or 0)))
def output(text,calls=None,native=None,tokens=None,cancelled=False,finish_reason=None):
    calls=calls or [];raw=dict(role='assistant',content=text or None)
    if calls:raw['tool_calls']=[dict(id=c['id'],type='function',function=dict(name=c['name'],arguments=json.dumps(c['arguments'],ensure_ascii=False))) for c in calls]
    if native:raw['_native']=native
    return dict(content=text,tool_calls=calls,raw_message=raw,usage=tokens or usage(),cancelled=cancelled,finish_reason=finish_reason)
def arguments(value):
    if isinstance(value,str):
        try:value=json.loads(value)
        except ValueError:raise ProviderError('O modelo devolveu argumentos de ferramenta incompletos ou inválidos.') from None
    if not isinstance(value,dict):raise ProviderError('Os argumentos de uma ferramenta têm de ser um objeto JSON.')
    return value
def image_data(url):
    match=re.fullmatch(r'data:(image/[a-z0-9.+-]+);base64,([A-Za-z0-9+/=\r\n]+)',url or '')
    if not match:raise ProviderError('Este provedor recebe imagens anexadas em base64; URL de imagem não suportado nesta mensagem.')
    return match.groups()
def text_parts(content):
    if isinstance(content,str):return [dict(type='text',text=content)] if content else []
    return content or []

def single_system(messages):
    """Junta as mensagens de sistema numa só, no início. A app acrescenta notas de sistema a meio (resumo da conversa,
    memória, hooks) e há modelos locais cujo modelo de conversa recusa isso («System message must be at the beginning»)."""
    if not any(m.get('role')=='system' for m in messages[1:]):return messages
    notes=[m['content'] for m in messages if m.get('role')=='system' and isinstance(m.get('content'),str) and m['content']]
    return ([dict(role='system',content='\n\n'.join(notes))] if notes else [])+[m for m in messages if m.get('role')!='system']

def compatible(provider,model,messages,tools=None,params=None):
    params=params or {}
    if provider.get('rig') and model.get('base_url'):provider={**provider,'base_url':model['base_url']}  # na rig cada modelo tem o seu servidor
    kind,base,key,headers=settings(provider)
    clean=[{k:v for k,v in m.items() if k in ('role','content','tool_calls','tool_call_id','name')} for m in messages]
    body=dict(model=model['id'],messages=single_system(clean))
    if tools:body.update(tools=tools,tool_choice='auto')
    options={**(model.get('defaults') or {}),**params}
    for k in ('temperature','max_tokens','top_p'):
        if k in options:body[k]=options[k]
    # Esforço de raciocínio: só para o servidor do próprio utilizador («Outro»), onde foi ensaiado (llama.cpp); os serviços da nuvem podem recusar o campo.
    if kind=='openai-compatible' and options.get('reasoning_effort'):body['reasoning_effort']=options['reasoning_effort']
    if callable(params.get('_on_delta')):return openrouter._chat_stream(base+'/chat/completions',headers,body,params['_on_delta'],params.get('_cancel'))
    with request(provider,'POST','/chat/completions',body) as response:
        data=response.json();choices=data.get('choices') or []
        if not choices:raise ProviderError('O provedor não devolveu uma resposta de chat.')
        if choices[0].get('finish_reason') in ('length','content_filter'):return output(openrouter._content_to_text(choices[0].get('message',{}).get('content'))+'\n[Resposta incompleta.]',tokens=data.get('usage'),finish_reason=choices[0].get('finish_reason'))
        m=choices[0].get('message') or {};calls=[dict(id=c.get('id') or uuid.uuid4().hex,name=c['function']['name'],arguments=arguments(c['function'].get('arguments') or '{}')) for c in m.get('tool_calls',[])]
        return output(openrouter._content_to_text(m.get('content')),calls,tokens=data.get('usage'),finish_reason=choices[0].get('finish_reason'))

def openai(provider,model,messages,tools=None,params=None):
    params=params or {};items=[]
    for m in messages:
        native=m.get('_native') or {}
        if native.get('kind')=='openai':items.extend(native['output']);continue
        if m['role']=='tool':items.append(dict(type='function_call_output',call_id=m['tool_call_id'],output=m.get('content') or ''));continue
        parts=[]
        for part in text_parts(m.get('content')):
            if part.get('type')=='text':parts.append(dict(type='input_text',text=part['text']))
            elif part.get('type')=='image_url':parts.append(dict(type='input_image',image_url=part['image_url']['url']))
        if parts:items.append(dict(role=m['role'],content=parts))
        for c in m.get('tool_calls',[]):items.append(dict(type='function_call',call_id=c['id'],name=c['function']['name'],arguments=c['function']['arguments']))
    body=dict(model=model['id'],input=items,store=False)
    if tools:body['tools']=[dict(type='function',name=t['function']['name'],description=t['function'].get('description',''),parameters=t['function']['parameters'],strict=False) for t in tools]
    options={**(model.get('defaults') or {}),**params}
    if options.get('max_tokens'):body['max_output_tokens']=int(options['max_tokens'])
    if options.get('reasoning_effort'):body['reasoning']={'effort':options['reasoning_effort']}
    stream=callable(params.get('_on_delta'));body['stream']=stream;final=None;parts=[];completed={};cancel=params.get('_cancel')
    with request(provider,'POST','/responses',body,stream) as response:
        if stream and 'text/event-stream' in response.headers.get('Content-Type',''):
            for event in events(response,cancel):
                typ=event.get('type')
                if typ=='response.output_text.delta':parts.append(event.get('delta',''));params['_on_delta'](event.get('delta',''))
                elif typ=='response.output_item.done':completed[event['output_index']]=event['item']
                elif typ in ('response.completed','response.incomplete'):final=event['response']
            if cancel and cancel.is_set():return output(''.join(parts),cancelled=True)
            if final is None:raise ProviderError('A ligação terminou antes de concluir a resposta OpenAI.')
        else:final=response.json()
    if final.get('error') or final.get('status')=='failed':raise ProviderError('Erro OpenAI: '+str(final.get('error'))[:1500])
    native=final.get('output') or [completed[k] for k in sorted(completed)];text='';calls=[]
    for item in native:
        if item.get('type')=='message':text+=''.join(p.get('text',p.get('refusal','')) for p in item.get('content',[]) if p.get('type') in ('output_text','refusal'))
        elif item.get('type')=='function_call' and final.get('status')!='incomplete':calls.append(dict(id=item['call_id'],name=item['name'],arguments=arguments(item.get('arguments') or '{}')))
    if final.get('status')=='incomplete':calls=[];text+='\n[Resposta incompleta: '+str(final.get('incomplete_details',{}))+']'
    if stream and not parts and text:params['_on_delta'](text)
    u=final.get('usage') or {}
    reason=(final.get('incomplete_details') or {}).get('reason','incomplete') if final.get('status')=='incomplete' else final.get('status','completed')
    return output(text,calls,None if final.get('status')=='incomplete' else dict(kind='openai',output=native),usage(u.get('input_tokens'),u.get('output_tokens'),u.get('total_tokens')),finish_reason=reason)

def anthropic(provider,model,messages,tools=None,params=None):
    params=params or {};system=[];converted=[]
    def add(role,blocks):
        if not blocks:return
        if converted and converted[-1]['role']==role:converted[-1]['content'].extend(blocks)
        else:converted.append(dict(role=role,content=blocks))
    for m in messages:
        if m['role'] in ('system','developer'):system.append(openrouter._content_to_text(m.get('content')));continue
        if m['role']=='tool':add('user',[dict(type='tool_result',tool_use_id=m['tool_call_id'],content=m.get('content') or '')]);continue
        native=m.get('_native') or {}
        if native.get('kind')=='anthropic':add('assistant',copy.deepcopy(native['content']));continue
        blocks=[]
        for part in text_parts(m.get('content')):
            if part.get('type')=='text':blocks.append(dict(type='text',text=part['text']))
            elif part.get('type')=='image_url':mime,data=image_data(part['image_url']['url']);blocks.append(dict(type='image',source=dict(type='base64',media_type=mime,data=data)))
        for c in m.get('tool_calls',[]):blocks.append(dict(type='tool_use',id=c['id'],name=c['function']['name'],input=arguments(c['function']['arguments'])))
        add(m['role'],blocks)
    body=dict(model=model['id'],max_tokens=int((model.get('defaults') or {}).get('max_tokens',4096)),system='\n\n'.join(system),messages=converted)
    if tools:body['tools']=[dict(name=t['function']['name'],description=t['function'].get('description',''),input_schema=t['function']['parameters']) for t in tools]
    stream=callable(params.get('_on_delta'));body['stream']=stream;cancel=params.get('_cancel');blocks={};tokens={};stop=None;finished=False
    with request(provider,'POST','/messages',body,stream) as response:
        if stream and 'text/event-stream' in response.headers.get('Content-Type',''):
            fragments={}
            for event in events(response,cancel):
                typ=event.get('type')
                if typ=='message_start':tokens.update(event.get('message',{}).get('usage') or {})
                elif typ=='content_block_start':blocks[event['index']]=event['content_block']
                elif typ=='content_block_delta':
                    i=event['index'];delta=event.get('delta',{});block=blocks.setdefault(i,{})
                    if delta.get('type')=='text_delta':block['text']=block.get('text','')+delta.get('text','');params['_on_delta'](delta.get('text',''))
                    elif delta.get('type')=='input_json_delta':fragments[i]=fragments.get(i,'')+delta.get('partial_json','')
                    elif delta.get('type')=='thinking_delta':block['thinking']=block.get('thinking','')+delta.get('thinking','')
                    elif delta.get('type')=='signature_delta':block['signature']=block.get('signature','')+delta.get('signature','')
                elif typ=='message_delta':tokens.update(event.get('usage') or {});stop=event.get('delta',{}).get('stop_reason')
                elif typ=='message_stop':finished=True
            if cancel and cancel.is_set():return output(''.join(b.get('text','') for b in blocks.values() if b.get('type')=='text'),cancelled=True)
            if not finished:raise ProviderError('A ligação terminou antes de concluir a resposta Anthropic.')
            if stop!='max_tokens':
                for i,text in fragments.items():blocks[i]['input']=arguments(text)
            content=[blocks[i] for i in sorted(blocks)]
        else:
            data=response.json();content=data.get('content') or [];tokens=data.get('usage') or {};stop=data.get('stop_reason')
            if data.get('type')=='error':raise ProviderError(str(data.get('error'))[:1500])
            if stream:
                for b in content:
                    if b.get('type')=='text':params['_on_delta'](b.get('text',''))
    text=''.join(b.get('text','') for b in content if b.get('type')=='text');calls=[dict(id=b['id'],name=b['name'],arguments=arguments(b.get('input') or {})) for b in content if b.get('type')=='tool_use' and stop!='max_tokens']
    if stop=='max_tokens':calls=[];text+='\n[Resposta incompleta: limite de tokens.]'
    return output(text,calls,None if stop=='max_tokens' else dict(kind='anthropic',content=content),usage(tokens.get('input_tokens',0)+tokens.get('cache_read_input_tokens',0)+tokens.get('cache_creation_input_tokens',0),tokens.get('output_tokens',0)),finish_reason=stop)

def google(provider,model,messages,tools=None,params=None):
    params=params or {};system=[];contents=[];names={};native_ids={}
    for m in messages:
        if m['role'] in ('system','developer'):system.append(openrouter._content_to_text(m.get('content')));continue
        if m['role']=='tool':
            try:value=json.loads(m.get('content') or '{}')
            except ValueError:value=m.get('content') or ''
            fn=dict(name=names.get(m['tool_call_id'],m.get('name','tool')),response={'result':value})
            if native_ids.get(m['tool_call_id']):fn['id']=native_ids[m['tool_call_id']]
            parts=[dict(functionResponse=fn)];role='user'
        else:
            role='model' if m['role']=='assistant' else 'user';native=m.get('_native') or {};parts=[]
            if native.get('kind')=='google':parts=copy.deepcopy(native['parts'])
            else:
                for part in text_parts(m.get('content')):
                    if part.get('type')=='text':parts.append(dict(text=part['text']))
                    elif part.get('type')=='image_url':mime,data=image_data(part['image_url']['url']);parts.append(dict(inlineData=dict(mimeType=mime,data=data)))
                for c in m.get('tool_calls',[]):parts.append(dict(functionCall=dict(name=c['function']['name'],args=arguments(c['function']['arguments']))))
            functions=[p['functionCall'] for p in parts if 'functionCall' in p]
            for c,fn in zip(m.get('tool_calls',[]),functions):names[c['id']]=fn['name'];native_ids[c['id']]=fn.get('id')
        if not parts:continue
        if contents and contents[-1]['role']==role:contents[-1]['parts'].extend(parts)
        else:contents.append(dict(role=role,parts=parts))
    body=dict(contents=contents,systemInstruction={'parts':[{'text':'\n\n'.join(system)}]})
    if tools:body['tools']=[{'functionDeclarations':[dict(name=t['function']['name'],description=t['function'].get('description',''),parametersJsonSchema=t['function']['parameters']) for t in tools]}]
    defaults=model.get('defaults') or {}
    if defaults.get('max_tokens'):body['generationConfig']={'maxOutputTokens':int(defaults['max_tokens'])}
    stream=callable(params.get('_on_delta'));cancel=params.get('_cancel');mid=model['id'].removeprefix('models/');path='/models/'+quote(mid,safe='')+(':streamGenerateContent?alt=sse' if stream else ':generateContent');parts=[];tokens={};finish=None;seen=False
    with request(provider,'POST',path,body,stream) as response:
        data_events=events(response,cancel) if stream and 'text/event-stream' in response.headers.get('Content-Type','') else [response.json()]
        for event in data_events:
            seen=True;tokens=event.get('usageMetadata') or tokens;candidates=event.get('candidates') or []
            if not candidates:
                if event.get('promptFeedback',{}).get('blockReason'):raise ProviderError('Pedido bloqueado pelo provedor: '+event['promptFeedback']['blockReason'])
                continue
            candidate=candidates[0];finish=candidate.get('finishReason') or finish
            for part in candidate.get('content',{}).get('parts',[]):
                parts.append(part)
                if stream and 'text' in part and not part.get('thought'):params['_on_delta'](part['text'])
    if cancel and cancel.is_set():return output(''.join(p.get('text','') for p in parts if not p.get('thought')),cancelled=True)
    if stream and finish is None:raise ProviderError('A ligação terminou antes de concluir a resposta Google; ferramentas não executadas.')
    if not seen or (not parts and finish in (None,'STOP')):raise ProviderError('O provedor Google não devolveu conteúdo. Motivo: '+str(finish))
    text=''.join(p.get('text','') for p in parts if not p.get('thought'));calls=[]
    for p in parts:
        if 'functionCall' in p and finish in (None,'STOP'):
            fn=p['functionCall'];calls.append(dict(id=fn.get('id') or uuid.uuid4().hex,name=fn['name'],arguments=arguments(fn.get('args') or {})))
    if finish not in (None,'STOP'):calls=[];text+='\n[Resposta terminada pelo provedor: '+str(finish)+']'
    return output(text,calls,dict(kind='google',parts=parts) if finish in (None,'STOP') else None,usage(tokens.get('promptTokenCount'),(tokens.get('candidatesTokenCount') or 0)+(tokens.get('thoughtsTokenCount') or 0),tokens.get('totalTokenCount')),finish_reason=finish)

def models(provider):
    kind,_,_,_=settings(provider)
    from .catalog import normalize
    with request(provider,'GET','/models?output_modalities=all' if kind=='openrouter' else '/models') as response:data=response.json()
    rows=[]
    if isinstance(data,list):data=dict(data=data)  # alguns serviços compatíveis devolvem a lista sem o invólucro «data»
    if not isinstance(data,dict):raise ProviderError('O provedor devolveu uma lista de modelos num formato desconhecido.')
    for item in (data.get('models',[]) if kind=='google' else data.get('data') or []):
        if not isinstance(item,dict):continue
        if kind=='google' and 'generateContent' not in item.get('supportedGenerationMethods',[]):continue
        mid=(item.get('id') or item.get('name') or '').removeprefix('models/')
        if mid:
            row=normalize(item,kind)
            row['type']=row['types'][0] if row['types'] else 'other'
            rows.append(row)
    return dict(models=rows,truncated=bool(data.get('has_more') or data.get('nextPageToken')),note='Categorias por modalidades de saída. Código é uma etiqueta inferida do nome/descrição; outros modelos de chat também podem programar. Serviços sem adaptador aparecem apenas no catálogo.')
