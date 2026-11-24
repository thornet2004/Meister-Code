"""Servidor MCP de demonstração local; apenas eco e soma, sem efeitos externos."""
import json
import sys

TOOLS=[
    {"name":"demo_echo","description":"Devolve o texto recebido para testar o MCP.","inputSchema":{"type":"object","properties":{"texto":{"type":"string"}},"required":["texto"]},"annotations":{"readOnlyHint":True}},
    {"name":"demo_somar","description":"Soma dois números localmente.","inputSchema":{"type":"object","properties":{"a":{"type":"number"},"b":{"type":"number"}},"required":["a","b"]},"annotations":{"readOnlyHint":True}}
]
def ensure_stdio():
    # O executável principal não tem consola; recupera os pipes herdados no modo MCP.
    if sys.stdin is None or sys.stdout is None:
        import ctypes, msvcrt, os
        from ctypes import wintypes
        get_handle=ctypes.windll.kernel32.GetStdHandle
        get_handle.argtypes=[wintypes.DWORD];get_handle.restype=wintypes.HANDLE
        if sys.stdin is None:
            sys.stdin=os.fdopen(msvcrt.open_osfhandle(get_handle(-10),os.O_RDONLY),'r',encoding='utf-8')
        if sys.stdout is None:
            sys.stdout=os.fdopen(msvcrt.open_osfhandle(get_handle(-11),0),'w',encoding='utf-8',buffering=1)

def main():
    ensure_stdio()
    legacy='--legacy' in sys.argv
    for line in sys.stdin:
        message=json.loads(line)
        if 'id' not in message:continue
        method=message.get('method');params=message.get('params',{})
        try:
            if method=='server/discover' and not legacy:result={'resultType':'complete','supportedVersions':['2026-07-28'],'capabilities':{'tools':{}},'_meta':{'io.modelcontextprotocol/serverInfo':{'name':'studio-demo','version':'1.0'}}}
            elif method=='initialize':result={'protocolVersion':'2025-11-25','capabilities':{'tools':{}},'serverInfo':{'name':'studio-demo','version':'1.0'}}
            elif method=='tools/list':result={'tools':TOOLS}
            elif method=='tools/call':
                args=params.get('arguments',{})
                if params['name']=='demo_echo':value={'texto':args['texto']}
                elif params['name']=='demo_somar':value={'soma':args['a']+args['b']}
                else:raise ValueError('Ferramenta desconhecida')
                result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}],'structuredContent':value,'isError':False}
            else:
                print(json.dumps({'jsonrpc':'2.0','id':message['id'],'error':{'code':-32601,'message':'Method not found'}}),flush=True);continue
            response={'jsonrpc':'2.0','id':message['id'],'result':result}
        except Exception as exc:response={'jsonrpc':'2.0','id':message['id'],'error':{'code':-32602,'message':str(exc)}}
        print(json.dumps(response,ensure_ascii=True),flush=True)
    return 0
if __name__=='__main__':raise SystemExit(main())
