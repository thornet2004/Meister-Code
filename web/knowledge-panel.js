"use strict";
(()=>{
 const el=(tag,value='',cls='')=>{const n=document.createElement(tag);n.textContent=value;n.className=cls;return n;};
 const launch=el('button','Conhecimento','btn ghost small');launch.id='btn-knowledge';document.querySelector('#btn-agent-workspace').after(launch);
 const overlay=el('div','','modal-overlay hidden');overlay.id='knowledge-modal';overlay.setAttribute('role','dialog');overlay.setAttribute('aria-modal','true');overlay.setAttribute('aria-label','Base de conhecimento do projeto');
 const modal=el('div','','modal wide'),head=el('div','','modal-head'),body=el('div','','modal-body'),status=el('p','','hint');status.id='knowledge-status';
 head.append(el('h3','Base de conhecimento do projeto'));modal.append(head,body);overlay.append(modal);document.body.append(overlay);
 async function callApi(name,...args){const r=await call(name,...args);if(!r.ok)throw Error(r.error);return r;}
 function button(parent,label,action,cls){const b=el('button',label,cls||'btn ghost small');b.type='button';b.onclick=async()=>{b.disabled=true;try{await action();}catch(e){status.textContent=e.message;}finally{b.disabled=false;}};parent.append(b);return b;}
 const close=()=>{overlay.classList.add('hidden');launch.focus();};button(head,'Fechar',close);overlay.onclick=e=>{if(e.target===overlay)close();};document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!overlay.classList.contains('hidden'))close();});
 body.append(status,el('p','As notas que o agente grava e consulta neste projeto. Pesquisa por palavras; o agente também procura por significado quando a pesquisa semântica está ligada.','hint'));
 const query=el('input');query.id='kn-query';query.placeholder='Pesquisar notas';query.setAttribute('aria-label','Pesquisar notas');body.append(query);
 button(body,'Procurar',()=>refresh());button(body,'Nova nota',()=>edit({}));
 query.onkeydown=e=>{if(e.key==='Enter')refresh().catch(e=>status.textContent=e.message);};
 // formulário (escondido até editar ou criar)
 const form=el('section','','hidden');form.id='kn-form';
 const titulo=el('input');titulo.id='kn-titulo';titulo.placeholder='Título';titulo.maxLength=200;titulo.setAttribute('aria-label','Título');
 const etiquetas=el('input');etiquetas.id='kn-etiquetas';etiquetas.placeholder='Etiquetas (ex.: auth, login)';etiquetas.maxLength=500;etiquetas.setAttribute('aria-label','Etiquetas');
 const tipo=el('input');tipo.id='kn-tipo';tipo.placeholder='Tipo (ex.: função, nota, decisão)';tipo.maxLength=100;tipo.setAttribute('aria-label','Tipo');
 const ref=el('input');ref.id='kn-ref';ref.placeholder='Referência (ex.: 0x401000, ficheiro:linha)';ref.maxLength=300;ref.setAttribute('aria-label','Referência');
 const texto=el('textarea');texto.id='kn-texto';texto.rows=6;texto.maxLength=20000;texto.placeholder='Conteúdo da nota';texto.setAttribute('aria-label','Conteúdo');
 form.append(el('h4','Nota'),titulo,etiquetas,tipo,ref,texto);
 let editing=null;  // id da nota a editar, ou null para uma nova
 button(form,'Guardar nota',async()=>{if(!titulo.value.trim()){status.textContent='A nota precisa de um título.';return;}await callApi('save_note',titulo.value,texto.value,etiquetas.value,tipo.value,ref.value,editing);status.textContent='Guardada.';form.classList.add('hidden');await refresh();},'btn');
 button(form,'Cancelar',()=>{form.classList.add('hidden');status.textContent='';});
 body.append(form);
 async function edit(nota){editing=nota.id!=null?nota.id:null;titulo.value=nota.titulo||'';texto.value=nota.texto||'';etiquetas.value=nota.etiquetas||'';tipo.value=nota.tipo||'';ref.value=nota.ref||'';form.classList.remove('hidden');status.textContent='';titulo.focus();}
 const results=el('div');results.id='kn-results';body.append(results);
 async function refresh(){
  const r=await callApi('get_notes',query.value,50);results.replaceChildren();
  if(!r.notas.length){results.append(el('p','Sem notas.','hint'));return;}
  for(const n of r.notas){const card=el('article','','mcp-card');
   const meta=[n.tipo,n.etiquetas,n.ref].filter(Boolean).join(' · ');
   card.append(el('strong',n.titulo));if(meta)card.append(el('p',meta,'hint'));if(n.trecho)card.append(el('pre',n.trecho,'step-body'));
   button(card,'Editar',async()=>{const full=await callApi('read_note',n.id);if(full.encontrada)await edit(full.nota);else status.textContent='A nota já não existe.';});
   button(card,'Apagar',async()=>{await callApi('forget_note',n.id);await refresh();});
   results.append(card);}
 }
 launch.onclick=async()=>{overlay.classList.remove('hidden');form.classList.add('hidden');status.textContent='A carregar…';try{await refresh();status.textContent='';}catch(e){status.textContent=e.message;}};
})();
