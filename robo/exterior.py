"""Ações e ETFs do exterior pelo Yahoo Finance.

- EUA: todas as ações acima de US$ 1 bilhão de valor de mercado (NYSE, Nasdaq e NYSE American).
- Outros 21 mercados: as maiores empresas de cada bolsa, sem as listagens cruzadas.
- ETFs americanos: os 600 maiores por patrimônio.
Os fundamentos (setor, ROE, margens, dívida etc.) vêm de uma consulta por ativo e ficam num
cache (dados/cache_fundamentos.json), renovado aos poucos a cada execução.

Grava dados/exterior.json e dados/etfs_exterior.json.
"""
import os
import re
import sys
import time

from comum import Yahoo, dy_yahoo, e, eq, gt, ler, log, mudanca_12m, num, ou, pct, salvar, tabela

MAX_FUNDAMENTOS = int(os.environ.get("MAX_FUNDAMENTOS", "1500"))
RENOVAR_DIAS = 20

# código, nome, região do Yahoo, bolsas, moedas do balanço aceitas, quantidade
MERCADOS = [
    ("EUA", "Estados Unidos", "us", ["NMS", "NYQ", "NGM", "NCM", "ASE"], None, 6000),
    ("CAN", "Canadá", "ca", ["TOR"], ["CAD", "USD"], 150),
    ("GBR", "Reino Unido", "gb", ["LSE"], ["GBP", "GBp", "USD", "EUR"], 200),
    ("FRA", "França", "fr", ["PAR"], ["EUR"], 120),
    ("DEU", "Alemanha", "de", ["GER"], ["EUR"], 120),
    ("NLD", "Holanda", "nl", ["AMS"], ["EUR", "USD"], 60),
    ("CHE", "Suíça", "ch", ["EBS"], ["CHF", "USD", "EUR"], 80),
    ("ITA", "Itália", "it", ["MIL"], ["EUR"], 80),
    ("ESP", "Espanha", "es", ["MCE"], ["EUR"], 60),
    ("SWE", "Suécia", "se", ["STO"], ["SEK", "EUR"], 60),
    ("DNK", "Dinamarca", "dk", ["CPH"], ["DKK", "EUR"], 40),
    ("JPN", "Japão", "jp", ["JPX"], ["JPY"], 250),
    ("CHN", "China", "cn", ["SHH", "SHZ"], ["CNY"], 200),
    ("HKG", "Hong Kong", "hk", ["HKG"], ["HKD", "CNY", "USD"], 150),
    ("TWN", "Taiwan", "tw", ["TAI"], ["TWD"], 100),
    ("KOR", "Coreia do Sul", "kr", ["KSC"], ["KRW"], 100),
    ("IND", "Índia", "in", ["NSI"], ["INR"], 150),
    ("AUS", "Austrália", "au", ["ASX"], ["AUD", "USD"], 100),
    ("SGP", "Singapura", "sg", ["SES"], ["SGD", "USD"], 30),
    ("MEX", "México", "mx", ["MEX"], ["MXN", "USD"], 40),
    ("CHL", "Chile", "cl", ["SGO"], ["CLP", "USD"], 30),
    ("ARG", "Argentina", "ar", ["BUE"], ["ARS", "USD"], 30),
]
PAIS_MERCADO = {"United States": "EUA", "Canada": "CAN", "United Kingdom": "GBR", "France": "FRA",
                "Germany": "DEU", "Netherlands": "NLD", "Switzerland": "CHE", "Italy": "ITA", "Spain": "ESP",
                "Sweden": "SWE", "Denmark": "DNK", "Japan": "JPN", "China": "CHN", "Hong Kong": "HKG",
                "Taiwan": "TWN", "South Korea": "KOR", "India": "IND", "Australia": "AUS", "Singapore": "SGP",
                "Mexico": "MEX", "Chile": "CHL", "Argentina": "ARG"}
SETORES = {"Technology": "Tecnologia", "Healthcare": "Saúde", "Financial Services": "Financeiro",
           "Consumer Cyclical": "Consumo cíclico", "Consumer Defensive": "Consumo não cíclico",
           "Industrials": "Bens industriais", "Energy": "Petróleo, gás e energia", "Utilities": "Utilidade pública",
           "Basic Materials": "Materiais básicos", "Real Estate": "Imobiliário",
           "Communication Services": "Comunicações"}
PAISES = {"United States": "Estados Unidos", "Canada": "Canadá", "United Kingdom": "Reino Unido",
          "France": "França", "Germany": "Alemanha", "Netherlands": "Holanda", "Switzerland": "Suíça",
          "Italy": "Itália", "Spain": "Espanha", "Sweden": "Suécia", "Denmark": "Dinamarca", "Japan": "Japão",
          "China": "China", "Hong Kong": "Hong Kong", "Taiwan": "Taiwan", "South Korea": "Coreia do Sul",
          "India": "Índia", "Australia": "Austrália", "Singapore": "Singapura", "Mexico": "México",
          "Chile": "Chile", "Argentina": "Argentina", "Ireland": "Irlanda", "Israel": "Israel",
          "Brazil": "Brasil", "Bermuda": "Bermudas", "Cayman Islands": "Ilhas Cayman", "Belgium": "Bélgica",
          "Norway": "Noruega", "Finland": "Finlândia", "Luxembourg": "Luxemburgo", "Uruguay": "Uruguai",
          "Jersey": "Jersey", "Puerto Rico": "Porto Rico", "Greece": "Grécia", "South Africa": "África do Sul",
          "Austria": "Áustria", "Portugal": "Portugal", "Indonesia": "Indonésia", "Singapore ": "Singapura"}
ACOES_K = ["t", "n", "mkt", "bolsa", "cur", "price", "mcap", "pl", "plf", "pvp", "psr", "dy", "eps", "vpa",
           "var12", "liq", "setor", "ind", "pais", "roe", "roa", "mb", "mo", "ml", "de", "cr", "cl", "lc",
           "evebitda", "beta", "payout", "site"]
ETFS_K = ["t", "n", "cur", "price", "aum", "er", "dy", "var12", "ytd", "r3", "r5", "cat", "fam", "liq"]


def cambio(y, moedas):
    """{moeda: dólares por 1 unidade}."""
    moedas = set(moedas) | ({"GBP"} if "GBp" in moedas else set())
    pares = {m: f"USD{m}=X" for m in moedas if m not in ("USD", "GBp")}
    cot = y.cotacoes(list(pares.values()) + ["USDBRL=X"])
    fx = {"USD": 1.0}
    for m, s in pares.items():
        p = num((cot.get(s) or {}).get("regularMarketPrice"), 8)
        if p:
            fx[m] = 1 / p
    if "GBP" in fx:
        fx["GBp"] = fx["GBP"] / 100
    brl = num((cot.get("USDBRL=X") or {}).get("regularMarketPrice"), 6)
    return fx, brl


def listar(y):
    acoes = []
    for cod, nome, regiao, bolsas, moedas, qtd in MERCADOS:
        filtro = [eq("region", regiao), ou(*[eq("exchange", b) for b in bolsas]) if len(bolsas) > 1 else eq("exchange", bolsas[0])]
        if cod == "EUA":
            filtro.append(gt("intradaymarketcap", 1e9))
        try:
            lista = y.tela(e(*filtro), maximo=qtd if cod == "EUA" else qtd * 2)
        except Exception as ex:
            log(f"  {nome}: {ex}")
            continue
        n0 = len(acoes)
        for q in lista:
            if moedas and q.get("financialCurrency") and q["financialCurrency"] not in moedas:
                continue  # listagem cruzada de empresa estrangeira
            if not num(q.get("regularMarketPrice")):
                continue
            q["_mkt"] = cod
            acoes.append(q)
            if cod != "EUA" and len(acoes) - n0 >= qtd:
                break
        log(f"  {nome}: {len(acoes) - n0}")
    return acoes


def chave_nome(n):
    n = re.sub(r"[^A-Z0-9 ]", " ", (n or "").upper())
    n = re.sub(r"\b(INC|CORP|CORPORATION|LTD|LIMITED|PLC|SA|S A|AG|NV|N V|SE|SPA|S P A|AB|ASA|CO|COMPANY|GROUP|HOLDINGS?|THE|CLASS [A-Z])\b", " ", n)
    return " ".join(n.split())


LIQ_BDR = 1e6  # BDRs com liquidez diária acima de R$ 1 milhão ganham os fundamentos da empresa lá fora


def bdrs_extras(y, acoes):
    """Empresas de BDRs líquidos que ainda não estão na lista: entram pelo código (AAPL34 -> AAPL)."""
    have = {q["symbol"] for q in acoes}
    pedidos = {}
    b3 = ler("b3.json", {}) or {}
    k = b3.get("k") or []
    for a in b3.get("d", []):
        l = dict(zip(k, a))
        if l.get("tipo") == "BDR" and (l.get("liq") or 0) >= LIQ_BDR and l.get("sub") and l["sub"] not in have:
            pedidos[l["sub"]] = l
    if not pedidos:
        log("  BDRs líquidos sem empresa na lista: nenhum")
        return []
    cot = y.cotacoes(list(pedidos))
    extras, nomes = [], []
    for sim, q in cot.items():
        if not num(q.get("regularMarketPrice")):
            continue
        bdr_nome = {w for w in chave_nome(pedidos[sim].get("n") or "").split() if len(w) > 2 and w not in STOP_BDR}
        ext_nome = {w for w in chave_nome(q.get("longName") or q.get("shortName") or "").split() if len(w) > 2}
        if not bdr_nome & ext_nome:
            continue  # o código não confere com o nome do BDR: não entra
        q["_mkt"] = "EUA" if q.get("currency") == "USD" else "BDR"
        extras.append(q)
        nomes.append(sim)
    log(f"  BDRs líquidos com empresa lá fora: {len(extras)} de {len(pedidos)} ({', '.join(nomes[:25])})")
    return extras


STOP_BDR = {"INC", "CORP", "CORPORATION", "LTD", "LIMITED", "PLC", "SA", "NV", "GROUP", "HOLDINGS", "THE", "CO", "COMPANY", "ADR", "CLASS", "BDR", "DRS", "DR", "CLA"}


def renovar_cache(y, simbolos, etfs, prioridade=()):
    cache = ler("cache_fundamentos.json", {}) or {}
    agora = time.time()
    vazio = lambda s: len(cache.get(s) or {}) <= 1  # consulta anterior não trouxe nada: tenta de novo em 3 dias
    vencido = lambda s: agora - cache[s].get("ts", 0) > (3 if vazio(s) else RENOVAR_DIAS) * 86400
    # primeiro as empresas que têm BDR na B3 e ainda estão sem dados
    todos = set(simbolos)
    pri = [s for s in dict.fromkeys(prioridade) if s in todos and (s not in cache or (vazio(s) and vencido(s)))]
    fila = pri + [s for s in simbolos if s not in cache and s not in pri] + sorted(
        [s for s in simbolos if s in cache and s not in pri and vencido(s)],
        key=lambda s: cache[s].get("ts", 0))
    feitos, falhas = 0, 0
    for s in fila[:MAX_FUNDAMENTOS]:
        try:
            if s in etfs:
                r = y.resumo(s, "fundProfile,defaultKeyStatistics,summaryDetail")
                fp, ks, sd = r.get("fundProfile") or {}, r.get("defaultKeyStatistics") or {}, r.get("summaryDetail") or {}
                fee = (fp.get("feesExpensesInvestment") or {}).get("annualReportExpenseRatio")
                cache[s] = {"ts": int(agora), "cat": fp.get("categoryName"), "fam": fp.get("family"),
                            "er": pct(fee, 3) if fee else pct(ks.get("annualReportExpenseRatio"), 3),
                            "aum": num(ks.get("totalAssets") or sd.get("totalAssets"), 0), "ytd": pct(ks.get("ytdReturn")),
                            "r3": pct(ks.get("threeYearAverageReturn")), "r5": pct(ks.get("fiveYearAverageReturn")),
                            "yld": pct(sd.get("yield"))}
            else:
                r = y.resumo(s, "assetProfile,financialData,defaultKeyStatistics,summaryDetail")
                ap, fd = r.get("assetProfile") or {}, r.get("financialData") or {}
                ks, sd = r.get("defaultKeyStatistics") or {}, r.get("summaryDetail") or {}
                de = num(fd.get("debtToEquity"), 4)
                cache[s] = {"ts": int(agora), "setor": ap.get("sector"), "ind": ap.get("industry"),
                            "pais": ap.get("country"), "site": ap.get("website"),
                            "roe": pct(fd.get("returnOnEquity")), "roa": pct(fd.get("returnOnAssets")),
                            "mb": pct(fd.get("grossMargins")), "mo": pct(fd.get("operatingMargins")),
                            "ml": pct(fd.get("profitMargins")), "de": round(de / 100, 3) if de is not None else None,
                            "cr": pct(fd.get("revenueGrowth")), "cl": pct(fd.get("earningsGrowth")),
                            "lc": num(fd.get("currentRatio"), 2), "evebitda": num(ks.get("enterpriseToEbitda"), 2),
                            "beta": num(ks.get("beta"), 2), "payout": pct(sd.get("payoutRatio")),
                            "psr": num(sd.get("priceToSalesTrailing12Months") or ks.get("priceToSalesTrailing12Months"), 2)}
            feitos, falhas = feitos + 1, 0
        except Exception as ex:
            falhas += 1
            if "404" in str(ex):
                cache[s] = {"ts": int(agora)}
            if falhas >= 20:
                log(f"  fundamentos: Yahoo parou de responder ({ex})")
                break
        time.sleep(0.25)
        if feitos and feitos % 250 == 0:
            log(f"  fundamentos: {feitos} consultados")
    validos = set(simbolos)
    cache = {s: v for s, v in cache.items() if s in validos}
    salvar("cache_fundamentos.json", cache)
    faltam = sum(1 for s in simbolos if s not in cache)
    log(f"  fundamentos: {feitos} atualizados nesta execução; {faltam} ainda sem dados")
    return cache


def main():
    y = Yahoo()
    acoes = listar(y)
    acoes += bdrs_extras(y, acoes)
    etfs = y.tela(eq("region", "us"), tipo="ETF", ordem="fundnetassets", maximo=600)
    etfs = [q for q in etfs if num(q.get("regularMarketPrice"))]
    log(f"ações: {len(acoes)}; ETFs: {len(etfs)}")
    fx, brl = cambio(y, ({q.get("currency") for q in acoes} | {q.get("financialCurrency") for q in acoes}) - {None})
    simbolos_etf = {q["symbol"] for q in etfs}
    # fila de fundamentos: ETFs (são poucos) e depois as maiores empresas primeiro
    def em_dolar(q):
        cur = q.get("currency")
        return (num(q.get("marketCap")) or 0) * (fx.get("GBP" if cur == "GBp" else cur) or 0)
    ordem = [q["symbol"] for q in etfs] + [q["symbol"] for q in sorted(acoes, key=lambda q: -em_dolar(q))]
    # empresas com BDR negociado na B3 (casadas pelo nome, como o app faz na página do BDR)
    bdrs = {chave_nome(l[1]) for l in (ler("b3.json", {}) or {}).get("d", []) if len(l) > 2 and l[2] == "BDR"} - {""}
    prioridade = [q["symbol"] for q in acoes if chave_nome(q.get("longName") or q.get("shortName")) in bdrs]
    log(f"  {len(prioridade)} ações do exterior com BDR na B3")
    cache = renovar_cache(y, ordem, simbolos_etf, prioridade)

    linhas = []
    for q in acoes:
        s, cur = q["symbol"], q.get("currency")
        f = cache.get(s, {})
        preco = num(q.get("regularMarketPrice"))
        taxa = fx.get(cur)
        moeda_bal = q.get("financialCurrency") or cur
        taxa_mcap = fx.get("GBP" if cur == "GBp" else cur)
        linhas.append({
            "t": s, "n": (q.get("longName") or q.get("shortName") or "").strip(), "mkt": q["_mkt"],
            "bolsa": q.get("fullExchangeName") or q.get("exchange"), "cur": cur, "price": preco,
            "mcap": num((num(q.get("marketCap")) or 0) * taxa_mcap, 0) if taxa_mcap and q.get("marketCap") else None,
            "pl": num(q.get("trailingPE"), 2), "plf": num(q.get("forwardPE"), 2), "pvp": num(q.get("priceToBook"), 2),
            "psr": f.get("psr"), "dy": dy_yahoo(q), "eps": num(q.get("epsTrailingTwelveMonths"), 4),
            "vpa": num(q.get("bookValue"), 4), "var12": mudanca_12m(q),
            "liq": num((num(q.get("averageDailyVolume3Month")) or 0) * preco * taxa, 0) if taxa else None,
            "setor": SETORES.get(f.get("setor"), f.get("setor")), "ind": f.get("ind"),
            "pais": PAISES.get(f.get("pais"), f.get("pais")),
            **{c: f.get(c) for c in ("roe", "roa", "mb", "mo", "ml", "de", "cr", "cl", "lc", "evebitda", "beta", "payout", "site")},
            "_pais_en": f.get("pais"), "_moeda_bal": moeda_bal,
        })

    # mesma empresa em mais de uma bolsa: fica a listagem do país de origem (ou a mais negociada)
    grupos = {}
    for l in linhas:
        grupos.setdefault((chave_nome(l["n"]), l["_moeda_bal"]), []).append(l)
    finais = []
    for (nome, _), g in grupos.items():
        if len(g) == 1 or not nome:
            finais += g
            continue
        casa = [l for l in g if PAIS_MERCADO.get(l["_pais_en"]) == l["mkt"]]
        if casa:
            finais += casa
        else:
            finais.append(max(g, key=lambda l: l["liq"] or 0))
    finais.sort(key=lambda l: -(l["mcap"] or 0))
    salvar("exterior.json", tabela(ACOES_K, finais, fonte="Yahoo Finance", usdbrl=brl,
                                   mercados={c: n for c, n, *_ in MERCADOS}))

    linhas_etf = []
    for q in etfs:
        s = q["symbol"]
        f = cache.get(s, {})
        preco = num(q.get("regularMarketPrice"))
        linhas_etf.append({
            "t": s, "n": (q.get("longName") or q.get("shortName") or "").strip(), "cur": q.get("currency"),
            "price": preco, "aum": f.get("aum") or num(q.get("netAssets"), 0), "er": f.get("er"),
            "dy": f.get("yld") if f.get("yld") is not None else dy_yahoo(q), "var12": mudanca_12m(q),
            "ytd": f.get("ytd"), "r3": f.get("r3"), "r5": f.get("r5"), "cat": f.get("cat"), "fam": f.get("fam"),
            "liq": num((num(q.get("averageDailyVolume3Month")) or 0) * preco, 0),
        })
    salvar("etfs_exterior.json", tabela(ETFS_K, linhas_etf, fonte="Yahoo Finance", usdbrl=brl))
    log(f"OK: {len(finais)} ações e {len(linhas_etf)} ETFs do exterior")


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        log(f"Exterior falhou: {ex}")
        sys.exit(1)
