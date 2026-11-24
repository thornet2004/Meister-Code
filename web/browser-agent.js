(() => {
  if (window.__studioBrowserAgent) return;
  const nodes = new Map();
  let counter = 0;
  function visible(node) {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  }
  function target(ref) {
    const node = nodes.get(ref);
    if (!node || !node.isConnected || !visible(node)) throw new Error('Elemento indisponível. Lê novamente a página para obter referências atuais.');
    return node;
  }
  window.__studioBrowserAgent = {
    read() {
      nodes.clear();
      const elements = [];
      for (const node of document.querySelectorAll('a[href],button,input,textarea,select,[role="button"],[role="link"],[contenteditable="true"],[tabindex]')) {
        if (!visible(node) || node.disabled || node.type === 'hidden') continue;
        if (elements.length >= 250) break;
        const ref = 'e' + (++counter);
        nodes.set(ref, node);
        elements.push({ref, tag:node.tagName.toLowerCase(), role:node.getAttribute('role') || '',
          type:node.type || '', label:(node.getAttribute('aria-label') || Array.from(node.labels || []).map(l=>l.innerText).join(' ') || node.innerText || node.placeholder || node.title || node.getAttribute('alt') || '').trim().slice(0,250),
          value:node.type === 'password' ? '[oculto]' : String(node.value || '').slice(0,300),
          href:node.href || undefined, checked:node.checked,
          options:node.tagName === 'SELECT' ? Array.from(node.options).slice(0,50).map(o=>({value:o.value,text:o.text})) : undefined});
      }
      const text = (document.body?.innerText || '').slice(0,24000);
      return {url:location.href,title:document.title,text,elements,
        scroll:{x:scrollX,y:scrollY,height:document.documentElement.scrollHeight},
        note:'Referências válidas para esta leitura. Iframes e shadow DOM fechados podem não estar disponíveis.'};
    },
    locate(ref) {
      const node = target(ref);
      node.scrollIntoView({block:'center',inline:'center'});
      const rect = node.getBoundingClientRect();
      return {x:rect.x+rect.width/2,y:rect.y+rect.height/2};
    },
    fill(ref, text) {
      const node = target(ref);
      node.focus();
      if (node.readOnly) throw new Error('Este campo é só de leitura.');
      if (node.isContentEditable) node.textContent = text;
      else if (['INPUT','TEXTAREA','SELECT'].includes(node.tagName)) {
        const prototype = node.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : node.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(prototype,'value').set.call(node,text);
      } else throw new Error('A referência não corresponde a um campo editável.');
      node.dispatchEvent(new Event('input',{bubbles:true}));
      node.dispatchEvent(new Event('change',{bubbles:true}));
      return {filled:true};
    },
    focus(ref) { target(ref).focus(); return {focused:true}; },
    scroll(amount) { window.scrollBy(0,amount); return {scrolled:true}; }
  };
})();
