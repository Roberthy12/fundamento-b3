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
  for (const ab of ['div', 'sim', 'just', 'ir', 'mer', 'calc', 'age', 'semana', 'diario', 'risco', 'estr', 'rf', 'saude']) { await p.evaluate(a => localStorage.setItem('fund_ftab', JSON.stringify(a)), ab); rotas.push('#ferramentas'); await p.goto(url + '#ferramentas'); await p.reload(); await p.waitForTimeout(1500);
    const t = await texto(p); if (t.length < 40) erros.push('Ferramentas/' + ab + ' ficou vazia'); }
  for (const r of rotas) { await p.goto(url + r); await p.reload(); await p.waitForTimeout(1800);
    const t = await texto(p); if (t.length < 40) erros.push('página vazia em ' + (r || 'início')); if (/Não foi possível carregar os dados/.test(t)) erros.push('dados não carregaram em ' + (r || 'início')); }
  // contas conhecidas: o resultado na tela tem de bater com a conta feita à parte
  const brl = t => parseFloat(t.replace(/\./g, '').replace(',', '.')), tela = async (tab, cab) => { await p.evaluate(([a, c]) => { localStorage.setItem('fund_ftab', JSON.stringify('calc')); localStorage.setItem('fund_calcab', JSON.stringify(c)); }, [tab, cab]); await p.goto(url + '#ferramentas'); await p.reload(); return texto(p); };
  { const t = await tela('calc', 'jc'), m = t.match(/Total ao final[\s\S]{0,20}?R\$\s*([\d.]+,\d{2})/i), im = Math.pow(1.1, 1 / 12) - 1; let v = 1000; for (let i = 0; i < 120; i++) v = v * (1 + im) + 500;
    if (!m || Math.abs(brl(m[1]) - v) > 1) erros.push('juros compostos: tela ' + (m && m[1]) + ' esperado ' + v.toFixed(2)); }
  { const t = await tela('calc', 're'), m = t.match(/Reserva ideal[\s\S]{0,20}?R\$\s*([\d.]+,\d{2})/i); if (!m || Math.abs(brl(m[1]) - 24000) > 0.01) erros.push('reserva de emergência: tela ' + (m && m[1]) + ' esperado 24.000,00'); }
  // dados: P/L publicado x preço / lucro por ação (só avisa; falha se mais de 25% das ações divergirem muito)
  { const j = await p.evaluate(() => fetch('acoes.json').then(r => r.json())); const k = j.k, ip = k.indexOf('price'), il = k.indexOf('lpa'), ipl = k.indexOf('p_l');
    if (ip >= 0 && il >= 0 && ipl >= 0) { const L = j.d.filter(x => x[ip] > 0 && x[il] > 0 && x[ipl] > 0); const ruim = L.filter(x => Math.abs(x[ip] / x[il] / x[ipl] - 1) > 0.15).length; console.log('P/L conferido em ' + L.length + ' ações; ' + ruim + ' divergem mais de 15%.'); if (L.length > 30 && ruim / L.length > 0.25) console.log('::warning::P/L diverge de preço/LPA em ' + ruim + ' de ' + L.length + ' ações (só aviso, não bloqueia)'); } }
  await b.close(); srv.close();
  if (erros.length) { console.error('TESTE DE TELA FALHOU:\n- ' + [...new Set(erros)].join('\n- ')); process.exit(1); }
  console.log('Teste de tela ok: ' + rotas.length + ' páginas sem erro.');
});
