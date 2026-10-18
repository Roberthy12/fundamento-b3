# Fundamento B3

App web gratuito de análise de investimentos. Todos os indicadores são calculados pelo próprio app a partir de dados oficiais (CVM, B3, Banco Central e Tesouro), sem depender de outros sites de análise. Reúne num só lugar:

| Classe | O que tem | Quantidade aproximada |
|---|---|---|
| Ações da B3 | 30 indicadores comparados ao setor; resultado, balanço e fluxo de caixa de até 10 anos, últimos 12 meses e trimestres; proventos com data com e pagamento; gráficos de evolução e cotação; busca avançada, rankings (Graham, Bazin, Fórmula Mágica), comparador | 400 |
| FIIs | dividend yield, P/VP, rendimentos, taxa de administração e composição da carteira | 320 |
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
| Ações da B3 | **CVM**: demonstrações anuais (DFP) e trimestrais (ITR) de cada companhia, das quais o app calcula receita, lucro, EBITDA, dívida, fluxo de caixa e os últimos 12 meses. **B3**: lista de empresas listadas, códigos de negociação, setor oficial, quantidade de ações e proventos declarados. **Yahoo Finance**: cotação, volume e histórico mensal de preços. Ações sem negócio há mais de 30 dias saem da lista. |
| FIIs | informe mensal dos FIIs na CVM (dados abertos) e cotações do Yahoo Finance |
| ETFs, BDRs, Fiagros e FI-Infra | Yahoo Finance |
| Exterior (ações e ETFs) | Yahoo Finance. Setor, margens, ROE e taxas dos ETFs são renovados aos poucos (até 1.500 ativos por execução, maiores primeiro). |
| Fundos | cadastro e informe diário da CVM; CDI do Banco Central |
| Tesouro Direto | Tesouro Transparente (preços e taxas oficiais) |

Como os indicadores das ações são calculados:
- **Últimos 12 meses** = último ano completo + acumulado do ano corrente − mesmo período do ano anterior, usando as demonstrações consolidadas (ou individuais, quando a empresa não consolida).
- **LPA e VPA** usam o lucro e o patrimônio dos controladores divididos pelas ações em circulação (sem as de tesouraria).
- **Dividend yield** soma os proventos com data com nos últimos 12 meses, por código (ON, PN ou unit), com os juros sobre capital próprio pelo valor bruto.
- **Dívida líquida** = empréstimos e financiamentos de curto e longo prazo − caixa e aplicações. Para bancos e seguradoras, indicadores de dívida, EBIT e liquidez não se aplicam.
- **EBITDA** = EBIT + depreciação e amortização da demonstração de fluxo de caixa.

O GitHub pausa os agendamentos de repositórios públicos que ficam 60 dias sem nenhuma atividade. Se a aba Actions mostrar esse aviso, clique em **Enable workflow**.

## Custos
Tudo grátis:
- GitHub Pages e GitHub Actions, porque o repositório é público.
- CVM, B3, Banco Central, Tesouro Transparente e Yahoo Finance, sem cadastro.

## Arquivos
```
index.html            o app (HTML, CSS e JavaScript)
robo/comum.py         funções compartilhadas (downloads, Yahoo Finance, gravação)
robo/acoes.py         ações da B3                -> acoes.json e dados/empresas/<RAIZ>.json
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
Os robôs só usam a biblioteca padrão do Python. Os arquivos de dados são gerados a cada execução e não ficam no repositório.

## Uso dos dados
Os dados vêm de fontes públicas e servem para estudo pessoal. Preço justo de Graham, preço-teto de Bazin, checklist e simulações de renda são estimativas do próprio app. Rentabilidade passada não garante resultado futuro. Nada aqui é recomendação de investimento.
