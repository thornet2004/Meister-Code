"""One real coding task in disposable files, with a strict tool/path allowlist."""
import copy,hashlib,json,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import api,config
from coding_tools import read_json,atomic

def main():
    saved=read_json(config.config_path());selection=saved['chat'];provider=copy.deepcopy(next(p for p in saved['providers'] if p['id']==selection['provider_id']));model=next(m for m in provider['models'] if m['id']==selection['model_id']);model.setdefault('defaults',{})['max_tokens']=1024
    base=Path(tempfile.mkdtemp(prefix='studio-live-code-'));project=base/'project';tests=project/'tests';tests.mkdir(parents=True);(project/'calc.py').write_text('def add(a, b):\n    return a - b\n',encoding='utf-8');testfile=tests/'test_calc.py';testfile.write_text('import unittest\nfrom calc import add\nclass Tests(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n        self.assertEqual(add(-2, 3), 1)\n',encoding='utf-8');original=hashlib.sha256(testfile.read_bytes()).hexdigest()
    cfg=config.default_config();cfg.update(storage_layout=2,storage_root=str(base),providers=[provider],chat=selection,projects=[dict(id='fixture',name='Synthetic',path=str(project))],active_project_id='fixture');cfg['preferences'].update(agent=dict(enabled=True,scope='project',approval='auto'),execution_limits=dict(seconds=180,tokens=30000,tools=12,cost=0,input_per_million=0,output_per_million=0))
    settings=base/'settings';settings.mkdir();allowed={'ler_codigo','aplicar_patch','projeto_validar'};calls=[]
    with patch('config.application_root',return_value=base),patch('config.config_dir',return_value=settings),patch('config.load_config',side_effect=lambda:copy.deepcopy(cfg)),patch('config.save_config'):
        app=api.Api();available=app._available_tools;handler=app._handle_tool
        def guarded(c,call,*args):
            name=call.get('name');arguments=call.get('arguments') or {};calls.append(name)
            if name not in allowed:return json.dumps({'error':'Ferramenta não autorizada neste ensaio.'})
            if name=='aplicar_patch' and any(a.get('caminho')!='calc.py' for a in arguments.get('alteracoes',[])):return json.dumps({'error':'Só podes alterar calc.py neste ensaio.'})
            return handler(c,call,*args)
        try:
            with patch.object(app,'_available_tools',side_effect=lambda *a:[t for t in available(*a) if t['function']['name'] in allowed]),patch.object(app,'_handle_tool',side_effect=guarded):
                start=time.monotonic();result=app.chat('Corrige a função add em calc.py, que subtrai em vez de somar. Lê o ficheiro antes de aplicar um patch com o hash atual. Mantém tests/test_calc.py intacto. Usa apenas ler_codigo, aplicar_patch e projeto_validar. Executa as verificações e conclui quando os testes passarem. Não instales dependências.')
            turns=api._load_conversation(project/'.studio');last=turns[-1];evidence=dict(ok=result['ok'],turn_state=last.get('turn_state'),seconds=round(time.monotonic()-start,2),model=model['id'],calls=calls,tests_unchanged=hashlib.sha256(testfile.read_bytes()).hexdigest()==original,source=(project/'calc.py').read_text(),validation=last.get('validation'),workspace=str(project),error=result.get('error'))
            atomic(Path('tests/private-agent-live-result.json'),json.dumps(evidence,ensure_ascii=False,indent=2).encode());print(json.dumps(evidence,ensure_ascii=False),flush=True)
            if not evidence['ok'] or evidence['turn_state']!='completed' or not evidence['tests_unchanged'] or (evidence['validation'] or {}).get('state')!='passed':raise AssertionError('A tarefa real não cumpriu os critérios. Ver relatório.')
        finally:
            app._tasks.close();app._validations.close();app._commands.close();app._provider_tests.close();app._lsp.close();app._mcp.close();app._folder_tools.close();app._terminal.close()
if __name__=='__main__':main()
