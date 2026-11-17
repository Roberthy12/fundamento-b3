"""Empresas globais acompanhadas na aba Global: fundamentos trimestrais de fontes públicas.

Fontes:
- SEC (API de fatos XBRL, data.sec.gov): empresas americanas, com 14 trimestres reais e lucro por ação diluído.
- Yahoo Finance (séries fundamentais): TSMC, ASML e Brookfield, que entregam 20-F/40-F (sem trimestres no XBRL
  da SEC), e qualquer empresa em que a SEC falhar. O Yahoo traz poucos trimestres (cerca de 5).
- Yahoo Finance: cotação, valor de mercado e histórico mensal de preço.

Saída: dados/global.json. Não contém nenhum dado pessoal nem de carteira: só números públicos das empresas.
Pesos, custos e preços-alvo ficam no navegador de quem usa o app.
"""
import json
import math
import os
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from acoes import historico_mensal
from comum import DADOS, agora, log, salvar, Yahoo

SEC_UA = {"User-Agent": "Fundamento-B3 pesquisa publica (github.com/Roberthy12/fundamento-b3)", "Accept": "application/json"}

# símbolo, nome, setor, CIK na SEC (None = Yahoo), moeda dos balanços
EMPRESAS = [
    ("TSM", "Taiwan Semiconductor (TSMC)", "Semicondutores", None, "TWD"),
    ("HALO", "Halozyme Therapeutics", "Biotecnologia", 1159036, "USD"),
    ("BN", "Brookfield Corporation", "Gestão de ativos", None, "USD"),
    ("ASML", "ASML Holding", "Semicondutores", None, "EUR"),
    ("META", "Meta Platforms", "Internet e mídia", 1326801, "USD"),
    ("V", "Visa", "Pagamentos", 1403161, "USD"),
    ("NFLX", "Netflix", "Streaming", 1065280, "USD"),
    ("BKNG", "Booking Holdings", "Viagens", 1075531, "USD"),
    ("LIN", "Linde", "Gases industriais", 1707925, "USD"),
    ("CELH", "Celsius Holdings", "Bebidas", 1341766, "USD"),
    ("MA", "Mastercard", "Pagamentos", 1141391, "USD"),
    ("FTAI", "FTAI Aviation", "Aviação (locação)", 1590364, "USD"),
]
ETFS = [("DRAM", "Roundhill Memory ETF", "ETF de memórias")]
CAIXA = ("IB01", "TFLO")
REC = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
       "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"]
LUC = ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"]
EPS = ["EarningsPerShareDiluted", "IncomeLossFromContinuingOperationsPerDilutedShare", "EarningsPerShareBasicAndDiluted"]
NTRIM = 16
FX = {"USD": None, "EUR": "EURUSD=X", "TWD": "TWDUSD=X"}


def _dias(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _sec(cik):
    req = urllib.request.Request(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", headers=SEC_UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def _trimestres_sec(f, nomes, unit):
    """{data_fim: valor} do trimestre isolado; o 4º trimestre é o ano menos os nove meses (marcado em 'q4')."""
    gaap = f.get("facts", {}).get("us-gaap", {})
    out, q4 = {}, set()
    for nome in nomes:
        c = gaap.get(nome)
        if not c or unit not in (c.get("units") or {}):
            continue
        m = {}
        for x in c["units"][unit]:
            if not x.get("start") or not x.get("end"):
                continue
            k = (x["start"], x["end"])
            if k not in m or x.get("filed", "") > m[k].get("filed", ""):
                m[k] = x
        vals = list(m.values())
        parcial = {}
        for x in vals:
            if 80 <= _dias(x["start"], x["end"]) <= 100:
                parcial[x["end"]] = x["val"]
        for a in vals:
            if not 350 <= _dias(a["start"], a["end"]) <= 380:
                continue
            nove = [y for y in vals if y["start"] == a["start"] and 260 <= _dias(y["start"], y["end"]) <= 280]
            if nove and a["end"] not in parcial:
                n9 = max(nove, key=lambda y: y["end"])
                parcial[a["end"]] = a["val"] - n9["val"]
                q4.add(a["end"])
        for e, v in parcial.items():
            if e not in out:
                out[e] = v
    return out, q4


def dados_sec(cik):
    f = _sec(cik)
    rec, _ = _trimestres_sec(f, REC, "USD")
    luc, _ = _trimestres_sec(f, LUC, "USD")
    op, _ = _trimestres_sec(f, ["OperatingIncomeLoss"], "USD")
    lb, _ = _trimestres_sec(f, ["GrossProfit"], "USD")
    eps, q4eps = _trimestres_sec(f, EPS, "USD/shares")
    fins = sorted(set(rec) | set(luc))[-NTRIM:]
    return {e: {"receita": rec.get(e), "lb": lb.get(e), "ebit": op.get(e), "lucro": luc.get(e),
                "eps": None if e in q4eps else eps.get(e)} for e in fins}


def dados_base(t):
    """Trimestres da SEC guardados no repositório (robo/sec_trimestres.json), usados quando a SEC recusa o robô.
    O LPA do 4º trimestre (data 31/12) fica vazio: o valor da SEC é ano menos nove meses e não serve."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sec_trimestres.json"), encoding="utf-8") as fh:
            linhas = (json.load(fh).get("empresas") or {}).get(t) or []
    except Exception:
        return {}
    return {r[0]: {"receita": r[1], "lb": None, "ebit": r[2], "lucro": r[3], "eps": None if r[0][5:] == "12-31" else r[4]}
            for r in linhas}


def dados_yahoo(y, simbolo, taxa=1.0):
    tipos = ["TotalRevenue", "GrossProfit", "OperatingIncome", "NetIncomeCommonStockholders", "NetIncome", "DilutedEPS"]
    url = ("https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/"
           f"{urllib.parse.quote(simbolo)}?type={','.join('quarterly' + t for t in tipos)}&merge=false"
           f"&period1=946684800&period2={int(time.time())}")
    r = y.json(url, tentativas=2)
    campos = {"TotalRevenue": "receita", "GrossProfit": "lb", "OperatingIncome": "ebit",
              "NetIncomeCommonStockholders": "lucro", "NetIncome": "lucro2", "DilutedEPS": "eps"}
    out = {}
    for item in ((r.get("timeseries") or {}).get("result") or []):
        for tipo in (item.get("meta") or {}).get("type") or []:
            campo = campos.get(tipo.replace("quarterly", "", 1))
            if not campo:
                continue
            for x in item.get(tipo) or []:
                raw = ((x or {}).get("reportedValue") or {}).get("raw")
                if x and x.get("asOfDate") and raw is not None:
                    out.setdefault(x["asOfDate"], {})[campo] = float(raw)
    res = {}
    for e in sorted(out)[-NTRIM:]:
        v = out[e]
        res[e] = {"receita": v.get("receita"), "lb": v.get("lb"), "ebit": v.get("ebit"),
                  "lucro": v.get("lucro") if v.get("lucro") is not None else v.get("lucro2"), "eps": v.get("eps")}
    return res


def anual_yahoo(y, simbolo):
    """Anos fechados (até 5) e o balanço mais recente, do Yahoo, na moeda dos balanços."""
    anuais = {"TotalRevenue": "receita", "OperatingIncome": "ebit", "NetIncomeCommonStockholders": "lucro", "NetIncome": "lucro2",
              "DilutedEPS": "eps", "OperatingCashFlow": "fco", "CapitalExpenditure": "capex", "CashDividendsPaid": "div"}
    saldos = {"TotalDebt": "divida", "CashCashEquivalentsAndShortTermInvestments": "caixa", "CashAndCashEquivalents": "caixa2",
              "StockholdersEquity": "pl", "TotalAssets": "ativo"}
    tipos = ["annual" + t for t in anuais] + ["quarterly" + t for t in saldos]
    url = ("https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/"
           f"{urllib.parse.quote(simbolo)}?type={','.join(tipos)}&merge=false&period1=946684800&period2={int(time.time())}")
    r = y.json(url, tentativas=2)
    ano, bal = {}, {}
    for item in ((r.get("timeseries") or {}).get("result") or []):
        for tipo in (item.get("meta") or {}).get("type") or []:
            if tipo.startswith("annual"):
                campo, destino = anuais.get(tipo[6:]), ano
            else:
                campo, destino = saldos.get(tipo[9:]), bal
            if not campo:
                continue
            for x in item.get(tipo) or []:
                raw = ((x or {}).get("reportedValue") or {}).get("raw")
                if x and x.get("asOfDate") and raw is not None:
                    destino.setdefault(x["asOfDate"], {})[campo] = float(raw)
    anual = []
    for d in sorted(ano)[-5:]:
        v = ano[d]
        anual.append([d, v.get("receita"), v.get("ebit"), v.get("lucro") if v.get("lucro") is not None else v.get("lucro2"),
                      v.get("eps"), v.get("fco"), v.get("capex"), v.get("div")])
    ult = bal[max(bal)] if bal else {}
    caixa = ult.get("caixa") if ult.get("caixa") is not None else ult.get("caixa2")
    balanco = {"data": max(bal) if bal else None, "divida": ult.get("divida"), "caixa": caixa, "pl": ult.get("pl"),
               "ativo": ult.get("ativo"),
               "divida_liquida": ult["divida"] - caixa if ult.get("divida") is not None and caixa is not None else None}
    return anual, balanco


def completar_eps(q, y_eps):
    """LPA que falta (4º trimestre, ou emissora sem LPA no XBRL): Yahoo; senão estimado com as ações do trimestre anterior."""
    datas = sorted(q)
    for i, e in enumerate(datas):
        v = q[e]
        v["eps_est"] = False
        if v.get("eps") is None and y_eps.get(e, {}).get("eps") is not None:
            v["eps"] = y_eps[e]["eps"]
        if v.get("eps") is None and v.get("lucro") is not None and i > 0:
            ant = q[datas[i - 1]]
            if ant.get("lucro") and ant.get("eps"):
                acoes = ant["lucro"] / ant["eps"]
                if acoes:
                    v["eps"], v["eps_est"] = round(v["lucro"] / acoes, 2), True
    # lucro por ação só dos últimos 8 trimestres: antes disso pode estar sem ajuste de desdobramento
    for e in datas[:-8]:
        q[e]["eps"] = None


def main():
    y = Yahoo()
    simbolos = [e[0] for e in EMPRESAS] + [e[0] for e in ETFS] + list(CAIXA) + [v for v in FX.values() if v]
    cot = y.cotacoes(simbolos)
    fx = {m: (cot.get(s) or {}).get("regularMarketPrice") if s else 1.0 for m, s in FX.items()}
    empresas = []
    for t, nome, setor, cik, moeda in EMPRESAS:
        try:
            q, fonte = None, None
            y_q = {}
            try:
                y_q = dados_yahoo(y, t)
            except Exception as ex:
                log(f"  {t}: Yahoo trimestres: {ex}")
            if cik:
                try:
                    q, fonte = dados_sec(cik), "SEC (formulários 10-Q e 10-K)"
                except Exception as ex:
                    log(f"  {t}: SEC: {ex}")
            if not q:
                base = dados_base(t)
                if base:   # histórico da SEC guardado + trimestres mais novos do Yahoo
                    q, fonte = base, "SEC (histórico guardado) e Yahoo Finance"
                    for e, v in y_q.items():
                        if e in q:
                            for c, x in v.items():
                                if q[e].get(c) is None and x is not None:
                                    q[e][c] = x
                        else:
                            q[e] = v
                    q = dict(sorted(q.items())[-NTRIM:])
            if not q:
                q, fonte = y_q, "Yahoo Finance"
            if not q:
                log(f"  {t}: sem demonstrações")
                continue
            completar_eps(q, y_q)
            ult4 = [q[e] for e in sorted(q)[-4:]]
            ttm = None
            if len(ult4) == 4:
                soma = lambda c: round(sum(v[c] for v in ult4), 4) if all(v.get(c) is not None for v in ult4) else None
                ttm = {"receita": soma("receita"), "lucro": soma("lucro"), "eps": soma("eps"), "ebit": soma("ebit")}
            qt = cot.get(t) or {}
            mcap, preco = qt.get("marketCap"), qt.get("regularMarketPrice")
            taxa = fx.get(moeda)
            pl = None
            if mcap and ttm and ttm.get("lucro") and ttm["lucro"] > 0 and taxa:
                pl = round(mcap / (ttm["lucro"] * taxa), 2)
            try:
                mensal = [[m[0], m[1]] for m in historico_mensal(y, t, 6)[0]]
            except Exception as ex:
                log(f"  {t}: preços mensais: {ex}")
                mensal = []
            try:
                anual, balanco = anual_yahoo(y, t)
            except Exception as ex:
                log(f"  {t}: anual e balanço: {ex}")
                anual, balanco = [], {}
            empresas.append({
                "anual": anual, "balanco": balanco,
                "t": t, "nome": nome, "setor": setor, "moeda": moeda, "fonte": fonte, "preco": preco,
                "mcap_usd": mcap, "pl": pl, "pl_yahoo": qt.get("trailingPE"), "pl_proj": qt.get("forwardPE"),
                "dy": qt.get("trailingAnnualDividendYield"), "pvp": qt.get("priceToBook"),
                "max52": qt.get("fiftyTwoWeekHigh"), "min52": qt.get("fiftyTwoWeekLow"),
                "ttm": ttm, "mensal": mensal,
                "trimestres": [[e, v.get("receita"), v.get("lb"), v.get("ebit"), v.get("lucro"), v.get("eps"),
                                1 if v.get("eps_est") else 0] for e, v in sorted(q.items())]})
            log(f"  {t}: {len(q)} trimestres, fonte {fonte}")
        except Exception as ex:
            log(f"  {t}: falhou: {ex}")
        time.sleep(0.5)
    etfs = []
    for t, nome, setor in ETFS:
        qt = cot.get(t) or {}
        try:
            mensal = [[m[0], m[1]] for m in historico_mensal(y, t, 6)[0]]
        except Exception as ex:
            log(f"  {t}: preços mensais: {ex}")
            mensal = []
        etfs.append({"t": t, "nome": nome, "setor": setor, "preco": qt.get("regularMarketPrice"),
                     "max52": qt.get("fiftyTwoWeekHigh"), "min52": qt.get("fiftyTwoWeekLow"), "mensal": mensal})
    caixa = [{"t": t, "preco": (cot.get(t) or {}).get("regularMarketPrice")} for t in CAIXA]
    salvar("global.json", {"atualizado": agora(), "fx": fx, "empresas": empresas, "etfs": etfs, "caixa": caixa})
    log(f"OK: {len(empresas)} empresas, {len(etfs)} ETFs")


if __name__ == "__main__":
    main()
