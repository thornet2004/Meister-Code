"""Fluxo real: leitura → patch → diagnóstico LSP → undo → redo."""
import json,tempfile,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import api
from coding_tools import Checkpoints
report={}
with tempfile.TemporaryDirectory(prefix='studio-code-') as temp:
    root=Path(temp);meta=root/'.studio';app=api.Api()
    try:
        ctx=dict(on=True,scope='project',approval='auto',base=str(root),_checkpoint_meta=str(meta),_checkpoint_title='Corrigir tipos em Python e TypeScript')
        for filename,bad,good in [('bad.py','x: int = "wrong"\n','x: int = 42\n'),('bad.ts','const x: number = "wrong";\n','const x: number = 42;\n')]:
            path=root/filename;path.write_text(bad,encoding='utf-8')
            diagnostic=app._lsp.diagnose(root,path,18)
            assert diagnostic['status']=='complete' and any(d['severity']=='error' for d in diagnostic['diagnostics']),diagnostic
            reading=json.loads(app._dispatch_coding_tool('ler_codigo',dict(caminho=filename),ctx,[]))
            result=json.loads(app._dispatch_coding_tool('aplicar_patch',dict(alteracoes=[dict(caminho=filename,sha256=reading['sha256'],trecho_antigo=bad.strip(),trecho_novo=good.strip())]),ctx,[]))
            assert 'error' not in result,result
            after=app._lsp.diagnose(root,path,18)
            assert after['status']=='complete' and not any(d['severity']=='error' for d in after['diagnostics']),after
            report[filename]=dict(before_errors=len(diagnostic['diagnostics']),after_errors=len(after['diagnostics']))
        store=Checkpoints(meta);key=ctx['_checkpoint_id'];store.finish(key)
        assert len(store.list())==1 and store.list()[0]['file_count']==2
        store.restore(key)
        assert '"wrong"' in (root/'bad.py').read_text() and '"wrong"' in (root/'bad.ts').read_text()
        store.restore(key,True)
        assert '42' in (root/'bad.py').read_text() and '42' in (root/'bad.ts').read_text()
        report.update(grouped_checkpoint=True,undo_redo=True)
    finally:app._lsp.close();app._mcp.close();app._folder_tools.close()
Path(__file__).with_name('coding-real-result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('PASS:',json.dumps(report))
