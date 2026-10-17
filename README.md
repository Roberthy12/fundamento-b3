# Fundamento B3

App web gratuito de análise fundamentalista de ações da B3. Mostra os indicadores de cada ação comparados aos pares do setor e tem busca avançada, rankings (Graham, Bazin, Fórmula Mágica), comparador e favoritos.

Ele roda no navegador e pode ser instalado no celular como app:
- **iPhone:** abra o site no Safari, toque em Compartilhar e depois em **Adicionar à Tela de Início**.
- **Android:** abra o site no Chrome, toque em ⋮ e depois em **Instalar app**.

## Atualização automática
- O robô (`.github/workflows/publicar.yml`) roda de **segunda a sexta às 18:30 de Brasília**.
- Ele executa `atualizar_dados.py`, grava o resultado em `acoes.json` e republica o site.
- Para atualizar na hora, vá em **Actions → Atualizar e publicar → Run workflow**.
- A data da última atualização e a fonte usada aparecem no rodapé do app.

### De onde vêm os dados
1. **Status Invest (todos os indicadores).** O robô tenta primeiro a busca avançada. O Status Invest recusa os servidores do GitHub (erro 403), então essa coleta completa hoje não acontece pelo robô.
2. **Yahoo Finance (cotações, sem cadastro).** Busca o preço de cada ação, de 20 em 20, e recalcula P/L, P/VP, DY, EV/EBIT e os demais múltiplos de preço. ROE, margens, endividamento e crescimento continuam os da última coleta completa. Variações acima de 50% num dia são ignoradas, porque costumam ser desdobramento ou grupamento.
3. **brapi.dev (opcional).** Com um token gratuito salvo em **Settings → Secrets and variables → Actions** com o nome `BRAPI_TOKEN`, o robô completa pela brapi as cotações das ações líquidas que o Yahoo não trouxer.

Se nada funcionar, o site continua no ar com os dados anteriores.

O GitHub pausa os agendamentos de repositórios públicos que ficam 60 dias sem nenhuma atividade. Se a aba Actions mostrar esse aviso, clique em **Enable workflow**.

## Custos
Tudo grátis:
- GitHub Pages, porque o repositório é público.
- GitHub Actions, que é gratuito em repositórios públicos.
- Yahoo Finance, sem cadastro.
- brapi.dev no plano gratuito, se você ativar o token.

## Arquivos
```
index.html            o app (HTML, CSS e JavaScript)
acoes.json            indicadores de todas as ações, atualizado pelo robô
atualizar_dados.py    coleta dos dados (só usa a biblioteca padrão do Python)
manifest.webmanifest  configuração para instalar como app
sw.js                 deixa o app abrir sem internet
*.png                 ícones
.github/workflows/publicar.yml  agenda a coleta e publica o site
```

## Uso dos dados
Os indicadores vêm de páginas públicas do Status Invest e as cotações do Yahoo Finance; servem para estudo pessoal. Preço justo de Graham, preço-teto de Bazin, payout e checklist são estimativas do próprio app. Nada aqui é recomendação de investimento.
