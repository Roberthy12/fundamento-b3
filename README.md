# Fundamento B3

App web gratuito de análise fundamentalista de ações da B3. Mostra os indicadores de cada ação comparados aos pares do setor e tem busca avançada, rankings (Graham, Bazin, Fórmula Mágica), comparador e favoritos.

Ele roda no navegador e pode ser instalado no celular como app:
- **iPhone:** abra o site no Safari, toque em Compartilhar e depois em **Adicionar à Tela de Início**.
- **Android:** abra o site no Chrome, toque em ⋮ e depois em **Instalar app**.

## Atualização automática
- O robô (`.github/workflows/publicar.yml`) roda de **segunda a sexta às 18:30 de Brasília**.
- Ele executa `atualizar_dados.py`, que baixa os indicadores da busca avançada do Status Invest e grava em `acoes.json`. Depois republica o site.
- Para atualizar na hora, vá em **Actions → Atualizar e publicar → Run workflow**.
- A data da última atualização aparece no rodapé do app.

### Plano B (opcional e gratuito)
Use quando o Status Invest recusar o robô:
1. Crie uma conta em brapi.dev e gere um token. O plano gratuito permite 15 mil requisições por mês.
2. Salve o token em **Settings → Secrets and variables → Actions → New repository secret**, com o nome `BRAPI_TOKEN`.

A partir daí, quando o Status Invest falhar, o robô atualiza as cotações das ações com liquidez de pelo menos R$ 1 mi por dia e recalcula P/L, P/VP, DY e os demais múltiplos de preço. Se nada funcionar, o site continua no ar com os dados anteriores.

O GitHub pausa os agendamentos de repositórios públicos que ficam 60 dias sem nenhuma atividade. Se a aba Actions mostrar esse aviso, clique em **Enable workflow**.

## Custos
Tudo grátis:
- GitHub Pages, porque o repositório é público.
- GitHub Actions, que é gratuito em repositórios públicos.
- brapi.dev no plano gratuito, se você ativar o plano B.

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
Os indicadores vêm de páginas públicas do Status Invest e servem para estudo pessoal. Preço justo de Graham, preço-teto de Bazin, payout e checklist são estimativas do próprio app. Nada aqui é recomendação de investimento.
