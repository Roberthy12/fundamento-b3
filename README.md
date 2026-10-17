# Fundamento B3

App web gratuito de análise de investimentos, no estilo do Status Invest. Reúne num só lugar:

| Classe | O que tem | Quantidade aproximada |
|---|---|---|
| Ações da B3 | indicadores comparados ao setor, busca avançada, rankings (Graham, Bazin, Fórmula Mágica), comparador | 576 |
| FIIs | dividend yield, P/VP, rendimentos, taxa de administração e composição da carteira | 318 |
| ETFs, BDRs, Fiagros e FI-Infra da B3 | cotação, variação em 12 meses, dividendos e liquidez | 1.200 |
| Ações do exterior | EUA acima de US$ 1 bilhão e as maiores de outros 21 mercados, com valuation, margens e rentabilidade | 4.100 |
| ETFs dos EUA | os 600 maiores por patrimônio, com taxa e retornos | 600 |
| Fundos de investimento | fundos abertos acima de R$ 50 milhões e com pelo menos 10 cotistas, com rentabilidade comparada ao CDI | 3.000 |
| Tesouro Direto | taxas e preços do dia e histórico de um ano de cada título | 58 |

A busca no topo encontra qualquer ativo de qualquer classe. Os favoritos ficam salvos no navegador.

Ele roda no navegador e pode ser instalado no celular como app:
- **iPhone:** abra o site no Safari, toque em Compartilhar e depois em **Adicionar à Tela de Início**.
- **Android:** abra o site no Chrome, toque em ⋮ e depois em **Instalar app**.

## Atualização automática
- O robô (`.github/workflows/publicar.yml`) roda de **segunda a sexta às 18:30 de Brasília**, coleta todas as classes e republica o site.
- Para atualizar na hora, vá em **Actions → Atualizar e publicar → Run workflow**.
- Uma alteração de código (push) só republica o site com os dados já publicados, sem nova coleta.
- Se a coleta de uma classe falhar, ela continua com os dados do dia anterior; as outras seguem normalmente.
- A fonte e a data de cada classe aparecem no rodapé da página correspondente.

### De onde vêm os dados
| Classe | Fonte |
|---|---|
| Ações da B3 | cotações do Yahoo Finance; ROE, margens, endividamento e crescimento da última coleta completa do Status Invest (hoje o Status Invest recusa os servidores do GitHub com erro 403). Com um token gratuito da brapi.dev salvo como `BRAPI_TOKEN` em **Settings → Secrets and variables → Actions**, o robô completa as cotações que faltarem. |
| FIIs | informe mensal dos FIIs na CVM (dados abertos) e cotações do Yahoo Finance |
| ETFs, BDRs, Fiagros e FI-Infra | Yahoo Finance |
| Exterior (ações e ETFs) | Yahoo Finance. Setor, margens, ROE e taxas dos ETFs são renovados aos poucos (até 1.500 ativos por execução, maiores primeiro), então os menores ganham esses dados ao longo dos primeiros dias. |
| Fundos | cadastro e informe diário da CVM; CDI do Banco Central |
| Tesouro Direto | Tesouro Transparente (preços e taxas oficiais) |

O GitHub pausa os agendamentos de repositórios públicos que ficam 60 dias sem nenhuma atividade. Se a aba Actions mostrar esse aviso, clique em **Enable workflow**.

## Custos
Tudo grátis:
- GitHub Pages e GitHub Actions, porque o repositório é público.
- Yahoo Finance, CVM, Banco Central e Tesouro Transparente, sem cadastro.
- brapi.dev no plano gratuito, se você ativar o token.

## Arquivos
```
index.html            o app (HTML, CSS e JavaScript)
acoes.json            ações da B3, atualizado pelo robô
atualizar_dados.py    coleta das ações da B3
robo/comum.py         funções compartilhadas (downloads, Yahoo Finance, gravação)
robo/fiis.py          FIIs                       -> dados/fiis.json
robo/b3.py            ETFs, BDRs, Fiagros, FI-Infra -> dados/b3.json
robo/exterior.py      ações e ETFs do exterior   -> dados/exterior.json, dados/etfs_exterior.json
robo/fundos.py        fundos de investimento     -> dados/fundos.json
robo/tesouro.py       Tesouro Direto             -> dados/tesouro.json
robo/indice.py        índice da busca            -> dados/busca.json
manifest.webmanifest  configuração para instalar como app
sw.js                 deixa o app abrir sem internet
*.png                 ícones
.github/workflows/publicar.yml  agenda a coleta e publica o site
```
Os robôs só usam a biblioteca padrão do Python. A pasta `dados/` é gerada a cada execução e não fica no repositório.

## Uso dos dados
Os dados vêm de fontes públicas e servem para estudo pessoal. Preço justo de Graham, preço-teto de Bazin, payout, checklist e simulações de renda são estimativas do próprio app. Rentabilidade passada não garante resultado futuro. Nada aqui é recomendação de investimento.
