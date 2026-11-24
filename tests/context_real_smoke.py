"""Definições e referências reais em Python e TypeScript, sem modelos cloud."""
import json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from coding_lsp import LanguageServers
report={}
with tempfile.TemporaryDirectory(prefix='studio-nav-') as tmp:
    root=Path(tmp);lsp=LanguageServers()
    try:
        (root/'helper.py').write_text('def double(value: int) -> int:\n    return value * 2\n');(root/'main.py').write_text('from helper import double\nanswer = double(21)\n')
        (root/'helpers.ts').write_text('export function dobro(value: number): number { return value * 2; }\n');(root/'main.ts').write_text('import { dobro } from "./helpers";\nconst answer = dobro(21);\n')
        for kind,main,helper,column,definition_column in [('python','main.py','helper.py',10,5),('typescript','main.ts','helpers.ts',16,17)]:
            result=lsp.navigate(root,root/main,'definitions',2,column);assert result['status']=='complete' and any(Path(r['path']).name==helper for r in result['results']),result
            outline=lsp.navigate(root,root/helper,'symbols');assert outline['results'],outline
            entry=next(r for r in outline['results'] if r['name'] in ('double','dobro'));chained=lsp.navigate(root,entry['path'],'references',entry['line'],entry['column']);assert any(Path(r['path']).name==main for r in chained['results']),chained
            references=lsp.navigate(root,root/helper,'references',1,definition_column);assert any(Path(r['path']).name==main for r in references['results']),references
            report[kind]=dict(definitions=result['results'],references=references['results'],symbols=outline['results'])
        try:lsp.navigate(root,root.parent/'outside.py','symbols');raise AssertionError('Scope check missing')
        except ValueError:pass
    finally:lsp.close()
Path(__file__).with_name('context-real-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print('PASS: real Python/TypeScript definitions, references and symbols.')
