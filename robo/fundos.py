"""Fundos de investimento brasileiros (dados abertos da CVM) com rentabilidade e comparação com o CDI.

Entram as classes abertas, não exclusivas, em funcionamento, para público geral ou qualificado,
com patrimônio de pelo menos R$ 50 milhões. Grava dados/fundos.json.
"""
import csv
import io
import json
import sys
import zipfile
from datetime import date, datetime, timedelta

from comum import BRASILIA, baixar, csv_linhas, log, num, salvar, tabela, texto

CAD = "https://dados.cvm.gov.br/dados/FI/CAD/DADOS/registro_fundo_classe.zip"
DIARIO = "https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_{:%Y%m}.zip"
CDI = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json&dataInicial={:%d/%m/%Y}&dataFinal={:%d/%m/%Y}"
PL_MINIMO = 50e6
MIN_COTISTAS = 10
CHAVES = ["c", "n", "cls", "anb", "gest", "adm", "pl", "cot", "r1m", "rano", "r12", "r24", "cdi12", "dt",
          "pub", "trib", "ext", "ini"]


def digitos(c):
    return "".join(ch for ch in (c or "") if ch.isdigit())


def fmt_cnpj(d):
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}" if len(d) == 14 else d


def cadastro():
    z = zipfile.ZipFile(io.BytesIO(baixar(CAD, timeout=180)))
    arq = {n.split("/")[-1]: n for n in z.namelist()}
    classes = csv_linhas(z.read(arq["registro_classe.csv"]))
    fundos = {l["ID_Registro_Fundo"]: l for l in csv_linhas(z.read(arq["registro_fundo.csv"]))}
    tipos = {}
    alvo = {}
    for c in classes:
        tipos[c.get("Tipo_Classe")] = tipos.get(c.get("Tipo_Classe"), 0) + 1
        if c.get("Situacao") != "Em Funcionamento Normal" or c.get("Exclusivo") == "S":
            continue
        if (c.get("Forma_Condominio") or "").lower() != "aberto":
            continue
        tipo = (c.get("Tipo_Classe") or "") + " " + (c.get("Classificacao") or "")
        if any(x in tipo for x in ("FII", "FIDC", "FIP", "FIAGRO", "FMP", "FUNCINE")):
            continue
        pub = c.get("Publico_Alvo") or ""
        if "Profissional" in pub:
            continue
        pl = num(c.get("Patrimonio_Liquido"), 2) or 0
        if pl < PL_MINIMO:
            continue
        f = fundos.get(c.get("ID_Registro_Fundo"), {})
        alvo[digitos(c.get("CNPJ_Classe"))] = {
            "n": (c.get("Denominacao_Social") or "").strip(), "cls": c.get("Classificacao") or "",
            "anb": c.get("Classificacao_Anbima") or "", "gest": (f.get("Gestor") or "").strip(),
            "adm": (f.get("Administrador") or "").strip(), "pl": pl, "pub": pub,
            "trib": c.get("Tributacao_Longo_Prazo") or "", "ext": c.get("Permitido_Aplicacao_CemPorCento_Exterior") or "",
            "ini": c.get("Data_Inicio") or "",
        }
    log(f"tipos de classe na CVM: {dict(sorted(tipos.items(), key=lambda x: -x[1])[:12])}")
    log(f"classes selecionadas: {len(alvo)}")
    return alvo


def cotas_do_mes(mes, alvo):
    """{cnpj: [(data, cota, pl, cotistas)]} de um mês do informe diário."""
    try:
        z = zipfile.ZipFile(io.BytesIO(baixar(DIARIO.format(mes), timeout=240)))
    except Exception as e:
        log(f"  informe diário {mes:%Y-%m}: {e}")
        return None
    por = {}
    for n in z.namelist():
        for l in csv.DictReader(io.StringIO(texto(z.read(n))), delimiter=";"):
            c = digitos(l.get("CNPJ_FUNDO_CLASSE") or l.get("CNPJ_FUNDO"))
            if c not in alvo:
                continue
            q = num(l.get("VL_QUOTA"), 10)
            if q and q > 0:
                por.setdefault(c, {}).setdefault(l.get("ID_SUBCLASSE") or "", []).append(
                    (l["DT_COMPTC"], q, num(l.get("VL_PATRIM_LIQ"), 2), num(l.get("NR_COTST"), 0)))
    # cota da classe; se só houver subclasses, sempre a mesma (a de menor código)
    out = {c: sorted(subs[min(subs)]) for c, subs in por.items()}
    log(f"  informe diário {mes:%Y-%m}: {len(out)} fundos")
    return out


def cota_em(series, alvo_data):
    """Última cota até a data pedida, procurando nos meses carregados."""
    melhor = None
    for s in series:
        for d, q, *_ in s:
            if d <= alvo_data and (melhor is None or d > melhor[0]):
                melhor = (d, q)
    return melhor


def cdi_acumulado(inicio, fim):
    try:
        dados = json.loads(baixar(CDI.format(inicio, fim), timeout=60))
        fator = 1.0
        for p in dados:
            d = datetime.strptime(p["data"], "%d/%m/%Y").date()
            if inicio < d <= fim:
                fator *= 1 + float(p["valor"]) / 100
        return fator - 1
    except Exception as e:
        log(f"  CDI indisponível: {e}")
        return None


def main():
    alvo = cadastro()
    hoje = datetime.now(BRASILIA).date()
    mes = hoje.replace(day=1)
    atual = cotas_do_mes(mes, alvo)
    if not atual or len(atual) < len(alvo) * 0.5:
        mes = (mes - timedelta(days=1)).replace(day=1)
        atual = cotas_do_mes(mes, alvo) or {}
    if not atual:
        raise RuntimeError("informe diário indisponível")
    ultima = max(s[-1][0] for s in atual.values())
    d_ult = date.fromisoformat(ultima)
    alvos = {"r1m": d_ult - timedelta(days=30), "rano": date(d_ult.year - 1, 12, 31),
             "r12": d_ult - timedelta(days=365), "r24": d_ult - timedelta(days=730)}
    meses = {mes: atual}
    for d in alvos.values():
        m = d.replace(day=1)
        if m not in meses:
            meses[m] = cotas_do_mes(m, alvo) or {}
    cdi12 = cdi_acumulado(alvos["r12"], d_ult)

    linhas = []
    for c, info in alvo.items():
        serie = atual.get(c)
        if not serie:
            continue
        dt, cota, pl, cot = serie[-1]
        if dt < (d_ult - timedelta(days=10)).isoformat():
            continue  # parou de informar
        if (cot or 0) < MIN_COTISTAS:
            continue  # fundo master ou quase exclusivo: o investidor comum não aplica nele
        l = {"c": fmt_cnpj(c), **info, "pl": pl or info["pl"], "cot": cot, "dt": dt}
        for k, d in alvos.items():
            m = d.replace(day=1)
            ref = cota_em([meses.get(m, {}).get(c, []), meses.get((m - timedelta(days=1)).replace(day=1), {}).get(c, [])],
                          d.isoformat())
            l[k] = round((cota / ref[1] - 1) * 100, 2) if ref and ref[1] else None
            if l[k] is not None and abs(l[k]) > 500:
                l[k] = None
        l["cdi12"] = round(l["r12"] / (cdi12 * 100) * 100, 1) if l.get("r12") is not None and cdi12 else None
        linhas.append(l)
    linhas.sort(key=lambda l: -(l["pl"] or 0))
    if len(linhas) < 300:
        raise RuntimeError(f"só {len(linhas)} fundos")
    salvar("fundos.json", tabela(CHAVES, linhas, fonte="Dados abertos da CVM (cadastro e informe diário) e CDI do Banco Central",
                                 data_cotas=ultima, cdi12=round(cdi12 * 100, 2) if cdi12 else None))
    log(f"OK: {len(linhas)} fundos (cotas até {ultima})")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"Fundos falhou: {e}")
        sys.exit(1)
