"""Bounded real-model checks, spread over time; only synthetic echo traffic."""
import argparse,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import config
from coding_tools import read_json,atomic
from system_diagnostics import ProviderTests,load

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=int,default=300);parser.add_argument('--cases',type=int,default=20);parser.add_argument('--output',default='tests/local-soak-result.json');args=parser.parse_args()
    if not 60<=args.seconds<=900 or not 1<=args.cases<=40:raise ValueError('Ensaio limitado a 60–900 segundos e 1–40 casos.')
    cfg=read_json(config.config_path());models=[(p,m) for p in cfg.get('providers',[]) for m in p.get('models',[]) if m.get('type')=='chat' and (p.get('api_key') or p.get('kind') in ('ollama','lmstudio','openai-compatible'))]
    if not models:raise ValueError('Não há modelos de chat configurados.')
    runner=ProviderTests();start=time.monotonic();data=dict(started_at=time.time(),seconds_requested=args.seconds,cases_requested=args.cases,models=[dict(provider_id=p['id'],kind=p['kind'],model_id=m['id']) for p,m in models],results=[]);disabled=set()
    def save():atomic(Path(args.output),json.dumps(data,ensure_ascii=False,indent=2).encode())
    save()
    try:
        for case in range(args.cases):
            if time.monotonic()-start>=args.seconds:break
            candidates=[n for n in range(len(models)) if n not in disabled]
            if not candidates:break
            index=candidates[case%len(candidates)];p,m=models[index];run=runner.start(p,m,1,1024)
            while runner.jobs:
                if time.monotonic()-start>args.seconds+30:runner.cancel(run['id'])
                time.sleep(.2)
            result=load(run['id']);data['results'].append(result)
            if result['state']!='passed':disabled.add(index)
            save();print(json.dumps(dict(case=case+1,kind=p['kind'],model=m['id'],state=result['state'],failure=result.get('failure'),error=result.get('error'))),flush=True)
            due=start+(case+1)*args.seconds/args.cases
            while time.monotonic()<due and time.monotonic()-start<args.seconds:time.sleep(.2)
    finally:
        runner.close();data.update(finished_at=time.time(),elapsed_seconds=round(time.monotonic()-start,2),passed=sum(r['state']=='passed' for r in data['results']),failed=sum(r['state']!='passed' for r in data['results']));save()
    print(json.dumps(dict(elapsed_seconds=data['elapsed_seconds'],passed=data['passed'],failed=data['failed'])),flush=True)
if __name__=='__main__':main()
