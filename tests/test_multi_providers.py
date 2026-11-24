import json, unittest
from unittest.mock import patch
from providers import multi,openrouter
from providers.base import ProviderError

class Response:
    def __init__(self, data, streaming=False):
        self.data=data; self.ok=True; self.status_code=200; self.headers={'Content-Type':'text/event-stream' if streaming else 'application/json'}
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def json(self):return self.data
    def iter_lines(self,**kwargs):
        for item in self.data:yield ('data: '+json.dumps(item)).encode()

class ProvidersTest(unittest.TestCase):
    def test_truncated_partial_tool_arguments_are_neither_decoded_nor_replayed(self):
        r,_=self.call('openai',dict(status='incomplete',incomplete_details=dict(reason='max_output_tokens'),output=[dict(type='function_call',call_id='c',name='run',arguments='{partial')]))
        self.assertEqual(r['tool_calls'],[]);self.assertNotIn('_native',r['raw_message']);self.assertEqual(r['finish_reason'],'max_output_tokens')
        events=[dict(type='content_block_start',index=0,content_block=dict(type='tool_use',id='c',name='run',input={})),dict(type='content_block_delta',index=0,delta=dict(type='input_json_delta',partial_json='{partial')),dict(type='message_delta',delta=dict(stop_reason='max_tokens')),dict(type='message_stop')]
        r,_=self.call('anthropic',events,stream=True);self.assertEqual(r['tool_calls'],[]);self.assertNotIn('_native',r['raw_message']);self.assertEqual(r['finish_reason'],'max_tokens')
        r,_=self.call('google',dict(candidates=[dict(content=dict(parts=[dict(functionCall=dict(name='run',args='{partial'))]),finishReason='MAX_TOKENS')]));self.assertEqual(r['tool_calls'],[]);self.assertNotIn('_native',r['raw_message']);self.assertEqual(r['finish_reason'],'MAX_TOKENS')
    def test_vendor_finish_reasons_survive_normalization(self):
        r,_=self.call('openai',dict(status='incomplete',incomplete_details=dict(reason='max_output_tokens'),output=[]));self.assertEqual(r['finish_reason'],'max_output_tokens')
        r,_=self.call('anthropic',dict(content=[],stop_reason='max_tokens'));self.assertEqual(r['finish_reason'],'max_tokens')
        r,_=self.call('google',dict(candidates=[dict(content=dict(parts=[]),finishReason='MAX_TOKENS')]));self.assertEqual(r['finish_reason'],'MAX_TOKENS')
    def test_openrouter_length_does_not_execute_partial_tools_and_keeps_reason(self):
        event=dict(choices=[dict(delta=dict(tool_calls=[dict(index=0,id='c',function=dict(name='run',arguments='{broken'))]),finish_reason='length')])
        with patch('providers.openrouter._chat_post',return_value=Response([event],True)):
            r=openrouter._chat_stream('http://localhost',{},dict(model='test'),lambda s:None)
        self.assertEqual(r['tool_calls'],[]);self.assertEqual(r['finish_reason'],'length')
    def call(self, kind, data, messages=None, stream=False):
        provider=dict(kind=kind,api_key='test-secret',base_url='http://localhost:5555/v1')
        with patch.object(multi.requests,'request',return_value=Response(data,stream)) as request:
            result=getattr(multi,kind)(provider,{'id':'test'},messages or [{'role':'user','content':'olá'}],params={'_on_delta':lambda s:None} if stream else {})
        return result,request.call_args.kwargs['json']
    def test_openai_native_replay(self):
        native=[{'type':'reasoning','id':'r','encrypted_content':'opaque'},dict(type='function_call',call_id='c',name='read',arguments='{"path":"x"}')]
        result,body=self.call('openai',dict(output=native,usage={'input_tokens':10,'output_tokens':3}))
        self.assertEqual(result['tool_calls'][0]['arguments'],{'path':'x'})
        _,body=self.call('openai',dict(output=[]),[result['raw_message'],dict(role='tool',tool_call_id='c',content='ok')])
        self.assertEqual(body['input'][:2],native)
        self.assertEqual(body['input'][2]['type'],'function_call_output')
        self.assertFalse(body['store'])
    def test_openai_stream_completion_required(self):
        with self.assertRaises(ProviderError):self.call('openai',[dict(type='response.output_text.delta',delta='x')],stream=True)
        result,_=self.call('openai',[dict(type='response.completed',response=dict(status='completed',output=[dict(type='message',content=[dict(type='output_text',text='ok')])]))],stream=True)
        self.assertEqual(result['content'],'ok')
    def test_openai_truncated_does_not_execute(self):
        result,_=self.call('openai',dict(status='incomplete',output=[dict(type='function_call',call_id='c',name='run',arguments='{}')]))
        self.assertEqual(result['finish_reason'],'incomplete')
        self.assertEqual(result['tool_calls'],[])
    def test_anthropic_signature_and_results(self):
        blocks=[dict(type='thinking',thinking='private',signature='opaque'),dict(type='tool_use',id='c',name='read',input={'x':1})]
        result,_=self.call('anthropic',dict(content=blocks,stop_reason='tool_use'))
        _,body=self.call('anthropic',dict(content=[]),[result['raw_message'],dict(role='tool',tool_call_id='c',content='ok')])
        self.assertEqual(body['messages'][0]['content'],blocks)
        self.assertEqual(body['messages'][1]['content'][0]['tool_use_id'],'c')
    def test_google_signature_and_call_id(self):
        parts=[dict(functionCall=dict(id='c',name='read',args={'x':1}),thoughtSignature='opaque')]
        result,_=self.call('google',dict(candidates=[dict(content={'parts':parts},finishReason='STOP')]))
        _,body=self.call('google',dict(candidates=[dict(content={'parts':[{'text':'ok'}]},finishReason='STOP')]),[result['raw_message'],dict(role='tool',tool_call_id='c',content='{"ok":true}')])
        self.assertEqual(body['contents'][0]['parts'],parts)
        self.assertEqual(body['contents'][1]['parts'][0]['functionResponse']['id'],'c')
    def test_compatible_sends_a_single_system_message_first(self):
        sent={}
        def fake(method,url,**kwargs):
            sent.update(kwargs.get('json') or {});return Response({'choices':[{'message':{'content':'ok'},'finish_reason':'stop'}]})
        messages=[dict(role='system',content='regras'),dict(role='user',content='olá'),dict(role='system',content='resumo'),
                  dict(role='assistant',content='viva'),dict(role='system',content=''),dict(role='user',content='continua')]
        with patch.object(multi.requests,'request',side_effect=fake):
            multi.compatible(dict(kind='lmstudio'),dict(id='m'),messages)
        self.assertEqual([m['role'] for m in sent['messages']],['system','user','assistant','user'])
        self.assertEqual(sent['messages'][0]['content'],'regras\n\nresumo','as notas juntam-se pela ordem, sem perder nenhuma')
        plain=[dict(role='system',content='regras'),dict(role='user',content='olá')]
        self.assertIs(multi.single_system(plain),plain,'sem notas a meio não se mexe em nada')
        self.assertEqual(multi.single_system([dict(role='user',content='a'),dict(role='system',content='b')])[0],dict(role='system',content='b'))
    def test_reasoning_effort_goes_only_to_the_users_own_server(self):
        sent=[]
        def fake(method,url,**kwargs):
            sent.append(kwargs.get('json') or {});return Response({'choices':[{'message':{'content':'ok'},'finish_reason':'stop'}]})
        with patch.object(multi.requests,'request',side_effect=fake):
            multi.compatible(dict(kind='openai-compatible',base_url='http://rig:8081/v1'),dict(id='m'),[dict(role='user',content='olá')],None,dict(reasoning_effort='none'))
            multi.compatible(dict(kind='openai-compatible',base_url='http://rig:8081/v1'),dict(id='m'),[dict(role='user',content='olá')])
            multi.compatible(dict(kind='lmstudio'),dict(id='m'),[dict(role='user',content='olá')],None,dict(reasoning_effort='none'))
        self.assertEqual([body.get('reasoning_effort') for body in sent],['none',None,None])
    def test_local_auth_optional_and_models(self):
        p=dict(kind='ollama')
        self.assertNotIn('Authorization',multi.settings(p)[3])
        with patch.object(multi.requests,'request',return_value=Response({'data':[{'id':'local-model'}]})):
            self.assertEqual(multi.models(p)['models'][0]['id'],'local-model')
    def test_cloud_requires_key_and_url_has_no_embedded_credentials(self):
        for p in [dict(kind='openai'),dict(kind='ollama',base_url='http://user:password@localhost')]:
            with self.assertRaises(ProviderError):multi.settings(p)
    def test_anthropic_stream_arguments(self):
        events=[dict(type='content_block_start',index=0,content_block=dict(type='tool_use',id='c',name='read',input={})),dict(type='content_block_delta',index=0,delta=dict(type='input_json_delta',partial_json='{"x":1}')),dict(type='message_delta',delta={'stop_reason':'tool_use'}),dict(type='message_stop')]
        result,_=self.call('anthropic',events,stream=True);self.assertEqual(result['tool_calls'][0]['arguments'],{'x':1})
    def test_google_stream_and_image_input(self):
        messages=[dict(role='user',content=[dict(type='image_url',image_url={'url':'data:image/png;base64,YQ=='}),dict(type='text',text='inspect')])]
        result,body=self.call('google',[dict(candidates=[dict(content={'parts':[{'text':'ok'}]},finishReason='STOP')])],messages,True)
        self.assertEqual(result['content'],'ok');self.assertEqual(body['contents'][0]['parts'][0]['inlineData']['mimeType'],'image/png')
    def test_transient_retries_before_stream_only(self):
        failure=Response({});failure.status_code=503
        failure.close=lambda:None
        with patch.object(multi.requests,'request',side_effect=[failure,Response({'data':[]})]) as request,patch.object(multi.time,'sleep'):
            multi.models(dict(kind='ollama'));self.assertEqual(request.call_count,2)

if __name__=='__main__':unittest.main()
