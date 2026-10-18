"""Ações da B3 calculadas a partir de fontes oficiais.

- B3 (API pública de empresas listadas): códigos de negociação, setor, quantidade de ações
  e proventos dos últimos 12 meses.
- CVM (dados abertos): demonstrações anuais (DFP) e trimestrais (ITR) de todas as companhias.
- Yahoo Finance: cotação, volume médio e histórico mensal de preços.

Todos os indicadores são calculados aqui, com os 12 últimos meses de resultados.
Gera acoes.json (lista do app) e dados/empresas/<RAIZ>.json (histórico de cada empresa).

Uso: python robo/acoes.py
"""
import base64
import io
import json
import os
import re
import sys
import time
import zipfile
from datetime import date, datetime, timedelta

from comum import BRASILIA, DADOS, RAIZ, Yahoo, agora, baixar, ler, log, num, salvar

B3 = "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/"
CVM = "https://dados.cvm.gov.br/dados/CIA_ABERTA/"
CACHE = "cache_acoes.json"
DIAS_SEM_NEGOCIO = 30
ANOS_HISTORICO = 10
SUFIXOS = ("3", "4", "5", "6", "7", "8", "11")
HOJE = datetime.now(BRASILIA).date()

CHAVES = ["t", "n", "s", "ss", "sg", "price", "dy", "p_l", "p_vp", "p_ebit", "p_ativo", "ev_ebit",
          "margembruta", "margemebit", "margemliquida", "p_sr", "p_capitalgiro", "p_ativocirculante",
          "giroativos", "roe", "roa", "roic", "dividaliquidapatrimonioliquido", "dividaliquidaebit",
          "pl_ativo", "passivo_ativo", "liquidezcorrente", "peg_ratio", "receitas_cagr5", "lucros_cagr5",
          "liquidezmediadiaria", "vpa", "lpa", "valormercado",
          # além do que havia antes
          "ev_ebitda", "margemebitda", "dividaliquidaebitda", "payout", "p_fcl", "var12", "raiz"]


# ---------------------------------------------------------------- utilidades
def d(s):
    return date.fromisoformat(s[:10]) if s else None


def br(s):
    """'21/08/2026' -> date."""
    try:
        dd, mm, aa = s.strip().split("/")
        return date(int(aa), int(mm), int(dd))
    except Exception:
        return None


def menos_um_ano(x):
    try:
        return x.replace(year=x.year - 1)
    except ValueError:  # 29/02
        return x.replace(year=x.year - 1, day=28)


def inteiro(s):
    try:
        return int(str(s).replace(".", "").replace(",", "").strip() or 0)
    except ValueError:
        return 0


def div(a, b, casas=4, fator=1):
    if a is None or b is None or b == 0:
        return None
    return round(a / b * fator, casas)


def soma(*v):
    v = [x for x in v if x is not None]
    return sum(v) if v else None


ABREV = {"Máq", "Equip", "Constr", "Mat", "Serv", "Méd", "Hospit", "Prod", "Soc", "Fab", "Com", "Ind", "Part",
         "Adm", "Emp", "Arrend", "Veíc", "Fin", "Rec"}


def setor_b3(texto):
    """A B3 troca vírgulas por pontos: 'Petróleo. Gás e Biocombustíveis' -> 'Petróleo, Gás e Biocombustíveis'."""
    if not texto:
        return ["", "", ""]
    partes = []
    for p in texto.split("/"):
        p = p.strip().replace("..", "., ").replace(" . ", ", ")
        p = re.sub(r"(\w+)\.\s+", lambda m: m.group(0) if m.group(1) in ABREV else m.group(1) + ", ", p)
        partes.append(p)
    return (partes + ["", "", ""])[:3]


# ---------------------------------------------------------------- B3
def b3(metodo, params, tentativas=2):
    q = base64.b64encode(json.dumps(params, separators=(",", ":")).encode()).decode()
    return json.loads(baixar(B3 + metodo + "/" + q, timeout=40, tentativas=tentativas))


def b3_empresas():
    out, pagina = [], 1
    while True:
        r = b3("GetInitialCompanies", {"language": "pt-br", "pageNumber": pagina, "pageSize": 120})
        out += r.get("results") or []
        if pagina >= (r.get("page") or {}).get("totalPages", 1):
            break
        pagina += 1
        time.sleep(0.2)
    return [e for e in out if str(e.get("type")) == "1"]


def paralelo(func, itens, nome, workers=6):
    """Roda func em paralelo (B3 responde devagar a uma chamada por vez); devolve quantas deram certo."""
    from concurrent.futures import ThreadPoolExecutor
    ok = erros = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for n, res in enumerate(ex.map(func, itens), 1):
            ok, erros = (ok + 1, erros) if res else (ok, erros + 1)
            if n % 150 == 0:
                log(f"  B3 {nome}: {n} de {len(itens)}")
    log(f"B3 {nome}: {ok} atualizadas, {erros} falhas")
    return ok


def atualizar_b3(cache):
    """Lista e detalhe (setor, códigos) das empresas; o detalhe é renovado a cada 7 dias."""
    emp = b3_empresas()
    log(f"B3: {len(emp)} empresas com ações listadas")
    guard = cache.setdefault("b3", {})
    agora_ts = time.time()
    for e in emp:
        c = guard.setdefault(e["issuingCompany"], {})
        c["lista"] = {k: e.get(k) for k in ("codeCVM", "companyName", "tradingName", "cnpj", "market", "segment")}

    def detalhe(e):
        c = guard[e["issuingCompany"]]
        if agora_ts - c.get("ts_det", 0) <= 7 * 86400:
            return True
        try:
            det = b3("GetDetail", {"codeCVM": e["codeCVM"], "language": "pt-br"})
            c["det"] = {k: det.get(k) for k in ("industryClassification", "activity", "website", "otherCodes",
                                                 "market", "companyName", "tradingName", "dateQuotation")}
            c["ts_det"] = agora_ts
            return True
        except Exception:
            return False
    paralelo(detalhe, emp, "detalhes")
    vivos = {e["issuingCompany"] for e in emp}
    for raiz in list(guard):
        if raiz not in vivos:
            del guard[raiz]


def atualizar_proventos(guard, raizes):
    """Quantidade de ações e proventos dos últimos 12 meses (a cada execução, só das empresas negociadas)."""
    agora_ts = time.time()

    def complemento(raiz):
        c = guard[raiz]
        if agora_ts - c.get("ts_comp", 0) <= 20 * 3600:
            return True
        try:
            comp = b3("GetListedSupplementCompany", {"issuingCompany": raiz, "language": "pt-br"})
            comp = comp[0] if isinstance(comp, list) and comp else (comp or {})
            limite = HOJE - timedelta(days=400)
            c["comp"] = {
                "on": inteiro(comp.get("numberCommonShares")), "pn": inteiro(comp.get("numberPreferredShares")),
                "total": inteiro(comp.get("totalNumberShares")), "segmento": comp.get("segment"),
                "proventos": [p for p in (comp.get("cashDividends") or [])
                              if (br(p.get("lastDatePrior") or "") or HOJE) >= limite],
                "eventos": [p for p in (comp.get("stockDividends") or [])
                            if (br(p.get("lastDatePrior") or "") or HOJE) >= HOJE - timedelta(days=3650)],
            }
            c["ts_comp"] = agora_ts
            return True
        except Exception:
            return False
    paralelo(complemento, sorted(raizes), "proventos")


# ---------------------------------------------------------------- CVM
def zip_cvm(doc, ano):
    try:
        return zipfile.ZipFile(io.BytesIO(baixar(f"{CVM}DOC/{doc}/DADOS/{doc.lower()}_cia_aberta_{ano}.zip", timeout=240)))
    except Exception as ex:
        log(f"  CVM {doc} {ano}: {ex}")
        return None


def linhas_csv(z, nome):
    if nome not in z.namelist():
        return
    with z.open(nome) as fh:
        cab = None
        for bruta in io.TextIOWrapper(fh, encoding="latin-1", newline=""):
            campos = bruta.rstrip("\r\n").split(";")
            if cab is None:
                cab = {c: i for i, c in enumerate(campos)}
                yield cab
                continue
            yield campos


def conta_util(tipo, cd):
    nivel = cd.count(".") + 1
    if tipo.startswith("DFC"):
        return nivel <= 3 or cd.startswith("6.01.01.")
    return nivel <= 3


def ler_zip(z, prefixo, ano, alvo):
    """{(cvm, dt_refer): {"escopo", "linhas": [(tipo, ordem, ini, fim, cd, ds, valor)]}} com a última versão."""
    arq = {}
    for tipo in ("BPA", "BPP", "DRE", "DFC_MI", "DFC_MD"):
        for escopo in ("con", "ind"):
            it = linhas_csv(z, f"{prefixo}_{tipo}_{escopo}_{ano}.csv")
            cab = next(it, None)
            if cab is None:
                continue
            i = cab
            tem_ini = "DT_INI_EXERC" in i
            for c in it:
                try:
                    cvm = int(c[i["CD_CVM"]])
                except (ValueError, IndexError):
                    continue
                if cvm not in alvo:
                    continue
                cd = c[i["CD_CONTA"]]
                if not conta_util(tipo, cd):
                    continue
                chave = (cvm, c[i["DT_REFER"]], escopo)
                v = int(c[i["VERSAO"]] or 0)
                f = arq.get(chave)
                if f is None or v > f["v"]:
                    f = arq[chave] = {"v": v, "linhas": []}
                elif v < f["v"]:
                    continue
                esc = 1000 if c[i["ESCALA_MOEDA"]] == "MIL" else 1
                try:
                    valor = float(c[i["VL_CONTA"]]) * esc
                except ValueError:
                    continue
                f["linhas"].append((tipo[:3], c[i["ORDEM_EXERC"]], c[i["DT_INI_EXERC"]] if tem_ini else "",
                                    c[i["DT_FIM_EXERC"]], cd, c[i["DS_CONTA"]], valor))
    # consolidado quando existir; senão individual
    out = {}
    for (cvm, ref, escopo), f in arq.items():
        if escopo == "ind" and (cvm, ref, "con") in arq and len(arq[(cvm, ref, "con")]["linhas"]) > 20:
            continue
        out[(cvm, ref)] = {"escopo": escopo, "linhas": f["linhas"]}
    return out


RE_DA = re.compile(r"deprecia|amortiza|exaust", re.I)
RE_DA_NAO = re.compile(r"juros|encargo|custo de (transa|capta)|ágio|deságio|debênture|empréstimo|financiamento", re.I)
RE_CAPEX = re.compile(r"imobilizado|intang|ativo fixo|investimentos? em (ativo|bens)|capex|propriedade", re.I)
RE_CAPEX_NAO = re.compile(r"venda|alienação|baixa|recebimento|resgate|aplica", re.I)
RE_DIV = re.compile(r"dividend|juros sobre (o )?capital|jcp", re.I)


def extrair(linhas):
    """Métricas de uma demonstração: fluxos por (início, fim) e saldos por data."""
    grupos = {}
    for tipo, ordem, ini, fim, cd, ds, valor in linhas:
        grupos.setdefault((tipo, ordem, ini, fim), {})[cd] = (ds, valor)
    fluxos, saldos = {}, {}
    for (tipo, ordem, ini, fim), v in grupos.items():
        g = lambda cd, comeca="": v[cd][1] if cd in v and v[cd][0].lower().startswith(comeca.lower()) else None
        if tipo == "BPA":
            s = saldos.setdefault(fim, {"_ordem": ordem})
            s["ativo"] = g("1")
            s["ac"] = g("1.01", "Ativo Circulante")
            s["caixa"] = soma(g("1.01.01", "Caixa"), g("1.01.02", "Aplica")) if s["ac"] is not None else g("1.01", "Caixa")
            s["estoques"] = g("1.01.04", "Estoque")
        elif tipo == "BPP":
            s = saldos.setdefault(fim, {"_ordem": ordem})
            s["pc"] = g("2.01", "Passivo Circulante")
            s["pnc"] = g("2.02", "Passivo Não Circulante")
            if s["pc"] is not None:
                s["divida"] = soma(g("2.01.04", "Empréstimos"), g("2.02.01", "Empréstimos")) or 0.0
            pl_cd = next((cd for cd, (ds, _) in v.items() if cd.count(".") == 1 and ds.startswith("Patrimônio Líquido")), None)
            if pl_cd:
                s["pl"] = v[pl_cd][1]
                nc = sum(val for cd, (ds, val) in v.items() if cd.startswith(pl_cd + ".") and "Não Controladores" in ds)
                s["pl_contr"] = s["pl"] - nc
        elif tipo == "DRE":
            f = fluxos.setdefault((ini, fim), {"_ordem": ordem})
            f["receita"] = g("3.01")
            f["custo"] = g("3.02", "Custo")
            f["lb"] = g("3.03", "Resultado Bruto")
            f["desp"] = g("3.04", "Despesas")
            for cd, (ds, val) in v.items():
                if cd.count(".") != 1:
                    continue
                if ds.startswith("Resultado Antes do Resultado Financeiro"):
                    f["ebit"] = val
                elif ds.startswith("Resultado Financeiro"):
                    f["fin"] = val
                elif ds.startswith("Imposto de Renda"):
                    f["ir"] = val
                elif re.match(r"(Lucro/Prejuízo|Lucro ou Prejuízo)( Líquido)?( Consolidado)? do (Período|Exercício)\s*$", ds):
                    f["lucro"] = val
                    contr = [vv for c2, (d2, vv) in v.items() if c2.startswith(cd + ".") and "Controladora" in d2]
                    f["lucro_contr"] = contr[0] if contr else val
        elif tipo == "DFC":
            f = fluxos.setdefault((ini, fim), {"_ordem": ordem})
            f["fco"] = g("6.01", "Caixa Líquido")
            f["fci"] = g("6.02", "Caixa Líquido")
            f["fcf"] = g("6.03", "Caixa Líquido")
            f["da"] = sum(val for cd, (ds, val) in v.items()
                          if cd.startswith("6.01.01.") and RE_DA.search(ds) and not RE_DA_NAO.search(ds)) or None
            f["capex"] = sum(val for cd, (ds, val) in v.items() if cd.startswith("6.02.") and cd.count(".") == 2
                             and val < 0 and RE_CAPEX.search(ds) and not RE_CAPEX_NAO.search(ds)) or 0.0
            f["div_pagos"] = -sum(val for cd, (ds, val) in v.items() if cd.startswith("6.03.") and cd.count(".") == 2
                                  and val < 0 and RE_DIV.search(ds)) or 0.0
    return fluxos, saldos


def juntar(destino, novo, ref):
    """Guarda cada período uma vez; vale o dado em que o período é o 'ÚLTIMO' e, depois, o mais recente."""
    for per, campos in novo.items():
        prio = (campos.get("_ordem") == "ÚLTIMO", ref)
        atual = destino.get(per)
        if atual is None or prio > atual["_prio"]:
            destino[per] = {**{k: v for k, v in campos.items() if not k.startswith("_")}, "_prio": prio}
        else:  # completa campos ausentes
            for k, v in campos.items():
                if not k.startswith("_") and atual.get(k) is None and v is not None:
                    atual[k] = v


def carregar_cvm(alvo):
    ano = HOJE.year
    empresas = {}
    capital = {}
    zips = [("DFP", a) for a in range(ano - 1, ano - ANOS_HISTORICO - 1, -2)] + [("ITR", ano), ("ITR", ano - 1)]
    if HOJE.month <= 4:  # DFP do ano anterior pode ainda não ter saído
        zips.append(("DFP", ano - 2))
    for doc, a in zips:
        z = zip_cvm(doc, a)
        if z is None:
            continue
        pref = f"{doc.lower()}_cia_aberta"
        filings = ler_zip(z, pref, a, alvo)
        for (cvm, ref), f in filings.items():
            fluxos, saldos = extrair(f["linhas"])
            e = empresas.setdefault(cvm, {"fluxos": {}, "saldos": {}, "escopo": f["escopo"]})
            juntar(e["fluxos"], fluxos, ref)
            juntar(e["saldos"], saldos, ref)
        it = linhas_csv(z, f"{pref}_composicao_capital_{a}.csv")
        cab = next(it, None)
        if cab:
            for c in it:
                cnpj = re.sub(r"\D", "", c[cab["CNPJ_CIA"]])
                ref = c[cab["DT_REFER"]]
                if ref >= capital.get(cnpj, {}).get("ref", ""):
                    capital[cnpj] = {"ref": ref, "total": inteiro(c[cab["QT_ACAO_TOTAL_CAP_INTEGR"]]),
                                     "on": inteiro(c[cab["QT_ACAO_ORDIN_CAP_INTEGR"]]),
                                     "pn": inteiro(c[cab["QT_ACAO_PREF_CAP_INTEGR"]]),
                                     "tesouraria": inteiro(c[cab["QT_ACAO_TOTAL_TESOURO"]])}
        log(f"  CVM {doc} {a}: {len(filings)} demonstrações")
        del z, filings
    return empresas, capital


CAMPOS_FLUXO = ("receita", "custo", "lb", "desp", "ebit", "fin", "ir", "lucro", "lucro_contr", "da",
                "fco", "fci", "fcf", "capex", "div_pagos")
CAMPOS_SALDO = ("ativo", "ac", "caixa", "estoques", "pc", "pnc", "divida", "pl", "pl_contr")


def resumo_empresa(e):
    """Anual (até 10 anos), 12 meses, trimestres e balanço mais recente."""
    fl = {(d(i), d(f)): v for (i, f), v in e["fluxos"].items() if i and f}
    anuais = {k: v for k, v in fl.items() if 350 <= (k[1] - k[0]).days <= 380}
    if not anuais:
        return None
    ult = max(anuais)
    a = anuais[ult]
    # 12 meses: último anual + acumulado do ano corrente - mesmo período do ano anterior
    ytd = [k for k in fl if k[0] == ult[1] + timedelta(days=1) and k[1] > ult[1]]
    ttm, ref = dict(a), ult[1]
    if ytd:
        q = max(ytd)
        qp = (ult[0], menos_um_ano(q[1]))
        if qp in fl:
            ttm, ref = {}, q[1]
            for c in CAMPOS_FLUXO:
                x, y, z = a.get(c), fl[q].get(c), fl[qp].get(c)
                ttm[c] = x + y - z if None not in (x, y, z) else (x if c in ("capex", "div_pagos", "da") and None in (y, z) else None)
    # trimestres (3 meses) e 4º trimestre = ano - 9 meses
    trim = {k: v for k, v in fl.items() if 80 <= (k[1] - k[0]).days <= 100}
    for (ini, fim), v in anuais.items():
        nove = (ini, fim - timedelta(days=92))
        cand = [k for k in fl if k[0] == ini and 260 <= (k[1] - k[0]).days <= 280]
        if cand:
            n9 = fl[max(cand)]
            q4 = (max(cand)[1] + timedelta(days=1), fim)
            if q4 not in trim:
                trim[q4] = {c: (v.get(c) - n9.get(c)) if v.get(c) is not None and n9.get(c) is not None else None
                            for c in ("receita", "lb", "ebit", "lucro", "lucro_contr")}
    sal = {d(k): v for k, v in e["saldos"].items() if k}
    bal_ult = sal[max(sal)] if sal else {}
    return {"anuais": anuais, "ttm": ttm, "ref": ref, "trim": trim, "saldos": sal, "balanco": bal_ult,
            "data_balanco": max(sal) if sal else None}


def ano_de(fim):
    return fim.year if fim.month >= 6 else fim.year - 1


def cagr(por_ano, campo, anos=5):
    """Crescimento médio anual entre o último ano completo e cinco anos antes."""
    if not por_ano:
        return None
    ult = max(por_ano)
    ini, fim = (por_ano.get(ult - anos) or {}).get(campo), por_ano[ult].get(campo)
    if ini is None or fim is None or ini <= 0 or fim <= 0:
        return None
    return round(((fim / ini) ** (1 / anos) - 1) * 100, 2)


# ---------------------------------------------------------------- reserva sem B3 (cadastro e FCA da CVM)
def lista_cvm():
    cad = {}
    txt = baixar(CVM + "CAD/DADOS/cad_cia_aberta.csv", timeout=120).decode("latin-1").splitlines()
    cab = {c: i for i, c in enumerate(txt[0].split(";"))}
    for l in txt[1:]:
        c = l.split(";")
        if len(c) < len(cab) or c[cab["SIT"]] != "ATIVO":
            continue
        cad[re.sub(r"\D", "", c[cab["CNPJ_CIA"]])] = {"cvm": c[cab["CD_CVM"]], "nome": c[cab["DENOM_SOCIAL"]],
                                                       "setor": c[cab["SETOR_ATIV"]]}
    out = {}
    z = zip_cvm("FCA", HOJE.year) or zip_cvm("FCA", HOJE.year - 1)
    nome = next(n for n in z.namelist() if "valor_mobiliario" in n)
    it = linhas_csv(z, nome)
    cab = next(it)
    for c in it:
        t = c[cab["Codigo_Negociacao"]].strip().upper()
        cnpj = re.sub(r"\D", "", c[cab["CNPJ_Companhia"]])
        if (c[cab["Mercado"]] != "Bolsa" or c[cab["Data_Fim_Negociacao"]] or cnpj not in cad
                or not re.fullmatch(r"[A-Z]{4}\d{1,2}", t) or t[4:] not in SUFIXOS):
            continue
        info = cad[cnpj]
        e = out.setdefault(t[:4], {"lista": {"codeCVM": info["cvm"], "companyName": info["nome"], "tradingName": info["nome"],
                                             "cnpj": cnpj, "market": "", "segment": c[cab["Segmento"]]},
                                   "det": {"industryClassification": info["setor"], "otherCodes": []}, "comp": {}})
        e["det"]["otherCodes"].append({"code": t, "isin": ""})
    return out


# ---------------------------------------------------------------- preços
def historico_mensal(y, ticker):
    r = y.json(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.SA?range={ANOS_HISTORICO}y&interval=1mo",
               tentativas=2)
    res = r["chart"]["result"][0]
    ts = res.get("timestamp") or []
    fech = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    out = []
    for t, c in zip(ts, fech):
        if c:
            out.append([datetime.fromtimestamp(t, BRASILIA).strftime("%Y-%m"), round(c, 2)])
    return out


# ---------------------------------------------------------------- principal
def main():
    cache = ler(CACHE, {}) or {}
    fonte_b3 = True
    try:
        atualizar_b3(cache)
        empresas_b3 = cache["b3"]
    except Exception as ex:
        log(f"B3 indisponível ({ex})")
        fonte_b3 = False
        empresas_b3 = cache.get("b3") or {}
        if len(empresas_b3) < 200:
            log("usando o cadastro e o FCA da CVM para a lista de ações")
            empresas_b3 = lista_cvm()
    salvar(CACHE, cache)

    # códigos de negociação de ações por empresa
    tickers, isin_ticker = {}, {}
    for raiz, e in empresas_b3.items():
        for oc in (e.get("det") or {}).get("otherCodes") or []:
            t = (oc.get("code") or "").upper()
            if re.fullmatch(r"[A-Z]{4}\d{1,2}", t) and t[4:] in SUFIXOS:
                tickers.setdefault(raiz, []).append(t)
                if oc.get("isin"):
                    isin_ticker[oc["isin"]] = t
    todos = sorted({t for ts in tickers.values() for t in ts})
    log(f"{len(todos)} códigos de ações de {len(tickers)} empresas")

    y = Yahoo()
    cot = y.cotacoes([t + ".SA" for t in todos])
    limite = time.time() - DIAS_SEM_NEGOCIO * 86400
    precos = {}
    for t in todos:
        q = cot.get(t + ".SA")
        if q and (q.get("regularMarketPrice") or 0) > 0 and (q.get("regularMarketTime") or 0) >= limite:
            precos[t] = q
    log(f"Yahoo: {len(cot)} cotações, {len(precos)} com negócio nos últimos {DIAS_SEM_NEGOCIO} dias")
    negociadas = [raiz for raiz, ts in tickers.items() if any(t in precos for t in ts)]
    if fonte_b3:
        try:
            atualizar_proventos(cache["b3"], negociadas)
        except Exception as ex:
            log(f"B3 proventos: {ex}")
        salvar(CACHE, cache)

    alvo = {int(e["lista"]["codeCVM"]) for raiz, e in empresas_b3.items()
            if any(t in precos for t in tickers.get(raiz, [])) and str(e["lista"].get("codeCVM", "")).isdigit()}
    cvm, capital = carregar_cvm(alvo)
    log(f"CVM: demonstrações de {len(cvm)} de {len(alvo)} empresas")

    os.makedirs(os.path.join(DADOS, "empresas"), exist_ok=True)
    linhas = []
    cache_precos = cache.setdefault("precos", {})
    agora_ts = time.time()
    sem_balanco = 0
    for raiz, e in sorted(empresas_b3.items()):
        ts = [t for t in tickers.get(raiz, []) if t in precos]
        if not ts:
            continue
        lista, det, comp = e.get("lista") or {}, e.get("det") or {}, e.get("comp") or {}
        s, ss, sg = setor_b3(det.get("industryClassification"))
        nome = (lista.get("companyName") or det.get("companyName") or raiz).strip()
        codigo = int(lista["codeCVM"]) if str(lista.get("codeCVM", "")).isdigit() else None
        r = resumo_empresa(cvm[codigo]) if codigo in cvm else None
        if r is None:
            sem_balanco += 1

        # ações: B3; tesouraria pelo ITR/DFP
        cap = capital.get(re.sub(r"\D", "", lista.get("cnpj") or ""), {})
        on, pn = comp.get("on") or cap.get("on") or 0, comp.get("pn") or cap.get("pn") or 0
        total = (on + pn) or comp.get("total") or cap.get("total") or 0
        tes = cap.get("tesouraria") or 0
        acoes = total - tes if 0 < tes < total * 0.5 else total

        preco = {t: float(precos[t]["regularMarketPrice"]) for t in ts}
        liq = {t: (precos[t].get("averageDailyVolume3Month") or precos[t].get("regularMarketVolume") or 0) * preco[t] for t in ts}
        p_on = preco.get(raiz + "3")
        pn_ts = sorted([t for t in ts if t[4:] in ("4", "5", "6", "7", "8")], key=lambda t: -liq[t])
        p_pn = preco[pn_ts[0]] if pn_ts else None
        ref_preco = p_on or p_pn
        if ref_preco and total:
            vm = on * (p_on or p_pn) + pn * (p_pn or p_on)
            vm *= (acoes / total) if total else 1
        else:  # só a unit negocia
            u = next((t for t in ts if t.endswith("11")), None)
            vm = precos[u].get("marketCap") if u else None

        # proventos dos últimos 12 meses por código (B3)
        prov12 = {}
        for p in comp.get("proventos") or []:
            dc = br(p.get("lastDatePrior") or "")
            t = isin_ticker.get(p.get("isinCode") or p.get("assetIssued"))
            if t and dc and HOJE - timedelta(days=365) < dc <= HOJE:
                prov12[t] = prov12.get(t, 0) + (num(p.get("rate"), 8) or 0)
        prov_total = (prov12.get(raiz + "3", 0) * on + (prov12.get(pn_ts[0], 0) if pn_ts else 0) * pn) if comp else None

        ttm = (r or {}).get("ttm") or {}
        bal = (r or {}).get("balanco") or {}
        lucro, lucro_c = ttm.get("lucro"), ttm.get("lucro_contr")
        receita, ebit, da = ttm.get("receita"), ttm.get("ebit"), ttm.get("da")
        ebitda = ebit + da if ebit is not None and da is not None else None
        pl, pl_c, ativo = bal.get("pl"), bal.get("pl_contr"), bal.get("ativo")
        ac, pc, pnc = bal.get("ac"), bal.get("pc"), bal.get("pnc")
        dl = (bal.get("divida") or 0) - (bal.get("caixa") or 0) if pc is not None else None
        fcl = (ttm.get("fco") + ttm.get("capex")) if ttm.get("fco") is not None and ttm.get("capex") is not None else None
        anos = sorted((r or {}).get("anuais", {}))
        por_ano = {ano_de(k[1]): r["anuais"][k] for k in anos} if r else {}
        cagr_r = cagr(por_ano, "receita")
        cagr_l = cagr(por_ano, "lucro_contr")
        lpa = div(lucro_c, acoes, 4) if acoes else None
        vpa = div(pl_c, acoes, 4) if acoes else None
        payout = div(prov_total, lucro_c, 2, 100) if prov_total is not None and lucro_c and lucro_c > 0 else None

        for t in ts:
            p = preco[t]
            mult = 1
            if t.endswith("11") and ref_preco:
                m = round(p / ref_preco)
                mult = m if 1 <= m <= 10 and abs(p / (m * ref_preco) - 1) < 0.2 else 1
            vm_t = p / mult * acoes if acoes else None  # valor de mercado implícito no preço deste código
            ev_t = vm_t + dl if vm_t is not None and dl is not None else None
            linhas.append({
                "t": t, "n": nome, "s": s, "ss": ss, "sg": sg, "raiz": raiz,
                "price": round(p, 4),
                "dy": (round(prov12.get(t, 0) / p * 100, 4) if comp.get("proventos") is not None
                       else num((precos[t].get("trailingAnnualDividendYield") or 0) * 100, 4)),
                "lpa": round(lpa * mult, 4) if lpa is not None else None,
                "vpa": round(vpa * mult, 4) if vpa is not None else None,
                "p_l": div(p, lpa * mult) if lpa else None,
                "p_vp": div(p, vpa * mult) if vpa else None,
                "p_ebit": div(vm_t, ebit), "p_sr": div(vm_t, receita), "p_ativo": div(vm_t, ativo),
                "p_capitalgiro": div(vm_t, ac - pc) if ac is not None and pc is not None else None,
                "p_ativocirculante": div(vm_t, ac - pc - (pnc or 0)) if ac is not None and pc is not None else None,
                "p_fcl": div(vm_t, fcl) if fcl and fcl > 0 else None,
                "ev_ebit": div(ev_t, ebit), "ev_ebitda": div(ev_t, ebitda),
                "margembruta": div(ttm.get("lb"), receita, 2, 100), "margemebit": div(ebit, receita, 2, 100),
                "margemebitda": div(ebitda, receita, 2, 100), "margemliquida": div(lucro, receita, 2, 100),
                "giroativos": div(receita, ativo, 2), "roe": div(lucro_c, pl_c, 2, 100) if pl_c and pl_c > 0 else None,
                "roa": div(lucro, ativo, 2, 100),
                "roic": div(ebit * 0.66, pl + dl, 2, 100) if ebit is not None and pl is not None and dl is not None and pl + dl > 0 else None,
                "dividaliquidapatrimonioliquido": div(dl, pl, 2) if dl is not None and pl and pl > 0 else None,
                "dividaliquidaebit": div(dl, ebit, 2) if dl is not None and ebit and ebit > 0 else None,
                "dividaliquidaebitda": div(dl, ebitda, 2) if dl is not None and ebitda and ebitda > 0 else None,
                "pl_ativo": div(pl, ativo, 2), "passivo_ativo": div(ativo - pl, ativo, 2) if ativo and pl is not None else None,
                "liquidezcorrente": div(ac, pc, 2), "payout": payout,
                "receitas_cagr5": cagr_r, "lucros_cagr5": cagr_l,
                "peg_ratio": div(div(p, lpa * mult), cagr_l, 4) if lpa and lpa > 0 and cagr_l and cagr_l > 0 else None,
                "liquidezmediadiaria": round(liq[t], 2), "valormercado": round(vm, 2) if vm else None,
                "var12": num(precos[t].get("fiftyTwoWeekChangePercent"), 2),
            })

        # arquivo da empresa: histórico para gráficos e tabelas no app
        principal = max(ts, key=lambda t: liq[t])
        cp = cache_precos.get(principal) or {}
        if agora_ts - cp.get("ts", 0) > 6 * 86400:
            try:
                cp = cache_precos[principal] = {"ts": agora_ts, "m": historico_mensal(y, principal)}
                time.sleep(0.2)
            except Exception as ex:
                log(f"  histórico de {principal}: {ex}")
        anual = {}
        if r:
            for k in anos[-ANOS_HISTORICO:]:
                ano_ref = ano_de(k[1])
                v, sd = r["anuais"][k], r["saldos"].get(k[1], {})
                da_a = v.get("da")
                anual[str(ano_ref)] = {
                    **{c: v.get(c) for c in CAMPOS_FLUXO},
                    "ebitda": v["ebit"] + da_a if v.get("ebit") is not None and da_a is not None else None,
                    **{c: sd.get(c) for c in CAMPOS_SALDO},
                }
        trimestres = []
        if r:
            for k in sorted(r["trim"])[-12:]:
                v = r["trim"][k]
                trimestres.append([k[1].isoformat(), v.get("receita"), v.get("lb"), v.get("ebit"), v.get("lucro_contr")])
        proventos = []
        for p in comp.get("proventos") or []:
            t = isin_ticker.get(p.get("isinCode") or p.get("assetIssued"))
            if t:
                proventos.append([t, (p.get("label") or "").title(), p.get("lastDatePrior"), p.get("paymentDate"),
                                  num(p.get("rate"), 8), p.get("relatedTo")])
        empresa = {
            "atualizado": agora(), "raiz": raiz, "nome": nome, "pregao": lista.get("tradingName"),
            "cnpj": lista.get("cnpj"), "cvm": codigo, "setor": [s, ss, sg], "listagem": comp.get("segmento") or lista.get("segment"),
            "site": det.get("website"), "atividade": det.get("activity"), "tickers": ts,
            "acoes": {"on": on, "pn": pn, "tesouraria": tes, "total": total},
            "escopo": cvm.get(codigo, {}).get("escopo") if codigo else None,
            "balanco_em": r["data_balanco"].isoformat() if r and r.get("data_balanco") else None,
            "ttm_ate": r["ref"].isoformat() if r else None,
            "ttm": {c: ttm.get(c) for c in CAMPOS_FLUXO} if r else None,
            "balanco": {c: bal.get(c) for c in CAMPOS_SALDO} if r else None,
            "anual": anual, "trimestres": trimestres, "proventos": proventos,
            "eventos": [[(ev.get("label") or "").title(), ev.get("lastDatePrior"), num(ev.get("factor"), 6)]
                        for ev in comp.get("eventos") or []],
            "precos": {"codigo": principal, "mensal": cp.get("m") or []},
        }
        with open(os.path.join(DADOS, "empresas", raiz + ".json"), "w", encoding="utf-8") as fh:
            json.dump(empresa, fh, ensure_ascii=False, separators=(",", ":"))

    salvar(CACHE, cache)
    codigos = {l["t"] for l in linhas}
    minimo = int(os.environ.get("MINIMO_ACOES", "250"))
    faltam = ({"PETR4", "VALE3", "ITUB4"} - codigos) if minimo >= 250 else set()
    if len(linhas) < minimo or faltam:
        raise RuntimeError(f"resultado incompleto: {len(linhas)} códigos, faltando {sorted(faltam)}")
    linhas.sort(key=lambda l: l["t"])
    dados = {"atualizado": agora(),
             "fonte": "demonstrações da CVM, cadastro e proventos da B3 e cotações do Yahoo Finance",
             "k": CHAVES, "d": [[l.get(c) for c in CHAVES] for l in linhas]}
    tmp = os.path.join(RAIZ, "acoes.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dados, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, os.path.join(RAIZ, "acoes.json"))
    log(f"OK: {len(linhas)} códigos de {len({l['raiz'] for l in linhas})} empresas; {sem_balanco} empresas sem demonstração; "
        f"B3 {'ok' if fonte_b3 else 'indisponível'}")
    for t in ("PETR4", "VALE3", "ITUB4", "WEGE3", "BBAS3", "TAEE11"):
        l = next((x for x in linhas if x["t"] == t), None)
        if l:
            log("  " + t + ": " + ", ".join(f"{k}={l.get(k)}" for k in ("price", "dy", "p_l", "p_vp", "roe", "margemliquida",
                                                                        "dividaliquidaebitda", "ev_ebitda", "valormercado")))


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        import traceback
        traceback.print_exc()
        log(f"Ações falhou: {ex}")
        sys.exit(1)
