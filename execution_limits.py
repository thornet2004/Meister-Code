"""Orçamentos por pedido e deteção de chamadas sem progresso."""
import hashlib,json,time

# tokens: soma de todas as rondas do pedido. Eram 200 mil; num modelo local com a janela cheia isso são quatro rondas (pedido do user, 24/11/2026: 4 milhões).
DEFAULTS=dict(seconds=1800,tokens=4000000,tool_calls=100,cost=0,input_per_million=0,output_per_million=0)
def validate(values):
    result={}
    for key,default in DEFAULTS.items():
        value=float(values.get(key,default))
        if not __import__('math').isfinite(value) or value<0:raise ValueError('Limites têm de ser números positivos ou zero.')
        if key in ('seconds','tokens','tool_calls') and not value:raise ValueError('Tempo, tokens e chamadas precisam de um limite maior que zero.')
        result[key]=int(value) if key in ('seconds','tokens','tool_calls') else value
    return result
class ExecutionLimits:
    def __init__(self,settings=None):self.settings=validate(settings or {});self.started=time.monotonic();self.tokens=0;self.cost=0;self.calls=0;self.repeats={};self.loop=False
    def add_usage(self,usage):
        self.tokens+=int(usage.get('total_tokens') or (usage.get('prompt_tokens',0)+usage.get('completion_tokens',0)))
        self.cost+=(int(usage.get('prompt_tokens') or 0)*self.settings['input_per_million']+int(usage.get('completion_tokens') or 0)*self.settings['output_per_million'])/1000000
    def observe(self,call,result):
        self.calls+=1;signature=hashlib.sha256((json.dumps([call.get('name'),call.get('arguments')],sort_keys=True,ensure_ascii=False)+str(result)).encode()).hexdigest()
        count=self.repeats.get(signature,0)+1;self.repeats[signature]=count
        polling=call.get('name') in ('processo_resultado','agente_resultado','lsp_diagnosticos','processos_listar','agentes_tarefas')
        if count>=(12 if polling else 3):self.loop=True
    def reason(self):
        if self.loop:return 'Chamadas repetidas sem progresso; o pedido foi interrompido.'
        if time.monotonic()-self.started>=self.settings['seconds']:return 'Limite de tempo do pedido atingido.'
        if self.tokens>=self.settings['tokens']:return 'Limite de tokens do pedido atingido.'
        if self.calls>=self.settings['tool_calls']:return 'Limite de chamadas de ferramentas atingido.'
        if self.settings['cost'] and self.cost>=self.settings['cost']:return 'Orçamento estimado do pedido atingido.'
        return ''
