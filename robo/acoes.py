"""Ações da B3 calculadas a partir de fontes oficiais.

- B3 (API pública de empresas listadas): códigos de negociação, setor, quantidade de ações,
  proventos dos últimos 12 meses e histórico de proventos.
- CVM (dados abertos): demonstrações anuais (DFP) e trimestrais (ITR), formulário de referência
  (acionistas e free float) e comunicados (fatos relevantes, releases) de todas as companhias,
  inclusive emissores estrangeiros com BDR na B3 que entregam balanço à CVM (Inter, JBS, Aura).
- Yahoo Finance: cotação, volume médio e histórico mensal de preços; Ibovespa.
- Banco Central: CDI e IPCA mensais, para comparar a rentabilidade.

Todos os indicadores são calculados aqui, com os 12 últimos meses de resultados e ano a ano.
Gera acoes.json (lista do app), dados/empresas/<RAIZ>.json (histórico de cada empresa)
e dados/referencias.json (Ibovespa, CDI e IPCA).

Uso: python robo/acoes.py
"""
import base64
import io
import json
import math
import os
import re
import sys
import time
import unicodedata
import zipfile
from datetime import date, datetime, timedelta

from comum import BRASILIA, DADOS, RAIZ, Yahoo, agora, baixar, ler, log, num, salvar

B3 = "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/"
CVM = "https://dados.cvm.gov.br/dados/CIA_ABERTA/"
CACHE = "cache_acoes.json"
BCB = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{}/dados?formato=json&dataInicial={}&dataFinal={}"
IPEA = "https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='{}')"
IPEA_SERIE = {"cdi": "BM12_TJCDI12", "ipca": "PRECOS12_IPCAG12"}  # % ao mês
DIAS_SEM_NEGOCIO = 30
ANOS_HISTORICO = 10
SUFIXOS = ("3", "4", "5", "6", "7", "8", "11")
SUFIXOS_BDR = ("31", "32", "33", "34", "35", "39", "11")
VERSAO_PRECOS = 2
MAX_HISTORICOS = int(os.environ.get("MAX_HISTORICOS", "450"))
HOJE = datetime.now(BRASILIA).date()
# tag along mínimo por segmento de listagem (Lei 6.404, art. 254-A, e regulamentos da B3)
TAG_ALONG = {"NM": 100, "N2": 100, "MA": 100, "M2": 100}
SETOR_CVM = {"Bancos": "Financeiro / Intermediários Financeiros / Bancos",
             "Alimentos": "Consumo não Cíclico / Alimentos Processados / Alimentos Diversos",
             "Extração Mineral": "Materiais Básicos / Mineração / Minerais Metálicos"}

CHAVES = ["t", "n", "s", "ss", "sg", "price", "dy", "p_l", "p_vp", "p_ebit", "p_ativo", "ev_ebit",
          "margembruta", "margemebit", "margemliquida", "p_sr", "p_capitalgiro", "p_ativocirculante",
          "giroativos", "roe", "roa", "roic", "dividaliquidapatrimonioliquido", "dividaliquidaebit",
          "pl_ativo", "passivo_ativo", "liquidezcorrente", "peg_ratio", "receitas_cagr5", "lucros_cagr5",
          "liquidezmediadiaria", "vpa", "lpa", "valormercado",
          "ev_ebitda", "margemebitda", "dividaliquidaebitda", "payout", "p_fcl", "var12", "raiz",
          # histórico, mercado e governança
          "p_ebitda", "ev_receita", "p_fco", "liquidezseca", "liquidezimediata", "ebitda_cagr5",
          "dy_media5", "roe_media5", "pl_medio5", "pvp_medio5", "anos_lucro", "anos_div",
          "freefloat", "tagalong", "ret12", "ret60", "bdr",
          # lucro x cotação na mesma janela de cerca de 5 anos
          "lc_lucro", "lc_cot", "lc_desde", "lc_n", "lc_r2", "lc_t0", "lc_t1", "lc_y0", "lc_yc", "lc_yh", "lc_salto", "lc_op"]


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
    # ações e BDRs de emissores estrangeiros registrados na CVM (níveis 2 e 3 entregam DFP/ITR)
    return [e for e in out if str(e.get("type")) == "1"
            or (str(e.get("type")) == "2" and e.get("typeBDR") in ("DR2", "DR3"))]


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
        c["lista"] = {k: e.get(k) for k in ("codeCVM", "companyName", "tradingName", "cnpj", "market", "segment", "typeBDR")}
        c["bdr"] = str(e.get("type")) == "2"

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
        if raiz not in vivos and not guard[raiz].get("fca"):
            del guard[raiz]


def bdrs_fca(guard):
    """BDRs de emissores estrangeiros que entregam balanço à CVM mas não aparecem na lista de empresas
    da B3 (ex.: Inter & Co, INBR32). Vêm do formulário cadastral (FCA) com o código de negociação."""
    z = zip_cvm("FCA", HOJE.year) or zip_cvm("FCA", HOJE.year - 1)
    if z is None:
        return 0
    for raiz in [r for r, c in guard.items() if c.get("fca")]:
        del guard[raiz]
    ja = {str((c.get("lista") or {}).get("codeCVM") or "").lstrip("0") for c in guard.values()}
    ano = next(n for n in z.namelist() if "_geral_" in n)[-8:-4]
    geral = {}
    it = linhas_csv(z, f"fca_cia_aberta_geral_{ano}.csv")
    cab = next(it, None)
    for c in it if cab else []:
        if len(c) < len(cab):
            continue
        geral[re.sub(r"\D", "", c[cab["CNPJ_Companhia"]])] = {
            "cvm": c[cab["Codigo_CVM"]].lstrip("0"), "nome": c[cab["Nome_Empresarial"]], "setor": c[cab["Setor_Atividade"]],
            "atividade": c[cab["Descricao_Atividade"]], "site": c[cab["Pagina_Web"]].strip(), "pais": c[cab["Pais_Origem"]]}
    novos = 0
    it = linhas_csv(z, f"fca_cia_aberta_valor_mobiliario_{ano}.csv")
    cab = next(it, None)
    for c in it if cab else []:
        if len(c) < len(cab):
            continue
        t = c[cab["Codigo_Negociacao"]].strip().upper()
        cnpj = re.sub(r"\D", "", c[cab["CNPJ_Companhia"]])
        g = geral.get(cnpj)
        if (not g or "BDR" not in c[cab["Valor_Mobiliario"]].upper() or c[cab["Mercado"]] != "Bolsa"
                or c[cab["Data_Fim_Negociacao"]] or not re.fullmatch(r"[A-Z]{4}\d{2}", t) or g["cvm"] in ja):
            continue
        raiz = t[:4]
        if raiz in guard:
            continue
        guard[raiz] = {"fca": True, "bdr": True,
                       "lista": {"codeCVM": g["cvm"], "companyName": g["nome"], "tradingName": g["nome"], "cnpj": cnpj,
                                 "market": "", "segment": "", "typeBDR": "CVM"},
                       "det": {"industryClassification": SETOR_CVM.get(g["setor"], f"Outros / {g['setor']} / {g['setor']}"),
                               "activity": g["atividade"], "website": g["site"], "otherCodes": [{"code": t, "isin": ""}]}}
        ja.add(g["cvm"])
        novos += 1
    log(f"FCA: {novos} BDRs de emissores estrangeiros com balanço na CVM")
    return novos


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
                            if (br(p.get("lastDatePrior") or "") or HOJE) >= HOJE - timedelta(days=4400)],
                "nome_b3": (comp.get("tradingName") or "").strip(),
            }
            c["ts_comp"] = agora_ts
            return True
        except Exception:
            return False
    paralelo(complemento, sorted(raizes), "proventos")


def atualizar_historico_proventos(guard, raizes):
    """Proventos em dinheiro dos últimos anos (B3), renovados a cada 6 dias."""
    agora_ts = time.time()
    limite = HOJE.year - ANOS_HISTORICO - 1

    def hist(raiz):
        c = guard[raiz]
        if agora_ts - c.get("ts_hist", 0) <= 6 * 86400:
            return True
        nome = ((c.get("comp") or {}).get("nome_b3") or (c.get("lista") or {}).get("tradingName") or "").strip()
        if not nome:
            return False
        try:
            out, pagina = [], 1
            while pagina <= 6:
                r = b3("GetListedCashDividends", {"language": "pt-br", "pageNumber": pagina, "pageSize": 120,
                                                  "tradingName": nome})
                res = r.get("results") or []
                for p in res:
                    dc = br(p.get("lastDatePriorEx") or "")
                    if dc and dc.year >= limite:
                        lote = num(p.get("quotedPerShares"), 4) or 1
                        out.append([dc.isoformat(), p.get("typeStock") or "", (p.get("corporateAction") or "").strip(),
                                    round((num(p.get("valueCash"), 10) or 0) / lote, 10)])
                ult = br(res[-1].get("lastDatePriorEx") or "") if res else None
                if not res or pagina >= ((r.get("page") or {}).get("totalPages") or 1) or (ult and ult.year < limite):
                    break
                pagina += 1
            c["hist"] = out
            c["ts_hist"] = agora_ts
            return True
        except Exception:
            return False
    paralelo(hist, sorted(raizes), "histórico de proventos")


def fator_eventos(eventos):
    """[(data, multiplicador de ações)] de desdobramentos, bonificações e grupamentos (sem repetir classes)."""
    vistos, out = set(), []
    for ev in eventos or []:
        tipo = (ev.get("label") or "").upper()
        f = num(ev.get("factor"), 10)
        dt = br(ev.get("lastDatePrior") or "")
        if not f or not dt or (dt, tipo, f) in vistos:
            continue
        vistos.add((dt, tipo, f))
        if tipo.startswith("DESDOBRAMENTO") or tipo.startswith("BONIFICA"):
            out.append((dt, 1 + f / 100))
        elif tipo.startswith("GRUPAMENTO"):
            out.append((dt, f))
    return out


CLASSE = {"3": "ON", "4": "PN", "5": "PNA", "6": "PNB", "7": "PNC", "8": "PND"}


def proventos_por_ano(hist, eventos, principal, mult, divs_yahoo):
    """Dividendo por ação (na base de ações de hoje) por ano da data com, para o código principal."""
    fatores = fator_eventos(eventos)
    ajuste = lambda dt: 1 / prod([m for d_ev, m in fatores if dt <= d_ev]) if fatores else 1
    por_ano, eventos_out = {}, []
    if hist:
        classe = CLASSE.get(principal[4:])
        tipos = {h[1] for h in hist}
        if classe not in tipos:  # unit ou BDR: usa a classe que existir (ON primeiro)
            classe = "ON" if "ON" in tipos else ("PN" if "PN" in tipos else max(tipos, key=lambda t: sum(h[1] == t for h in hist)))
            fator_unit = mult
        else:
            fator_unit = 1
        for dc, tipo, acao, v in hist:
            if tipo != classe or not v:
                continue
            dt = date.fromisoformat(dc)
            va = v * ajuste(dt) * fator_unit
            por_ano[dt.year] = por_ano.get(dt.year, 0) + va
            eventos_out.append([dc, "JCP" if "JRS" in acao.upper() or "JUROS" in acao.upper() else acao.title(), round(va, 6)])
        fonte = "B3"
    else:  # sem histórico na B3 (alguns BDRs): dividendos do Yahoo, já ajustados por desdobramentos
        for dc, v in divs_yahoo or []:
            dt = date.fromisoformat(dc)
            por_ano[dt.year] = por_ano.get(dt.year, 0) + v
            eventos_out.append([dc, "Dividendo", round(v, 6)])
        fonte = "Yahoo Finance" if divs_yahoo else None
    eventos_out.sort(reverse=True)
    return {a: round(v, 6) for a, v in por_ano.items()}, eventos_out, fonte


def prod(v):
    out = 1
    for x in v:
        out *= x
    return out


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
    # consolidado quando existir com valores; senão individual (há empresa sem controladas que entrega o
    # consolidado todo zerado, como a TIM)
    util = lambda f: f is not None and len(f["linhas"]) > 20 and sum(1 for x in f["linhas"] if x[6]) > 10
    out = {}
    for (cvm, ref, escopo), f in arq.items():
        if escopo == "ind" and util(arq.get((cvm, ref, "con"))):
            continue
        if escopo == "con" and not util(f) and (cvm, ref, "ind") in arq:
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
                    f["lucro_contr"] = contr[0] if contr and (contr[0] or not val) else val  # linha zerada = não preenchida
        elif tipo == "DFC":
            f = fluxos.setdefault((ini, fim), {"_ordem": ordem})
            f["fco"] = g("6.01", "Caixa Líquido")
            f["fci"] = g("6.02", "Caixa Líquido")
            f["fcf"] = g("6.03", "Caixa Líquido")
            # Depreciação é sempre somada de volta no fluxo; algumas empresas a lançam com sinal trocado.
            f["da"] = sum(abs(val) for cd, (ds, val) in v.items()
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


def cnpj14(s):
    d = re.sub(r"\D", "", s or "")
    return d.zfill(14) if d else ""


def indicadores_periodo(v, sd, preco, acoes, mult, dpa):
    """Indicadores de um ano: resultado do ano, balanço do fim do ano e cotação do último mês do ano."""
    lucro_c, lucro, receita, ebit, da = v.get("lucro_contr"), v.get("lucro"), v.get("receita"), v.get("ebit"), v.get("da")
    ebitda = ebit + abs(da) if ebit is not None and da is not None else None
    pl, pl_c, ativo = sd.get("pl"), sd.get("pl_contr"), sd.get("ativo")
    dl = (sd.get("divida") or 0) - (sd.get("caixa") or 0) if sd.get("pc") is not None else None
    lpa = lucro_c / acoes * mult if lucro_c is not None and acoes else None
    vpa = pl_c / acoes * mult if pl_c is not None and acoes else None
    vm = preco / mult * acoes if preco and acoes else None
    ev = vm + dl if vm is not None and dl is not None else None
    o = {"preco": preco, "vm": vm, "lpa": lpa, "vpa": vpa, "dpa": dpa,
         "p_l": div(preco, lpa, 2) if lpa and lpa > 0 and preco else None,
         "p_vp": div(preco, vpa, 2) if vpa and vpa > 0 and preco else None,
         "dy": div(dpa, preco, 2, 100) if dpa is not None and preco and dpa / preco <= 1 else None,  # acima de 100%: erro de dado
         "payout": div(dpa / mult * acoes, lucro_c, 1, 100) if dpa is not None and lucro_c and lucro_c > 0 and acoes else None,
         "ev_ebitda": div(ev, ebitda, 2) if ev is not None and ebitda and ebitda > 0 else None,
         "ev_ebit": div(ev, ebit, 2) if ev is not None and ebit and ebit > 0 else None,
         "psr": div(vm, receita, 2) if vm and receita and receita > 0 else None,
         "roe": div(lucro_c, pl_c, 2, 100) if lucro_c is not None and pl_c and pl_c > 0 else None,
         "roic": div(ebit * 0.66, pl + dl, 2, 100) if ebit is not None and pl is not None and dl is not None and pl + dl > 0 else None,
         "roa": div(lucro, ativo, 2, 100),
         "mb": div(v.get("lb"), receita, 2, 100), "mebitda": div(ebitda, receita, 2, 100),
         "mebit": div(ebit, receita, 2, 100), "ml": div(lucro, receita, 2, 100),
         "dl_ebitda": div(dl, ebitda, 2) if dl is not None and ebitda and ebitda > 0 else None,
         "dl_pl": div(dl, pl, 2) if dl is not None and pl and pl > 0 else None,
         "lc": div(sd.get("ac"), sd.get("pc"), 2), "giro": div(receita, ativo, 2)}
    return {k: (round(x, 4) if isinstance(x, float) else x) for k, x in o.items()}


def valor_meses_atras(mensal, meses, col=2):
    """Valor da série mensal [[AAAA-MM, fech, ajust]] n meses antes do último ponto (ou o mais próximo antes)."""
    if not mensal:
        return None
    a, m = map(int, mensal[-1][0].split("-"))
    tot = a * 12 + m - 1 - meses
    alvo = f"{tot // 12}-{tot % 12 + 1:02d}"
    cand = [x for x in mensal if x[0] <= alvo]
    return cand[-1][col] if cand and cand[-1][0] >= f"{tot // 12 - 1}-{tot % 12 + 1:02d}" else None


def reta(xs, ys):
    """Reta de mínimos quadrados: (intercepto, inclinação, R²)."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    b = sxy / sxx
    return my - b * mx, b, (sxy * sxy / (sxx * syy) if syy else 1.0)


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
def historico_mensal(y, simbolo, anos=ANOS_HISTORICO + 1):
    """Fechamento mensal (ajustado por desdobramentos), fechamento com proventos reinvestidos e dividendos."""
    r = y.json(f"https://query1.finance.yahoo.com/v8/finance/chart/{simbolo}?range={anos}y&interval=1mo"
               f"&events=div%7Csplit", tentativas=2)
    res = r["chart"]["result"][0]
    ts = res.get("timestamp") or []
    ind = res.get("indicators") or {}
    fech = ((ind.get("quote") or [{}])[0].get("close")) or []
    adj = ((ind.get("adjclose") or [{}])[0].get("adjclose")) or []
    meses = {}
    for i, t in enumerate(ts):
        c = fech[i] if i < len(fech) else None
        if c:
            a = adj[i] if i < len(adj) and adj[i] else c
            meses[datetime.fromtimestamp(t, BRASILIA).strftime("%Y-%m")] = [round(c, 4), round(a, 4)]
    m = [[k, v[0], v[1]] for k, v in sorted(meses.items())]
    divs = sorted([datetime.fromtimestamp(v["date"], BRASILIA).date().isoformat(), round(v["amount"], 6)]
                  for v in ((res.get("events") or {}).get("dividends") or {}).values() if v.get("amount"))
    return m, divs


def referencias(y, cache):
    """Ibovespa (Yahoo), CDI e IPCA mensais (Banco Central) para comparar a rentabilidade."""
    ref = cache.get("ref") or {}
    try:
        ref["ibov"] = [[k, c] for k, c, _ in historico_mensal(y, "%5EBVSP", ANOS_HISTORICO + 1)[0]]
    except Exception as ex:
        log(f"  Ibovespa: {ex}")
    # o Banco Central exige data final e limita cada consulta a 10 anos: duas janelas de 6 anos
    meio = date(HOJE.year - 5, 1, 1)
    janelas = [(date(HOJE.year - ANOS_HISTORICO - 1, 1, 1), meio - timedelta(days=1)), (meio, HOJE)]
    for nome, serie in (("cdi", 4391), ("ipca", 433)):
        try:
            pontos = {}
            for ini, fim in janelas:
                bruto = baixar(BCB.format(serie, ini.strftime("%d/%m/%Y"), fim.strftime("%d/%m/%Y")), timeout=60)
                try:
                    j = json.loads(bruto)
                except ValueError:
                    raise RuntimeError(f"resposta inesperada: {bruto[:120]!r}")
                for x in j:
                    pontos[x["data"][6:10] + "-" + x["data"][3:5]] = float(x["valor"])
            if pontos:
                ref[nome] = sorted([k, v] for k, v in pontos.items())
        except Exception as ex:
            log(f"  {nome.upper()} (Banco Central): {ex}")
            try:  # reserva: mesma série no Ipeadata
                j = json.loads(baixar(IPEA.format(IPEA_SERIE[nome]), timeout=90))
                desde = f"{HOJE.year - ANOS_HISTORICO - 1}-01"
                pontos = {x["VALDATA"][:7]: float(x["VALVALOR"]) for x in j.get("value") or []
                          if x.get("VALVALOR") is not None and x["VALDATA"][:7] >= desde}
                if pontos:
                    ref[nome] = sorted([k, v] for k, v in pontos.items())
                    log(f"  {nome.upper()}: {len(pontos)} meses pelo Ipeadata")
            except Exception as ex2:
                log(f"  {nome.upper()} (Ipeadata): {ex2}")
    cache["ref"] = ref
    salvar("referencias.json", {"atualizado": agora(), "fonte": "Ibovespa: Yahoo Finance; CDI e IPCA: Banco Central", **ref})
    log(f"Referências: Ibovespa {len(ref.get('ibov') or [])}, CDI {len(ref.get('cdi') or [])}, IPCA {len(ref.get('ipca') or [])} meses")


def carregar_fre(cnpjs):
    """Formulário de referência: acionistas relevantes, free float e quantidade de acionistas, por CNPJ."""
    out = {}
    for ano in (HOJE.year, HOJE.year - 1):
        z = zip_cvm("FRE", ano)
        if z is None:
            continue
        dist = {}
        it = linhas_csv(z, f"fre_cia_aberta_distribuicao_capital_{ano}.csv")
        cab = next(it, None)
        for c in it if cab else []:
            if len(c) < len(cab):
                continue
            cnpj = re.sub(r"\D", "", c[cab["CNPJ_Companhia"]])
            if cnpj not in cnpjs or cnpj in out:
                continue
            chave = (c[cab["Data_Referencia"]], int(c[cab["Versao"]] or 0))
            if cnpj in dist and chave < dist[cnpj]["_k"]:
                continue
            q = lambda col: int(float(c[cab[col]] or 0))
            dist[cnpj] = {"_k": chave, "ref": chave[0], "freefloat": num(c[cab["Percentual_Total_Acoes_Circulacao"]], 2) or None,  # 0% = não informado
                          "pf": q("Quantidade_Acionistas_PF"), "pj": q("Quantidade_Acionistas_PJ"),
                          "inst": q("Quantidade_Acionistas_Investidores_Institucionais")}
        pos = {}
        it = linhas_csv(z, f"fre_cia_aberta_posicao_acionaria_{ano}.csv")
        cab = next(it, None)
        for c in it if cab else []:
            if len(c) < len(cab) or c[cab["ID_Acionista_Relacionado"]].strip():
                continue  # só acionistas diretos
            cnpj = re.sub(r"\D", "", c[cab["CNPJ_Companhia"]])
            if cnpj not in cnpjs or cnpj in out:
                continue
            chave = (c[cab["Data_Referencia"]], int(c[cab["Versao"]] or 0))
            p = pos.setdefault(cnpj, {})
            p.setdefault(chave, []).append([c[cab["Acionista"]].strip(), c[cab["Tipo_Pessoa_Acionista"]].strip(),
                                            num(c[cab["Percentual_Acao_Ordinaria_Circulacao"]], 3),
                                            num(c[cab["Percentual_Acao_Preferencial_Circulacao"]], 3),
                                            num(c[cab["Percentual_Total_Acoes_Circulacao"]], 3),
                                            c[cab["Acionista_Controlador"]].strip() == "S"])
        for cnpj in set(dist) | set(pos):
            d = dist.get(cnpj, {})
            linhas = pos[cnpj][max(pos[cnpj])] if cnpj in pos else []
            out[cnpj] = {**{k: v for k, v in d.items() if k != "_k"}, "acionistas": resumir_acionistas(linhas)}
        log(f"  CVM FRE {ano}: {len(dist)} distribuições, {len(pos)} composições acionárias")
        del z
    return out


def resumir_acionistas(linhas):
    """Mostra quem tem 1% ou mais; junta os demais do grupo de controle. Sem CPF/CNPJ."""
    princ, ctrl_resto, fim = [], [0, 0, 0], []
    for nome, tipo, on, pn, tot, ctrl in linhas:
        on, pn, tot = on or 0, pn or 0, tot or 0
        nl = nome.lower()
        if nl.startswith("outros") or "tesouraria" in nl:
            fim.append(["Ações em tesouraria" if "tesouraria" in nl else "Outros", "", on, pn, tot, False])
        elif tot >= 1 or on >= 5 or pn >= 5:
            princ.append([nome, tipo, on, pn, tot, ctrl])
        elif ctrl:
            ctrl_resto = [ctrl_resto[0] + on, ctrl_resto[1] + pn, ctrl_resto[2] + tot]
        else:
            fim.append(["Outros", "", on, pn, tot, False])
    princ.sort(key=lambda l: -l[4])
    if ctrl_resto[2] > 0.0005:
        princ.append(["Demais integrantes do grupo de controle", "", *[round(x, 3) for x in ctrl_resto], True])
    junto = {}
    for l in fim:  # soma linhas "Outros"
        j = junto.setdefault(l[0], [l[0], "", 0, 0, 0, False])
        j[2], j[3], j[4] = round(j[2] + l[2], 3), round(j[3] + l[3], 3), round(j[4] + l[4], 3)
    return princ + sorted(junto.values(), key=lambda l: l[0] != "Outros")


def acentos(t):
    """Conserta acentos digitados separados da letra ("Ini´cio", "Definic¸a~o") em alguns assuntos."""
    t = unicodedata.normalize("NFC", t)
    for sinal, comb in (("´", "\u0301"), ("`", "\u0300"), ("¸", "\u0327"), ("~", "\u0303"), ("^", "\u0302")):
        t = re.sub(r"([A-Za-z])" + re.escape(sinal), lambda m: unicodedata.normalize("NFC", m.group(1) + comb), t)
    return t


CAT_DOC = {"Fato Relevante", "Comunicado ao Mercado", "Aviso aos Acionistas", "Calendário de Eventos Corporativos",
           "Relatório Proventos"}
TIPO_DOC = {"Press-release", "Apresentações a analistas/agentes do mercado"}


def carregar_ipe(cnpjs, por_empresa=25):
    """Fatos relevantes, comunicados, avisos aos acionistas e releases de resultados entregues à CVM."""
    docs = {}
    for ano in (HOJE.year, HOJE.year - 1):
        z = zip_cvm("IPE", ano)
        if z is None:
            continue
        it = linhas_csv(z, f"ipe_cia_aberta_{ano}.csv")
        cab = next(it, None)
        n = 0
        for c in it if cab else []:
            if len(c) < len(cab):
                continue
            cnpj = re.sub(r"\D", "", c[0])
            cat, tipo = c[cab["Categoria"]], c[cab["Tipo"]]
            if cnpj not in cnpjs or not (cat in CAT_DOC or (cat == "Dados Econômico-Financeiros" and tipo in TIPO_DOC)):
                continue
            extra = len(c) - len(cab)  # ';' dentro do assunto
            assunto = ";".join(c[cab["Assunto"]:cab["Assunto"] + 1 + extra]).strip()
            entrega, link = c[cab["Data_Entrega"] + extra], c[-1].strip()
            if not link.startswith("http"):
                continue
            assunto = acentos(assunto)
            chave = (cat, tipo, assunto.lower())  # o mesmo documento reapresentado aparece uma vez, o mais recente
            atual = docs.setdefault(cnpj, {}).get(chave)
            if atual is None or entrega > atual[0]:
                docs[cnpj][chave] = [entrega, cat, tipo, assunto[:220], link]
            n += 1
        log(f"  CVM IPE {ano}: {n} documentos")
        del z
    return {k: sorted(v.values(), reverse=True)[:por_empresa] for k, v in docs.items()}


# ---------------------------------------------------------------- principal
def main():
    from concurrent.futures import ThreadPoolExecutor
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
    try:
        bdrs_fca(empresas_b3)
    except Exception as ex:
        log(f"FCA (BDRs): {ex}")
    salvar(CACHE, cache)

    # códigos de negociação de ações (e BDRs de emissores com balanço na CVM) por empresa
    tickers, isin_ticker = {}, {}
    for raiz, e in empresas_b3.items():
        suf = SUFIXOS_BDR if e.get("bdr") else SUFIXOS
        for oc in (e.get("det") or {}).get("otherCodes") or []:
            t = (oc.get("code") or "").upper()
            if re.fullmatch(r"[A-Z]{4}\d{1,2}", t) and t[4:] in suf and t not in tickers.get(raiz, []):
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
        for func in (atualizar_proventos, atualizar_historico_proventos):
            try:
                func(cache["b3"], [r for r in negociadas if r in cache["b3"]])
            except Exception as ex:
                log(f"B3 {func.__name__}: {ex}")
            salvar(CACHE, cache)

    # histórico mensal do código mais negociado de cada empresa (renovado a cada 6 dias)
    liq_de = lambda t: (precos[t].get("averageDailyVolume3Month") or precos[t].get("regularMarketVolume") or 0) * precos[t]["regularMarketPrice"]
    principais = {raiz: max([t for t in ts if t in precos], key=liq_de) for raiz, ts in tickers.items() if any(t in precos for t in ts)}
    cache_precos = cache.setdefault("precos", {})
    agora_ts = time.time()
    velho = lambda t: (cache_precos.get(t) or {}).get("v") != VERSAO_PRECOS or agora_ts - cache_precos[t].get("ts", 0) > 6 * 86400
    faltam = sorted([t for t in principais.values() if velho(t)], key=lambda t: (cache_precos.get(t) or {}).get("ts", 0))[:MAX_HISTORICOS]

    def buscar(t):
        try:
            m, dv = historico_mensal(y, t + ".SA")
            cache_precos[t] = {"ts": agora_ts, "v": VERSAO_PRECOS, "m": m, "div": dv}
            return True
        except Exception:
            return False
    with ThreadPoolExecutor(max_workers=3) as ex:
        ok = sum(ex.map(buscar, faltam))
    log(f"Yahoo: {ok} de {len(faltam)} históricos mensais renovados")
    for t in list(cache_precos):
        if t not in principais.values():
            del cache_precos[t]
    salvar(CACHE, cache)
    try:
        referencias(y, cache)
    except Exception as ex:
        log(f"Referências: {ex}")

    alvo = {int(e["lista"]["codeCVM"]) for raiz, e in empresas_b3.items()
            if raiz in principais and str(e["lista"].get("codeCVM", "")).isdigit()}
    cvm, capital = carregar_cvm(alvo)
    log(f"CVM: demonstrações de {len(cvm)} de {len(alvo)} empresas")
    cnpjs = {cnpj14(e["lista"].get("cnpj")) for raiz, e in empresas_b3.items() if raiz in principais} - {""}
    fre, docs = {}, {}
    try:
        fre = carregar_fre(cnpjs)
    except Exception as ex:
        log(f"CVM FRE: {ex}")
    try:
        docs = carregar_ipe(cnpjs)
    except Exception as ex:
        log(f"CVM IPE: {ex}")

    os.makedirs(os.path.join(DADOS, "empresas"), exist_ok=True)
    linhas = []
    sem_balanco = 0
    mes_atual = HOJE.strftime("%Y-%m")
    falhas_emp = 0
    for raiz, e in sorted(empresas_b3.items()):
        try:
            if raiz not in principais:
                continue
            ts = [t for t in tickers[raiz] if t in precos]
            principal = principais[raiz]
            lista, det, comp = e.get("lista") or {}, e.get("det") or {}, e.get("comp") or {}
            bdr = bool(e.get("bdr"))
            s, ss, sg = setor_b3(det.get("industryClassification"))
            nome = (lista.get("companyName") or det.get("companyName") or raiz).strip()
            codigo = int(lista["codeCVM"]) if str(lista.get("codeCVM", "")).isdigit() else None
            r = resumo_empresa(cvm[codigo]) if codigo in cvm else None
            if r is None:
                sem_balanco += 1
            cnpj = cnpj14(lista.get("cnpj"))

            # ações: B3; tesouraria pelo ITR/DFP; emissor estrangeiro: capital informado à CVM
            cap = capital.get(cnpj, {})
            on, pn = comp.get("on") or cap.get("on") or 0, comp.get("pn") or cap.get("pn") or 0
            total = (on + pn) or comp.get("total") or cap.get("total") or 0
            if bdr and cap.get("total"):
                on, pn, total = cap.get("on") or 0, cap.get("pn") or 0, cap["total"]
            tes = cap.get("tesouraria") or 0
            acoes = total - tes if 0 < tes < total * 0.5 else total

            preco = {t: float(precos[t]["regularMarketPrice"]) for t in ts}
            liq = {t: liq_de(t) for t in ts}
            p_on = preco.get(raiz + "3")
            pn_ts = sorted([t for t in ts if t[4:] in ("4", "5", "6", "7", "8")], key=lambda t: -liq[t])
            p_pn = preco[pn_ts[0]] if pn_ts else None
            ref_preco = p_on or p_pn
            mult_bdr = 1.0
            if bdr:
                vm = preco[principal] * acoes if acoes else None
                ym = precos[principal].get("marketCap")
                if vm and ym:
                    razao = vm / ym
                    if not 0.8 < razao < 1.25:  # um BDR não equivale a uma ação: usa o valor de mercado do Yahoo
                        mult_bdr, vm = razao, ym
                elif ym:
                    vm = ym
            elif ref_preco and total:
                vm = on * (p_on or p_pn) + pn * (p_pn or p_on)
                vm *= (acoes / total) if total else 1
            else:  # só a unit negocia
                u = next((t for t in ts if t.endswith("11")), None)
                vm = precos[u].get("marketCap") if u else None

            def mult_de(t):
                if bdr:
                    return mult_bdr
                if t.endswith("11") and ref_preco:
                    m = round(preco[t] / ref_preco)
                    return m if 1 <= m <= 10 and abs(preco[t] / (m * ref_preco) - 1) < 0.2 else 1
                return 1

            # proventos dos últimos 12 meses por código (B3)
            prov12 = {}
            unico = ts[0] if len(tickers[raiz]) == 1 else None
            for p in comp.get("proventos") or []:
                dc = br(p.get("lastDatePrior") or "")
                t = isin_ticker.get(p.get("isinCode") or p.get("assetIssued")) or unico
                if t and dc and HOJE - timedelta(days=365) < dc <= HOJE:
                    prov12[t] = prov12.get(t, 0) + (num(p.get("rate"), 8) or 0)
            if not comp:
                prov_total = None
            elif bdr:
                prov_total = prov12.get(principal, 0) / mult_bdr * acoes
            else:
                prov_total = prov12.get(raiz + "3", 0) * on + (prov12.get(pn_ts[0], 0) if pn_ts else 0) * pn

            # histórico de preços do código principal, com o mês corrente pela cotação de hoje
            cp = cache_precos.get(principal) or {}
            mensal = [list(x) for x in cp.get("m") or [] if len(x) >= 3]
            p_hoje = preco[principal]
            if mensal and mensal[-1][0] == mes_atual:
                f = mensal[-1][2] / mensal[-1][1] if mensal[-1][1] else 1
                mensal[-1] = [mes_atual, round(p_hoje, 4), round(p_hoje * f, 4)]
            elif mensal and mensal[-1][0] < mes_atual:
                mensal.append([mes_atual, round(p_hoje, 4), round(p_hoje, 4)])
            mp = mult_de(principal)
            dpa_ano, prov_hist, fonte_prov = proventos_por_ano(e.get("hist"), comp.get("eventos"), principal, mp, cp.get("div"))

            ttm = (r or {}).get("ttm") or {}
            bal = (r or {}).get("balanco") or {}
            lucro, lucro_c = ttm.get("lucro"), ttm.get("lucro_contr")
            receita, ebit, da = ttm.get("receita"), ttm.get("ebit"), ttm.get("da")
            ebitda = ebit + abs(da) if ebit is not None and da is not None else None
            pl, pl_c, ativo = bal.get("pl"), bal.get("pl_contr"), bal.get("ativo")
            ac, pc, pnc = bal.get("ac"), bal.get("pc"), bal.get("pnc")
            dl = (bal.get("divida") or 0) - (bal.get("caixa") or 0) if pc is not None else None
            fco = ttm.get("fco")
            fcl = (fco + ttm.get("capex")) if fco is not None and ttm.get("capex") is not None else None
            anos = sorted((r or {}).get("anuais", {}))
            por_ano = {ano_de(k[1]): r["anuais"][k] for k in anos} if r else {}
            cagr_r = cagr(por_ano, "receita")
            cagr_l = cagr(por_ano, "lucro_contr")
            cagr_e = cagr({a: {"ebitda": v["ebit"] + abs(v["da"]) if v.get("ebit") is not None and v.get("da") is not None else None}
                           for a, v in por_ano.items()}, "ebitda")
            lpa = div(lucro_c, acoes, 4) if acoes else None
            vpa = div(pl_c, acoes, 4) if acoes else None
            payout = div(prov_total, lucro_c, 2, 100) if prov_total is not None and lucro_c and lucro_c > 0 else None
            if bdr:  # recibo sem equivalência confiável com a ação: fica só na lista de BDRs
                pvp_chk = div(preco[principal], vpa * mult_bdr) if vpa else None
                pl_chk = div(preco[principal], lpa * mult_bdr) if lpa else None
                if not vm or (pvp_chk is not None and abs(pvp_chk) > 300) or (pl_chk is not None and abs(pl_chk) > 3000):
                    log(f"  {raiz}: BDR com valores fora de escala (P/VP {pvp_chk}, P/L {pl_chk}); fica só na lista de BDRs")
                    continue

            # ano a ano: demonstrações + cotação do fim de cada ano + proventos do ano
            anual, ind_hist = {}, {}
            fech_mes = {m[0]: m[1] for m in mensal}
            if r:
                for k in anos[-ANOS_HISTORICO:]:
                    ano_ref = ano_de(k[1])
                    v, sd = r["anuais"][k], r["saldos"].get(k[1], {})
                    da_a = v.get("da")
                    anual[str(ano_ref)] = {
                        **{c: v.get(c) for c in CAMPOS_FLUXO},
                        "ebitda": v["ebit"] + abs(da_a) if v.get("ebit") is not None and da_a is not None else None,
                        **{c: sd.get(c) for c in CAMPOS_SALDO},
                    }
                    dpa = dpa_ano.get(k[1].year, 0 if fonte_prov else None)
                    ind_hist[str(ano_ref)] = indicadores_periodo(v, sd, fech_mes.get(k[1].strftime("%Y-%m")), acoes, mp, dpa)
            ult5 = [ind_hist[a] for a in sorted(ind_hist)[-5:]]

            # lucro x cotação: tendência de todos os anos de histórico (retas ajustadas ao lucro e à cotação),
            # lucro para cada R$ 100 de valor de mercado e sinais de distorção (lucro instável, salto recente,
            # lucro acima do operacional)
            lc = {}
            if r and lucro_c is not None and mensal and mensal[-1][1] and vm:
                corte = ""  # a série de preços só vale depois da última quebra no Yahoo (ex.: MMAQ3)
                for m in mensal:
                    if m[2] is not None and m[2] <= 0:
                        corte = m[0] + "~"
                for a, b in zip(mensal, mensal[1:]):
                    if a[1] and b[1] and not 0.125 < b[1] / a[1] < 8:
                        corte = max(corte, b[0])
                lucros = {int(a): v["lucro_contr"] for a, v in anual.items() if v.get("lucro_contr") is not None}
                fechados = [a for a in sorted(lucros) if date(a, 12, 31) < r["ref"]]
                pts = [(date(a, 12, 31), lucros[a], fech_mes.get(f"{a}-12"), (ind_hist.get(str(a)) or {}).get("vm"))
                       for a in fechados if f"{a}-12" >= corte]
                pts = [p for p in pts if p[2] and p[3]] + [(r["ref"], lucro_c, mensal[-1][1], vm)]
                maior = max(abs(p[1]) for p in pts)
                while pts and abs(pts[0][1]) < maior * 0.001:
                    pts.pop(0)  # anos antes de a empresa operar (ex.: JBS N.V. em 2022 e 2023)
                if len(pts) >= 4 and (pts[-1][0] - pts[0][0]).days >= 3 * 365:
                    xs = [(p[0] - pts[0][0]).days / 365.25 for p in pts]
                    ls, T = [p[1] for p in pts], xs[-1]
                    if min(ls) > 0:  # sempre com lucro: reta no logaritmo (crescimento composto)
                        a, b, r2 = reta(xs, [math.log(v) for v in ls])
                        f0, f1 = math.exp(a), math.exp(a + b * T)
                    else:  # algum ano de prejuízo: reta em reais
                        a, b, r2 = reta(xs, ls)
                        f0, f1 = a, a + b * T
                    g_l = (f1 / f0) ** (1 / T) - 1 if f0 > 0 and f1 > 0 and f0 >= 0.1 * f1 else None
                    xp = xs[:-1] + [(HOJE - pts[0][0]).days / 365.25]
                    _, bp, _ = reta(xp, [math.log(p[2]) for p in pts])
                    vm0 = pts[0][3]
                    lc = {"lc_desde": pts[0][0].year, "lc_n": len(pts),
                          "lc_lucro": round(g_l * 100, 2) if g_l is not None else None,
                          "lc_cot": round((math.exp(bp) - 1) * 100, 2), "lc_r2": round(r2, 2),
                          "lc_t0": round(f0), "lc_t1": round(f1),
                          "lc_y0": round(pts[0][1] / vm0 * 100, 2), "lc_yc": round(lucro_c / vm0 * 100, 2),
                          "lc_yh": round(lucro_c / vm * 100, 2)}
                    ant = [lucros[a] for a in fechados[-3:]]
                    if len(ant) == 3 and sum(ant) > 0:
                        lc["lc_salto"] = round(lucro_c / (sum(ant) / 3), 2)
                    if ebit and ebit > 0 and lucro_c > 0:
                        lc["lc_op"] = round(lucro_c / ebit, 2)

            teto = {"p_l": 100, "p_vp": 50, "ev_ebitda": 100}  # anos de lucro quase zero distorcem a média

            def media(campo, so_pos=False):
                xs = [x[campo] for x in ult5 if x.get(campo) is not None and (not so_pos or 0 < x[campo] <= teto.get(campo, 1e9))]
                return round(sum(xs) / len(xs), 2) if len(xs) >= 3 else None
            medias = {c: media(c, c in ("p_l", "p_vp", "ev_ebitda")) for c in ("p_l", "p_vp", "dy", "roe", "roic", "ml", "payout", "ev_ebitda")}
            anos_lucro = 0
            for a in sorted(anual, reverse=True):
                if (anual[a].get("lucro_contr") or 0) > 0:
                    anos_lucro += 1
                else:
                    break
            anos_div = None
            if fonte_prov:
                anos_div = 0
                for a in range(HOJE.year - 1, HOJE.year - 1 - ANOS_HISTORICO, -1):
                    if dpa_ano.get(a, 0) > 0:
                        anos_div += 1
                    else:
                        break
            adj_hoje = mensal[-1][2] if mensal else None
            a12, a60 = valor_meses_atras(mensal, 12), valor_meses_atras(mensal, 60)
            pos = lambda x: x is not None and x > 0
            ret12 = round((adj_hoje / a12 - 1) * 100, 2) if pos(adj_hoje) and pos(a12) else None
            ret60 = round(((adj_hoje / a60) ** (1 / 5) - 1) * 100, 2) if pos(adj_hoje) and pos(a60) else None
            listagem = (comp.get("segmento") or lista.get("market") or "").strip()
            tag = None if bdr else TAG_ALONG.get(listagem.upper(), 80)
            acion = fre.get(cnpj) or {}

            for t in ts:
                p = preco[t]
                mult = mult_de(t)
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
                    "p_ebitda": div(vm_t, ebitda) if ebitda and ebitda > 0 else None,
                    "ev_receita": div(ev_t, receita) if receita and receita > 0 else None,
                    "p_fco": div(vm_t, fco) if fco and fco > 0 else None,
                    "liquidezseca": div(ac - (bal.get("estoques") or 0), pc, 2) if ac is not None else None,
                    "liquidezimediata": div(bal.get("caixa"), pc, 2) if ac is not None else None,
                    "ebitda_cagr5": cagr_e, "dy_media5": medias["dy"], "roe_media5": medias["roe"],
                    "pl_medio5": medias["p_l"], "pvp_medio5": medias["p_vp"],
                    "anos_lucro": anos_lucro if r else None, "anos_div": anos_div,
                    "freefloat": acion.get("freefloat"), "tagalong": tag,
                    "ret12": ret12 if t == principal else None, "ret60": ret60 if t == principal else None,
                    "bdr": 1 if bdr else None, **lc,
                })

            # arquivo da empresa: histórico para gráficos e tabelas no app
            trimestres = []
            if r:
                for k in sorted(r["trim"])[-12:]:
                    v = r["trim"][k]
                    trimestres.append([k[1].isoformat(), v.get("receita"), v.get("lb"), v.get("ebit"), v.get("lucro_contr")])
            proventos = []
            for p in comp.get("proventos") or []:
                t = isin_ticker.get(p.get("isinCode") or p.get("assetIssued")) or unico
                if t:
                    proventos.append([t, (p.get("label") or "").title(), p.get("lastDatePrior"), p.get("paymentDate"),
                                      num(p.get("rate"), 8), p.get("relatedTo")])
            empresa = {
                "atualizado": agora(), "raiz": raiz, "nome": nome, "pregao": lista.get("tradingName"),
                "cnpj": cnpj, "cvm": codigo, "setor": [s, ss, sg], "listagem": listagem, "tagalong": tag, "bdr": bdr,
                "site": det.get("website"), "atividade": det.get("activity"), "tickers": ts,
                "acoes": {"on": on, "pn": pn, "tesouraria": tes, "total": total},
                "escopo": cvm.get(codigo, {}).get("escopo") if codigo else None,
                "balanco_em": r["data_balanco"].isoformat() if r and r.get("data_balanco") else None,
                "ttm_ate": r["ref"].isoformat() if r else None,
                "ttm": {c: ttm.get(c) for c in CAMPOS_FLUXO} if r else None,
                "balanco": {c: bal.get(c) for c in CAMPOS_SALDO} if r else None,
                "anual": anual, "trimestres": trimestres, "proventos": proventos,
                "ind_hist": ind_hist, "medias5": medias,
                "dividendos": {"fonte": fonte_prov, "codigo": principal,
                               "por_ano": {str(a): v for a, v in sorted(dpa_ano.items()) if a >= HOJE.year - ANOS_HISTORICO},
                               "eventos": [x for x in prov_hist if x[0] >= f"{HOJE.year - ANOS_HISTORICO}"][:160]},
                "acionistas": acion or None, "documentos": docs.get(cnpj, []),
                "eventos": [[(ev.get("label") or "").title(), ev.get("lastDatePrior"), num(ev.get("factor"), 6)]
                            for ev in comp.get("eventos") or []],
                "precos": {"codigo": principal, "mensal": mensal, "ret12": ret12, "ret60": ret60},
            }
            with open(os.path.join(DADOS, "empresas", raiz + ".json"), "w", encoding="utf-8") as fh:
                json.dump(empresa, fh, ensure_ascii=False, separators=(",", ":"))
        except Exception as ex:  # dado estranho de uma empresa não derruba as outras
            falhas_emp += 1
            log(f"  {raiz}: {type(ex).__name__}: {ex}")
            if falhas_emp == 1:
                import traceback
                traceback.print_exc()
    if falhas_emp:
        log(f"{falhas_emp} empresas com erro de cálculo ficaram de fora")

    salvar(CACHE, cache)
    codigos = {l["t"] for l in linhas}
    minimo = int(os.environ.get("MINIMO_ACOES", "250"))
    faltam = ({"PETR4", "VALE3", "ITUB4"} - codigos) if minimo >= 250 else set()
    if len(linhas) < minimo or faltam:
        raise RuntimeError(f"resultado incompleto: {len(linhas)} códigos, faltando {sorted(faltam)}")
    linhas.sort(key=lambda l: l["t"])
    dados = {"atualizado": agora(),
             "fonte": "demonstrações, formulários e comunicados da CVM, cadastro e proventos da B3 e cotações do Yahoo Finance",
             "k": CHAVES, "d": [[l.get(c) for c in CHAVES] for l in linhas]}
    tmp = os.path.join(RAIZ, "acoes.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dados, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, os.path.join(RAIZ, "acoes.json"))
    log(f"OK: {len(linhas)} códigos de {len({l['raiz'] for l in linhas})} empresas ({sum(1 for l in linhas if l['bdr'])} BDRs); "
        f"{sem_balanco} empresas sem demonstração; B3 {'ok' if fonte_b3 else 'indisponível'}")
    for t in ("PETR4", "VALE3", "ITUB4", "WEGE3", "BBAS3", "TAEE11", "INBR32", "JBSS32", "AURA33"):
        l = next((x for x in linhas if x["t"] == t), None)
        if l:
            log("  " + t + ": " + ", ".join(f"{k}={l.get(k)}" for k in (
                "price", "dy", "p_l", "p_vp", "roe", "margemliquida", "dividaliquidaebitda", "ev_ebitda", "valormercado",
                "dy_media5", "pl_medio5", "anos_div", "freefloat", "tagalong", "ret12", "ret60")))


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        import traceback
        traceback.print_exc()
        log(f"Ações falhou: {ex}")
        sys.exit(1)
