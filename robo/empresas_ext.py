"""Empresas de BDRs líquidos: mesmo formato de dados/empresas/<RAIZ>.json, com dados do Yahoo.

As empresas de fora não têm balanço na CVM, então as demonstrações vêm do endpoint de séries
fundamentais do Yahoo (anuais e trimestrais) e as cotações do gráfico mensal do Yahoo. Tudo é
convertido para reais pelo câmbio do dia. Os cálculos (indicadores por ano, Piotroski, Altman,
qualidade do lucro, lucro x cotação, médias de 5 anos) são os mesmos do robô brasileiro (acoes.py).
"""
import json
import math
import os
import time
import urllib.parse
from datetime import date, datetime, timedelta

from acoes import (CAMPOS_FLUXO, CAMPOS_SALDO, altman, cagr, historico_mensal, indicadores_periodo,
                   piotroski, qualidade_lucro, referencias, reta, sensibilidade)
from comum import DADOS, agora, log

# tipo do Yahoo -> campo do app (mesmos nomes de acoes.py)
TIPOS = {
    "TotalRevenue": "receita", "CostOfRevenue": "custo", "GrossProfit": "lb", "OperatingExpense": "desp",
    "OperatingIncome": "ebit", "InterestExpense": "fin", "TaxProvision": "ir", "NetIncome": "lucro",
    "NetIncomeCommonStockholders": "lucro_contr", "DepreciationAndAmortization": "da",
    "OperatingCashFlow": "fco", "InvestingCashFlow": "fci", "FreeCashFlow": "fcf",
    "CapitalExpenditure": "capex", "CashDividendsPaid": "div_pagos",
    "TotalAssets": "ativo", "CurrentAssets": "ac", "CashAndCashEquivalents": "caixa", "Inventory": "estoques",
    "CurrentLiabilities": "pc", "TotalNonCurrentLiabilitiesNetMinorityInterest": "pnc", "TotalDebt": "divida",
    "StockholdersEquity": "pl", "CommonStockEquity": "pl_contr", "RetainedEarnings": "reservas",
    "DilutedAverageShares": "acoes",
}
NEGATIVOS = {"fin", "capex", "div_pagos"}  # valores que saem do caixa ficam negativos, como no robô brasileiro
SALDOS = set(CAMPOS_SALDO)
FLUXOS = set(CAMPOS_FLUXO)
MESES_ULT = 12


def _url(simbolo):
    tipos = [p + t for t in TIPOS for p in ("annual", "quarterly")]
    agora_ts = int(time.time())
    return ("https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/"
            f"{urllib.parse.quote(simbolo)}?type={','.join(tipos)}&merge=false&period1=946684800&period2={agora_ts}")


def _series(r, taxa):
    """{'annual': {data: {campo: valor}}, 'quarterly': {...}} em reais (ações sem conversão)."""
    out = {"annual": {}, "quarterly": {}}
    for item in ((r.get("timeseries") or {}).get("result") or []):
        for tipo in (item.get("meta") or {}).get("type") or []:
            prefixo = "annual" if tipo.startswith("annual") else "quarterly"
            campo = TIPOS.get(tipo[len(prefixo):])
            if not campo:
                continue
            for x in item.get(tipo) or []:
                if not x or not x.get("asOfDate"):
                    continue
                raw = (x.get("reportedValue") or {}).get("raw")
                if raw is None:
                    continue
                if campo == "acoes":
                    v = float(raw)
                else:
                    v = float(raw) * taxa
                    if campo in NEGATIVOS:
                        v = -abs(v)
                    elif campo == "da":
                        v = abs(v)
                    v = round(v, 2)
                out[prefixo].setdefault(x["asOfDate"], {})[campo] = v
    return out


def _ttm(trim):
    """Últimos 4 trimestres somados nos fluxos; balanço do trimestre mais recente."""
    datas = sorted(trim)[-4:]
    if len(datas) < 4:
        return None, None
    ttm = {}
    for c in FLUXOS:
        vals = [trim[d].get(c) for d in datas]
        ttm[c] = round(sum(vals), 2) if all(v is not None for v in vals) else None
    if ttm.get("lucro_contr") is None:
        ttm["lucro_contr"] = ttm.get("lucro")
    return ttm, {c: trim[datas[-1]].get(c) for c in SALDOS}


def _lucro_x_cotacao(anual, ind_hist, mensal, fech_mes, lucro_c, ebit, vm, ref, hoje):
    """Tendência do lucro e da cotação, igual ao robô brasileiro (campos lc_*)."""
    if lucro_c is None or not mensal or not mensal[-1][1] or not vm:
        return {}
    corte = ""  # a série de preços só vale depois da última quebra no Yahoo
    for m in mensal:
        if m[2] is not None and m[2] <= 0:
            corte = m[0] + "~"
    for a, b in zip(mensal, mensal[1:]):
        if a[1] and b[1] and not 0.125 < b[1] / a[1] < 8:
            corte = max(corte, b[0])
    lucros = {int(a): v["lucro_contr"] for a, v in anual.items() if v.get("lucro_contr") is not None}
    fechados = [a for a in sorted(lucros) if date(a, 12, 31) < ref]
    pts = [(date(a, 12, 31), lucros[a], fech_mes.get(f"{a}-12"), (ind_hist.get(str(a)) or {}).get("vm"))
           for a in fechados if f"{a}-12" >= corte]
    pts = [p for p in pts if p[2] and p[3]] + [(ref, lucro_c, mensal[-1][1], vm)]
    maior = max(abs(p[1]) for p in pts)
    while pts and abs(pts[0][1]) < maior * 0.001:
        pts.pop(0)  # anos antes de a empresa operar
    k = len(pts)
    while k and pts[k - 1][1] > 0:
        k -= 1
    anos_ok = lambda ps: len(ps) >= 4 and (ps[-1][0] - ps[0][0]).days >= 3 * 365
    usa = pts[k:] if anos_ok(pts[k:]) else pts if anos_ok(pts) else None
    if not usa:
        return {}
    xs = [(p[0] - usa[0][0]).days / 365.25 for p in usa]
    T = xs[-1]
    if usa is not pts or k == 0:
        a, b, r2 = reta(xs, [math.log(p[1]) for p in usa]) if all(p[1] > 0 for p in usa) else (0, 0, 0)
        f0, f1, g_l = math.exp(a), math.exp(a + b * T), math.exp(b) - 1
    else:
        a, b, r2 = reta(xs, [p[1] for p in usa])
        f0, f1, g_l = a, a + b * T, None
    xp = xs[:-1] + [(hoje - usa[0][0]).days / 365.25]
    if not all(p[2] > 0 for p in usa):
        return {}
    _, bp, _ = reta(xp, [math.log(p[2]) for p in usa])
    vm0 = usa[0][3]
    if not vm0:
        return {}
    lc = {"lc_desde": usa[0][0].year, "lc_n": len(usa),
          "lc_lucro": round(g_l * 100, 2) if g_l is not None else None,
          "lc_cot": round((math.exp(bp) - 1) * 100, 2), "lc_r2": round(r2, 2),
          "lc_t0": round(f0), "lc_t1": round(f1),
          "lc_y0": round(usa[0][1] / vm0 * 100, 2), "lc_yc": round(lucro_c / vm0 * 100, 2),
          "lc_yh": round(lucro_c / vm * 100, 2)}
    ant = [lucros[a] for a in fechados[-3:]]
    if len(ant) == 3 and sum(ant) > 0:
        lc["lc_salto"] = round(lucro_c / (sum(ant) / 3), 2)
    if ebit and ebit > 0 and lucro_c > 0:
        lc["lc_op"] = round(lucro_c / ebit, 2)
    return lc


def _moeda_cotacao(y, simbolo):
    """Moeda em que o Yahoo mostra a cotação (pode ser diferente da moeda das demonstrações)."""
    r = y.json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(simbolo)}?range=1mo&interval=1d")
    return ((r.get("chart") or {}).get("result") or [{}])[0].get("meta", {}).get("currency")


def exportar(y, simbolo, moeda, fx, usdbrl, nome="", refs=None):
    """Grava dados/empresas_ext/<SIMBOLO>.json. Retorna True se gravou.

    Demonstrações são convertidas pela moeda que o balanço é publicado (moeda); cotações e proventos
    pela moeda em que a ação é negociada. Ex.: INTR reporta em BRL e negocia em USD.
    """
    taxa = (fx.get(moeda) or 0) * (usdbrl or 0)
    if not taxa:
        return False
    moeda_px = _moeda_cotacao(y, simbolo)
    taxa_px = (fx.get(moeda_px) or 0) * (usdbrl or 0)
    if not taxa_px:
        log(f"  {simbolo}: moeda da cotação {moeda_px} sem câmbio")
        return False
    s = _series(y.json(_url(simbolo)), taxa)
    bruto = s["annual"]
    if len(bruto) < 2:
        log(f"  {simbolo}: sem demonstrações anuais no Yahoo")
        return False
    datas = sorted(bruto)[-10:]
    acoes = next((bruto[d]["acoes"] for d in reversed(datas) if bruto[d].get("acoes")), None)
    if acoes is None:
        acoes = next((s["quarterly"][d]["acoes"] for d in sorted(s["quarterly"], reverse=True)
                      if s["quarterly"][d].get("acoes")), None)

    # cotação mensal em reais, proventos e fechamento por mês
    mensal_nat, divs = historico_mensal(y, simbolo)
    mensal = [[m, round(c * taxa_px, 4), round(a * taxa_px, 4)] for m, c, a in mensal_nat]
    fech = {m[0]: m[1] for m in mensal}
    try:
        sens = sensibilidade(mensal, refs) if refs and mensal else None
    except Exception as ex:
        log(f"  {simbolo}: sensibilidade: {ex}")
        sens = None
    dpa_ano = {}
    for data, valor in divs:
        dpa_ano[data[:4]] = dpa_ano.get(data[:4], 0) + valor * taxa_px
    tem_divs = bool(divs)

    anual, ind_hist = {}, {}
    for d in datas:
        v = bruto[d]
        ano = d[:4]
        lucro = v.get("lucro")
        lc_ = v.get("lucro_contr") if v.get("lucro_contr") is not None else lucro
        ebit, da = v.get("ebit"), v.get("da")
        vv = {c: v.get(c) for c in FLUXOS}
        vv["lucro_contr"], vv["lucro"] = lc_, lucro
        ebitda = ebit + abs(da) if ebit is not None and da is not None else None
        anual[ano] = {**{c: vv.get(c) for c in CAMPOS_FLUXO}, "ebitda": ebitda, **{c: v.get(c) for c in CAMPOS_SALDO}}
        sd = {c: v.get(c) for c in SALDOS}
        preco = fech.get(d[:7]) or fech.get(f"{ano}-12")
        dpa = dpa_ano.get(ano, 0 if tem_divs else None)
        ind_hist[ano] = indicadores_periodo(vv, sd, preco, acoes, 1, dpa)

    ttm, bal = _ttm(s["quarterly"])
    if ttm is None:  # sem trimestres: último ano fechado
        ult = bruto[datas[-1]]
        ttm = {c: ult.get(c) for c in FLUXOS}
        bal = {c: ult.get(c) for c in SALDOS}
        ttm_ate = datas[-1]
    else:
        ttm_ate = sorted(s["quarterly"])[-1]
    ref = date.fromisoformat(ttm_ate[:10])

    # preço atual e linha da empresa (o que a página usa para cotação, valor de mercado e lucro por ação)
    hoje_dt = datetime.now().date()
    preco_hoje = mensal[-1][1] if mensal else None
    vm = preco_hoje * acoes if preco_hoje and acoes else None
    lucro_c = ttm.get("lucro_contr") if ttm else None
    lpa = lucro_c / acoes if lucro_c is not None and acoes else None
    vpa = bal.get("pl_contr") / acoes if bal and bal.get("pl_contr") is not None and acoes else None
    dpa12 = sum(valor * taxa_px for data, valor in divs if data >= (hoje_dt - timedelta(days=365)).isoformat())
    ult12 = [m for m in mensal[-MESES_ULT:]]
    linha = {
        "price": preco_hoje, "valormercado": vm,
        "p_l": round(preco_hoje / lpa, 2) if lpa and lpa > 0 and preco_hoje else None,
        "p_vp": round(preco_hoje / vpa, 2) if vpa and vpa > 0 and preco_hoje else None,
        "dpa": round(dpa12, 4) if divs else None,
        "dy": round(dpa12 / preco_hoje * 100, 2) if divs and preco_hoje and dpa12 / preco_hoje <= 1 else None,
        "max52": max((m[1] for m in ult12), default=None), "min52": min((m[1] for m in ult12), default=None),
        "lpa": round(lpa, 4) if lpa is not None else None, "vpa": round(vpa, 4) if vpa is not None else None,
    }

    # médias dos últimos 5 anos (mesma regra do robô brasileiro: sem extremos e só valores positivos onde faz sentido)
    ult5 = [ind_hist[a] for a in sorted(ind_hist)[-5:]]
    def media(campo, so_pos=False):
        xs = [x[campo] for x in ult5 if x.get(campo) is not None and (not so_pos or 0 < x[campo] <= 1000)]
        return round(sum(xs) / len(xs), 2) if len(xs) >= 3 else None
    for campo, nome_m, so_pos in (("p_l", "pl_medio5", True), ("p_vp", "pvp_medio5", True), ("dy", "dy_media5", False),
                                  ("roe", "roe_media5", False)):
        linha[nome_m] = media(campo, so_pos)
    # médias de 2 e 10 anos (mesma regra)
    def media_n(campo, n, so_pos=False):
        uit = [ind_hist[a] for a in sorted(ind_hist)[-n:]]
        xs = [x[campo] for x in uit if x.get(campo) is not None and (not so_pos or 0 < x[campo] <= 1000)]
        return round(sum(xs) / len(xs), 2) if len(xs) >= (2 if n == 2 else 3) else None
    for campo, nome_m, so_pos in (("p_l", "pl_medio", True), ("p_vp", "pvp_medio", True), ("dy", "dy_media", False),
                                  ("roe", "roe_media", False)):
        linha[nome_m + "2"] = media_n(campo, 2, so_pos)
        linha[nome_m + "10"] = media_n(campo, 10, so_pos)

    anos_lucro = 0
    for a in sorted(anual, reverse=True):
        if (anual[a].get("lucro_contr") or 0) > 0:
            anos_lucro += 1
        else:
            break
    anos_div = None
    if divs:
        anos_div = 0
        for a in range(hoje_dt.year - 1, hoje_dt.year - 11, -1):
            if dpa_ano.get(str(a), 0) > 0:
                anos_div += 1
            else:
                break
    linha["anos_lucro"], linha["anos_div"] = anos_lucro, anos_div

    por_ano = {int(a): v for a, v in anual.items()}
    linha["receitas_cagr5"] = cagr(por_ano, "receita")
    linha["lucros_cagr5"] = cagr(por_ano, "lucro_contr")
    linha["fin"] = False
    linha.update(_lucro_x_cotacao(anual, ind_hist, mensal, fech, lucro_c, ttm.get("ebit") if ttm else None,
                                  vm, ref, hoje_dt))

    a12 = mensal[-13][2] if len(mensal) > 13 else None
    a60 = mensal[-61][2] if len(mensal) > 61 else None
    adj = mensal[-1][2] if mensal else None
    pos = lambda x: x is not None and x > 0
    linha["ret12"] = round((adj / a12 - 1) * 100, 2) if pos(adj) and pos(a12) else None
    linha["ret60"] = round(((adj / a60) ** (1 / 5) - 1) * 100, 2) if pos(adj) and pos(a60) else None

    pio = None
    try:
        pio = piotroski(anual, {})
    except Exception:
        pio = None
    alt = altman(bal or {}, ttm or {}) if bal and ttm else None
    qual = qualidade_lucro(anual, ttm or {}, bal or {}) if ttm and bal else None

    out = {
        "atualizado": agora(), "raiz": simbolo, "nome": nome, "origem": "Yahoo Finance", "moeda": "BRL", "moeda_cotacao": moeda_px, "moeda_balanco": moeda,
        "cvm": None, "bdr": True, "ttm_ate": ttm_ate, "ttm": ttm, "balanco": bal,
        "anual": anual, "ind_hist": ind_hist, "medias5": {k: v for k, v in linha.items() if k.endswith("_medio5") or k.endswith("_media5")},
        "linha": linha,
        "precos": {"codigo": simbolo, "mensal": mensal, "ret12": linha["ret12"], "ret60": linha["ret60"]},
        "dividendos": {"fonte": "Yahoo Finance", "codigo": simbolo,
                       "por_ano": {a: round(v, 4) for a, v in sorted(dpa_ano.items())}},
        "piotroski": pio, "altman": alt, "qualidade": qual, "sens": sens,
    }
    caminho = os.path.join(DADOS, "empresas_ext")
    os.makedirs(caminho, exist_ok=True)
    tmp = os.path.join(caminho, simbolo + ".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, os.path.join(caminho, simbolo + ".json"))
    return True


def exportar_todas(y, alvo, fx, brl, nomes=None):
    """alvo: {simbolo: moeda das demonstrações}. Uma empresa com erro não derruba as outras."""
    nomes = nomes or {}
    try:
        refs = referencias(y, {})  # Ibovespa, dólar, petróleo, CDI: para beta e sensibilidade
    except Exception as ex:
        log(f"  referências para sensibilidade: {ex}")
        refs = None
    feitas, falhas = 0, 0
    for simbolo, moeda in alvo.items():
        try:
            if exportar(y, simbolo, moeda, fx, brl, nomes.get(simbolo, ""), refs):
                feitas += 1
        except Exception as ex:
            falhas += 1
            log(f"  empresa {simbolo}: {ex}")
            if falhas >= 25:
                log("  empresas do exterior: muitas falhas, parando")
                break
        time.sleep(0.25)
    log(f"  empresas do exterior: {feitas} gravadas de {len(alvo)}")
    return feitas
