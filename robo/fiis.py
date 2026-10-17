"""FIIs negociados na B3: cadastro e números mensais da CVM + cotação do Yahoo Finance.

Grava dados/fiis.json. Uso: python robo/fiis.py
"""
import re
import sys
from datetime import datetime, timedelta

from comum import Yahoo, baixar, log, mudanca_12m, num, salvar, tabela, zip_csvs, BRASILIA

CVM = "https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{}.zip"
CHAVES = ["t", "n", "seg", "tipo", "mand", "gest", "adm", "price", "dy", "pvp", "vpc", "pl", "cot", "liq",
          "ult", "dym", "rend12", "var12", "tx", "papel", "imoveis", "fof", "cnpj", "ref", "publico"]
PAPEL = ("LIG", "Letras_Hipotecarias", "Debentures", "Notas_Promissorias")
IMOVEIS = ("Direitos_Bens_Imoveis", "Acoes_Sociedades_Atividades_FII", "Cotas_Sociedades_Atividades_FII")


def ultima_versao(linhas):
    """{cnpj: {data: linha}} mantendo a maior versão de cada mês."""
    out = {}
    for l in linhas:
        c, d = l.get("CNPJ_Fundo_Classe") or l.get("CNPJ_Fundo"), l.get("Data_Referencia")
        if not c or not d:
            continue
        atual = out.setdefault(c, {}).get(d)
        if atual is None or int(l.get("Versao") or 0) >= int(atual.get("Versao") or 0):
            out[c][d] = l
    return out


def carregar_cvm():
    ano = datetime.now(BRASILIA).year
    geral, compl, ativo = [], [], []
    for a in (ano - 1, ano):
        try:
            arquivos = zip_csvs(baixar(CVM.format(a)))
        except Exception as e:
            log(f"CVM FII {a}: {e}")
            continue
        for nome, linhas in arquivos.items():
            if "geral" in nome:
                geral += linhas
            elif "complemento" in nome:
                compl += linhas
            elif "ativo_passivo" in nome:
                ativo += linhas
    if not geral:
        raise RuntimeError("informe mensal de FIIs indisponível")
    return ultima_versao(geral), ultima_versao(compl), ultima_versao(ativo)


def soma(l, campos):
    return sum(num(l.get(c)) or 0 for c in campos)


def em_papel(l):
    """CRI/CRA e LCI aparecem em colunas antigas e novas; vale a maior de cada par."""
    par = lambda a, b: max(num(l.get(a)) or 0, num(l.get(b)) or 0)
    return par("CRI", "CRI_CRA") + par("LCI", "LCI_LCA") + soma(l, PAPEL)


def main():
    geral, compl, ativo = carregar_cvm()
    limite = (datetime.now(BRASILIA) - timedelta(days=200)).strftime("%Y-%m-%d")
    candidatos = {}
    for cnpj, meses in geral.items():
        ref = max(meses)
        g = meses[ref]
        isin = (g.get("Codigo_ISIN") or "").strip().upper()
        if ref < limite or g.get("Mercado_Negociacao_Bolsa") != "S" or not re.match(r"^BR[A-Z0-9]{4}CTF", isin):
            continue
        ticker = isin[2:6] + "11"
        if ticker not in candidatos or ref > candidatos[ticker][1]:
            candidatos[ticker] = (cnpj, ref)
    log(f"FIIs na CVM com ISIN de bolsa: {len(candidatos)}")

    y = Yahoo()
    cot = y.cotacoes([t + ".SA" for t in candidatos])
    hoje = datetime.now(BRASILIA).timestamp()
    linhas = []
    for ticker, (cnpj, ref) in sorted(candidatos.items()):
        q = cot.get(ticker + ".SA")
        if not q or not num(q.get("regularMarketPrice")):
            continue
        if hoje - (q.get("regularMarketTime") or 0) > 45 * 86400:
            continue  # sem negócios recentes
        preco = num(q["regularMarketPrice"])
        g = geral[cnpj][ref]
        meses = compl.get(cnpj, {})
        ult_mes = max(meses) if meses else None
        c = meses.get(ult_mes, {}) if ult_mes else {}
        vpc = num(c.get("Valor_Patrimonial_Cotas"))
        rend = []
        for d in sorted(meses)[-12:]:
            m = meses[d]
            dy_m, vp_m = num(m.get("Percentual_Dividend_Yield_Mes"), 8), num(m.get("Valor_Patrimonial_Cotas"))
            if dy_m is not None and vp_m and 0 <= dy_m < 0.2:
                rend.append(dy_m * vp_m)
        rend12 = round(sum(rend), 4) if rend else None
        ult = round(rend[-1], 4) if rend else None
        a = ativo.get(cnpj, {})
        a = a[max(a)] if a else {}
        total = num(a.get("Total_Investido")) or 0
        papel = round(em_papel(a) / total * 100, 1) if total > 0 else None
        imov = round(soma(a, IMOVEIS) / total * 100, 1) if total > 0 else None
        fof = round((num(a.get("FII")) or 0) / total * 100, 1) if total > 0 else None
        nome = (g.get("Nome_Fundo_Classe") or g.get("Nome_Fundo") or "").strip()
        seg = (g.get("Segmento_Atuacao") or "").strip() or "Outros"
        if fof is not None and fof >= 50:
            tipo = "Fundo de fundos"
        elif papel is not None and papel >= 50:
            tipo = "Papel"
        elif imov is not None and imov >= 50:
            tipo = "Tijolo"
        else:
            tipo = "Híbrido"
        tx = num(c.get("Percentual_Despesas_Taxa_Administracao"), 8)
        linhas.append({
            "t": ticker, "n": nome, "seg": seg, "tipo": tipo, "mand": (g.get("Mandato") or "").strip(),
            "gest": (g.get("Tipo_Gestao") or "").strip(), "adm": (g.get("Nome_Administrador") or "").strip(),
            "price": preco,
            "dy": round(rend12 / preco * 100, 2) if rend12 and preco else None,
            "pvp": round(preco / vpc, 3) if vpc and vpc > 0 else None,
            "vpc": vpc, "pl": num(c.get("Patrimonio_Liquido"), 0), "cot": num(c.get("Total_Numero_Cotistas"), 0),
            "liq": num((num(q.get("averageDailyVolume3Month")) or 0) * preco, 0),
            "ult": ult, "dym": round(ult / preco * 100, 2) if ult and preco else None, "rend12": rend12,
            "var12": mudanca_12m(q), "tx": round(tx * 12 * 100, 3) if tx is not None and tx < 0.01 else None,
            "papel": papel, "imoveis": imov, "fof": fof, "cnpj": cnpj, "ref": ult_mes or ref,
            "publico": (g.get("Publico_Alvo") or "").strip(),
        })
    if len(linhas) < 150:
        raise RuntimeError(f"só {len(linhas)} FIIs com cotação")
    salvar("fiis.json", tabela(CHAVES, linhas, fonte="Informe mensal da CVM e cotações do Yahoo Finance"))
    log(f"OK: {len(linhas)} FIIs")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FIIs falhou: {e}")
        sys.exit(1)
