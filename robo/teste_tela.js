// Teste de tela antes de publicar: abre o site montado em _site e falha se alguma página quebrar.
const {chromium} = require('playwright'), http = require('http'), fs = require('fs'), path = require('path');
const raiz = path.resolve(process.argv[2] || '_site'), tipos = {'.html': 'text/html', '.json': 'application/json', '.js': 'text/javascript', '.png': 'image/png', '.webmanifest': 'application/manifest+json'};
const srv = http.createServer((q, r) => { let f = path.join(raiz, decodeURIComponent(q.url.split('?')[0])); if (f.endsWith(path.sep)) f += 'index.html';
  if (!f.startsWith(raiz) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { r.writeHead(404); return r.end('{}'); }
  r.writeHead(200, {'content-type': tipos[path.extname(f)] || 'application/octet-stream'}); r.end(fs.readFileSync(f)); });
const texto = async p => { for (let i = 0; i < 30; i++) { const t = (await p.innerText('#app')).trim(); if (t.length >= 40 && !/^Carregando/.test(t)) return t; await p.waitForTimeout(1000); } return (await p.innerText('#app')).trim(); };
srv.listen(0, async () => {
  const url = 'http://localhost:' + srv.address().port + '/index.html', b = await chromium.launch(), p = await b.newPage(), erros = [];
  p.on('pageerror', e => erros.push(e.message));
  const rotas = ['', '#busca', '#rankings', '#comparar', '#investimentos', '#carteira', '#cripto', '#ferramentas', '#fiis', '#fundos', '#tesouro', '#PETR4', '#cripto/BTC'];
  const acoes = await p.goto(url).then(() => p.evaluate(() => fetch('acoes.json').then(r => r.json()).then(j => j.d.slice(0, 3).map(x => x[0])))).catch(() => []);
  acoes.forEach(t => rotas.push('#' + t));
  for (const ab of ['div', 'sim', 'just', 'ir', 'mer', 'calc', 'age']) { await p.evaluate(a => localStorage.setItem('fund_ftab', JSON.stringify(a)), ab); rotas.push('#ferramentas'); await p.goto(url + '#ferramentas'); await p.reload(); await p.waitForTimeout(1500);
    const t = await texto(p); if (t.length < 40) erros.push('Ferramentas/' + ab + ' ficou vazia'); }
  for (const r of rotas) { await p.goto(url + r); await p.reload(); await p.waitForTimeout(1800);
    const t = await texto(p); if (t.length < 40) erros.push('página vazia em ' + (r || 'início')); if (/Não foi possível carregar os dados/.test(t)) erros.push('dados não carregaram em ' + (r || 'início')); }
  await b.close(); srv.close();
  if (erros.length) { console.error('TESTE DE TELA FALHOU:\n- ' + [...new Set(erros)].join('\n- ')); process.exit(1); }
  console.log('Teste de tela ok: ' + rotas.length + ' páginas sem erro.');
});
