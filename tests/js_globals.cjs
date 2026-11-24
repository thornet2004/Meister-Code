// Ferramenta de manutenção da interface (não é um ensaio de Playwright).
//
// Os ficheiros de web/ são scripts clássicos: todas as declarações de topo
// (function/const/let/var/class) ficam no mesmo âmbito global. Esta ferramenta
// lê-os com o parser do TypeScript e mostra/guarda esse "contrato":
//
//   node tests/js_globals.cjs listar <ficheiro.js>      declarações e código de topo de um ficheiro
//   node tests/js_globals.cjs guardar <ficheiro.json>   nomes globais de todos os web/*.js
//   node tests/js_globals.cjs comparar <ficheiro.json>  falha se mudarem nomes ou houver duplicados
//
// O parser vem das dependências locais do LSP (Ferramentas/_Runtime/lsp) ou de
// TYPESCRIPT_MODULE.
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const ts = require(process.env.TYPESCRIPT_MODULE || path.join(root, 'Ferramentas/_Runtime/lsp/node_modules/typescript'));

function webFiles() {
  return fs.readdirSync(path.join(root, 'web')).filter(name => name.endsWith('.js')).sort();
}

function analyse(file) {
  const text = fs.readFileSync(file, 'utf8');
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  const line = pos => source.getLineAndCharacterOfPosition(pos).line + 1;
  const declarations = [];
  const statements = [];
  for (const node of source.statements) {
    const span = {start: line(node.getStart(source)), end: line(node.getEnd())};
    if (ts.isFunctionDeclaration(node) && node.name) {
      declarations.push({name: node.name.text, kind: 'function', ...span});
    } else if (ts.isClassDeclaration(node) && node.name) {
      declarations.push({name: node.name.text, kind: 'class', ...span});
    } else if (ts.isVariableStatement(node)) {
      const flags = node.declarationList.flags;
      const kind = flags & ts.NodeFlags.Const ? 'const' : flags & ts.NodeFlags.Let ? 'let' : 'var';
      for (const item of node.declarationList.declarations) {
        const names = [];
        const collect = target => {
          if (ts.isIdentifier(target)) names.push(target.text);
          else for (const element of target.elements) if (element.name) collect(element.name);
        };
        collect(item.name);
        for (const name of names) declarations.push({name, kind, ...span});
      }
    } else if (!ts.isEmptyStatement(node)) {
      statements.push({...span, text: node.getText(source).split('\n')[0].slice(0, 110)});
    }
  }
  return {declarations, statements, syntaxErrors: source.parseDiagnostics.length};
}

function contract() {
  const names = {};
  const duplicates = [];
  for (const name of webFiles()) {
    const result = analyse(path.join(root, 'web', name));
    if (result.syntaxErrors) throw new Error(`erro de sintaxe em web/${name}`);
    for (const item of result.declarations) {
      if (names[item.name]) duplicates.push(`${item.name} (${names[item.name].file} e ${name})`);
      names[item.name] = {kind: item.kind, file: name};
    }
  }
  return {names, duplicates};
}

const [mode, target] = process.argv.slice(2);
if (mode === 'listar' && target) {
  const result = analyse(path.resolve(target));
  for (const item of result.declarations) console.log(`${String(item.start).padStart(5)}-${String(item.end).padEnd(5)} ${item.kind.padEnd(8)} ${item.name}`);
  console.log(`--- código de topo que corre ao carregar (${result.statements.length}) ---`);
  for (const item of result.statements) console.log(`${String(item.start).padStart(5)}-${String(item.end).padEnd(5)} ${item.text}`);
} else if (mode === 'guardar' && target) {
  const {names, duplicates} = contract();
  if (duplicates.length) { console.error('nomes declarados em dois ficheiros:', duplicates); process.exit(1); }
  const kinds = Object.fromEntries(Object.keys(names).sort().map(name => [name, names[name].kind]));
  fs.writeFileSync(target, JSON.stringify(kinds, null, 1));
  console.log(`${Object.keys(kinds).length} nomes globais guardados em ${target}`);
} else if (mode === 'comparar' && target) {
  const saved = JSON.parse(fs.readFileSync(target, 'utf8'));
  const {names, duplicates} = contract();
  const missing = Object.keys(saved).filter(name => !names[name]);
  const added = Object.keys(names).filter(name => !(name in saved));
  const changed = Object.keys(saved).filter(name => names[name] && names[name].kind !== saved[name]);
  console.log(`antes: ${Object.keys(saved).length} nomes; agora: ${Object.keys(names).length}`);
  if (missing.length) console.log('em falta:', missing);
  if (added.length) console.log('novos:', added);
  if (changed.length) console.log('mudaram de tipo:', changed);
  if (duplicates.length) console.log('declarados em dois ficheiros:', duplicates);
  if (missing.length || added.length || changed.length || duplicates.length) process.exit(1);
  console.log('nomes globais idênticos, sem duplicados');
} else {
  console.log('uso: node tests/js_globals.cjs listar <ficheiro.js> | guardar <json> | comparar <json>');
  process.exit(2);
}
