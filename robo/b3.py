"""Outros ativos da B3: ETFs, BDRs, Fiagros e FI-Infra (lista e cotações do Yahoo Finance).

Os ETFs ganham dados de fundo da CVM (cadastro e informe diário), casados pelo nome da classe:
gestor, administrador, patrimônio, cotistas, rentabilidade 1 mês, no ano, 12 meses e CDI.
Usa acoes.json e dados/fiis.json para não repetir ações e FIIs. Grava dados/b3.json.
"""
import io
import os
import re
import sys
import unicodedata
import zipfile
from datetime import date, datetime, timedelta

from comum import BRASILIA, RAIZ, Yahoo, baixar, csv_linhas, dy_yahoo, eq, ler, log, mudanca_12m, num, salvar, tabela, texto
import csv as _csv

STATUS_CVM = []  # o que aconteceu em cada mês do informe diário; vai para o b3.json
from fundos import CAD, DIARIO, cdi_acumulado, cota_em, digitos, fmt_cnpj

CHAVES = ["t", "n", "tipo", "price", "var12", "liq", "dy", "pl", "pvp", "mcap", "cur",
          "cnpj", "gest", "adm", "patr", "cotst", "cls", "anb", "trib", "r1m", "rano", "r12", "cdi12", "sub"]
ETF = re.compile(r"\bETF\b|ÍNDICE|INDICE|ISHARES|IT NOW|\bTREND\b|HASHDEX|INVESTO|\bCI\b|INDEX|S&P|NASDAQ|IBOV|SMALL CAP|CRIPTO|BITCOIN|GOLD|OURO", re.I)
# palavras que só descrevem o tipo do fundo; não ajudam a identificar a classe
SOBRA = {"FUNDO", "DE", "INDICE", "CLASSE", "UNICA", "RESPONSABILIDADE", "LIMITADA", "ETF", "FI", "DO", "DA", "E", "EM", "S", "A"}


def tipo_de(ticker, nome, q):
    nome_u = nome.upper()
    # o tipo que o Yahoo informa tem prioridade sobre o padrão do código (um ETF pode terminar em 39)
    if q.get("quoteType") == "ETF":
        return "ETF"
    if re.fullmatch(r"[A-Z0-9]{4}3[1-9]", ticker):
        return "BDR"
    if "FIAGRO" in nome_u or re.search(r"\bAGRO", nome_u):
        return "Fiagro"
    if "INFRA" in nome_u and not ETF.search(nome_u.replace("INFRA", "")):
        return "FI-Infra"
    if ticker.endswith("11") and ETF.search(nome_u):
        return "ETF"
    if ticker.endswith("11") and ("IMOBILI" in nome_u or " FII" in nome_u):
        return None  # FII fora do informe da CVM; fica de fora
    return None


def tokens(nome):
    s = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().upper()
    return [p for p in re.split(r"[^A-Z0-9]+", s) if p]


def classes_cvm():
    """Todas as classes de fundo em funcionamento na CVM, com gestor e administrador."""
    z = zipfile.ZipFile(io.BytesIO(baixar(CAD, timeout=180)))
    arq = {n.split("/")[-1]: n for n in z.namelist()}
    classes = csv_linhas(z.read(arq["registro_classe.csv"]))
    fundos = {l["ID_Registro_Fundo"]: l for l in csv_linhas(z.read(arq["registro_fundo.csv"]))}
    saida = []
    for c in classes:
        if c.get("Situacao") != "Em Funcionamento Normal":
            continue
        f = fundos.get(c.get("ID_Registro_Fundo"), {})
        saida.append({
            "cnpj": digitos(c.get("CNPJ_Classe")), "nome": (c.get("Denominacao_Social") or "").strip(),
            "patr": num(c.get("Patrimonio_Liquido"), 2), "cls": c.get("Classificacao") or "",
            "anb": c.get("Classificacao_Anbima") or "", "trib": c.get("Tributacao_Longo_Prazo") or "",
            "gest": (f.get("Gestor") or "").strip(), "adm": (f.get("Administrador") or "").strip(),
        })
    log(f"CVM: {len(saida)} classes em funcionamento")
    return saida


def casar(etfs, classes):
    """{ticker: classe}. Primeiro pelo nome igual; depois, pelo nome da B3 contido no da CVM."""
    por_nome = {}
    for c in classes:
        por_nome.setdefault(" ".join(tokens(c["nome"])), []).append(c)
    casados, sem = {}, []
    for e in etfs:
        t_b3 = tokens(e["n"])
        exato = por_nome.get(" ".join(t_b3))
        if exato:
            casados[e["t"]] = max(exato, key=lambda c: c["patr"] or 0)
            continue
        base = {x for x in t_b3 if x not in SOBRA}
        if len(base) < 2:
            sem.append(e["t"])
            continue
        # só nomes que trazem no máximo 2 palavras a mais (evita casar com outro fundo da mesma família)
        cand = [c for c in classes if base <= {x for x in tokens(c["nome"]) if x not in SOBRA}
                and len({x for x in tokens(c["nome"]) if x not in SOBRA} - base) <= 2]
        if not cand:
            sem.append(e["t"])
            continue
        # o nome da CVM pode trazer só a palavra a mais; fica com a classe de maior patrimônio
        casados[e["t"]] = max(cand, key=lambda c: c["patr"] or 0)
    log(f"ETFs casados com a CVM: {len(casados)} de {len(etfs)}; sem par: {len(sem)}"
        + (f" ({', '.join(sem[:30])})" if sem else ""))
    return casados


def cotas_do_mes(mes, alvo):
    """{cnpj: [(data, cota, pl, cotistas)]} de um mês do informe diário; registra o status."""
    url = DIARIO.format(mes)
    try:
        bruto = baixar(url, timeout=900, tentativas=2)
    except Exception as e:
        STATUS_CVM.append(f"{mes:%Y-%m}: download falhou ({str(e)[:160]})")
        log(f"  informe diário {mes:%Y-%m}: {e}")
        return None
    try:
        z = zipfile.ZipFile(io.BytesIO(bruto))
        por = {}
        for n in z.namelist():
            for l in _csv.DictReader(io.StringIO(texto(z.read(n))), delimiter=";"):
                c = digitos(l.get("CNPJ_FUNDO_CLASSE") or l.get("CNPJ_FUNDO"))
                if c not in alvo:
                    continue
                q = num(l.get("VL_QUOTA"), 10)
                if q and q > 0:
                    por.setdefault(c, {}).setdefault(l.get("ID_SUBCLASSE") or "", []).append(
                        (l["DT_COMPTC"], q, num(l.get("VL_PATRIM_LIQ"), 2), num(l.get("NR_COTST"), 0)))
    except Exception as e:
        STATUS_CVM.append(f"{mes:%Y-%m}: leitura falhou ({str(e)[:160]})")
        log(f"  informe diário {mes:%Y-%m}: leitura falhou: {e}")
        return None
    out = {c: sorted(subs[min(subs)]) for c, subs in por.items()}
    STATUS_CVM.append(f"{mes:%Y-%m}: {len(bruto) // 1024 // 1024} MB, {len(out)} ETFs com cota")
    log(f"  informe diário {mes:%Y-%m}: {len(out)} ETFs")
    return out


def dados_cvm(casados):
    """Rentabilidade e patrimônio pelo informe diário das classes casadas."""
    alvo = {c["cnpj"]: c for c in casados.values()}
    hoje = datetime.now(BRASILIA).date()
    mes = hoje.replace(day=1)
    atual = cotas_do_mes(mes, alvo)
    if not atual or len(atual) < len(alvo) * 0.5:
        mes = (mes - timedelta(days=1)).replace(day=1)
        atual = cotas_do_mes(mes, alvo) or {}
    if not atual:
        log("informe diário da CVM indisponível: ETFs sem dados de fundo")
        return {}
    ultima = max(s[-1][0] for s in atual.values())
    d_ult = date.fromisoformat(ultima)
    alvos = {"r1m": d_ult - timedelta(days=30), "rano": date(d_ult.year - 1, 12, 31), "r12": d_ult - timedelta(days=365)}
    meses = {mes: atual}
    for d in alvos.values():
        m = d.replace(day=1)
        if m not in meses:
            meses[m] = cotas_do_mes(m, alvo) or {}
    cdi12 = cdi_acumulado(alvos["r12"], d_ult)
    out = {}
    for c, info in alvo.items():
        serie = atual.get(c)
        if not serie:
            continue
        dt, cota, cotst = serie[-1][0], serie[-1][1], serie[-1][3]
        if dt < (d_ult - timedelta(days=10)).isoformat():
            continue  # classe parou de informar
        l = {"dt": dt, "cotst": cotst}
        for k, d in alvos.items():
            m = d.replace(day=1)
            ref = cota_em([meses.get(m, {}).get(c, []), meses.get((m - timedelta(days=1)).replace(day=1), {}).get(c, [])],
                          d.isoformat())
            v = round((cota / ref[1] - 1) * 100, 2) if ref and ref[1] else None
            l[k] = v if v is not None and abs(v) <= 500 else None
        l["cdi12"] = round(cdi12 * 100, 2) if cdi12 else None
        out[c] = l
    log(f"ETFs com informe diário recente: {len(out)} de {len(alvo)}")
    return out


def main():
    acoes = ler(os.path.join(RAIZ, "acoes.json"), {})
    ja = {l[0] for l in acoes.get("d", [])}
    ja |= {l[0] for l in (ler("fiis.json", {}) or {}).get("d", [])}
    y = Yahoo()
    lista = y.tela(eq("region", "br"), maximo=4000)
    log(f"Yahoo B3: {len(lista)} ativos")
    linhas, vistos, descartados = [], set(), []
    for q in lista:
        s = q.get("symbol", "")
        if not s.endswith(".SA"):
            continue
        t = s[:-3]
        if t in ja or t in vistos or not num(q.get("regularMarketPrice")):
            continue
        nome = (q.get("longName") or q.get("shortName") or "").strip()
        tipo = tipo_de(t, nome, q)
        if not tipo:
            if q.get("quoteType") == "ETF" or ETF.search(nome):
                descartados.append(f"{t} ({q.get('quoteType')}, {nome[:50]})")
            continue
        vistos.add(t)
        preco = num(q.get("regularMarketPrice"))
        m = re.fullmatch(r"([A-Z]{3,5})\d{2}", t) if tipo == "BDR" else None
        linhas.append({
            "t": t, "n": nome, "tipo": tipo, "price": preco, "var12": mudanca_12m(q),
            "liq": num((num(q.get("averageDailyVolume3Month")) or 0) * preco, 0),
            "dy": dy_yahoo(q), "pl": num(q.get("trailingPE"), 2), "pvp": num(q.get("priceToBook"), 2),
            "mcap": num(q.get("marketCap"), 0), "cur": q.get("currency"),
            "sub": m.group(1) if m else None,
        })
    contagem = {}
    for l in linhas:
        contagem[l["tipo"]] = contagem.get(l["tipo"], 0) + 1
    if len(linhas) < 100:
        raise RuntimeError(f"só {len(linhas)} ativos")
    if descartados:
        log(f"Descartados (parecem ETF ou fundo e ficaram sem tipo): {len(descartados)}: " + "; ".join(descartados[:40]))
    # dados de fundo da CVM para os ETFs (uma falha aqui não derruba a lista da B3)
    try:
        etfs = [l for l in linhas if l["tipo"] == "ETF"]
        casados = casar(etfs, classes_cvm())
        fundo = dados_cvm(casados)
        for l in etfs:
            c = casados.get(l["t"])
            if not c:
                continue
            l.update({"cnpj": fmt_cnpj(c["cnpj"]), "gest": c["gest"], "adm": c["adm"], "patr": c["patr"],
                      "cls": c["cls"], "anb": c["anb"], "trib": c["trib"]})
            if c["cnpj"] in fundo:
                l.update({k: v for k, v in fundo[c["cnpj"]].items()})
    except Exception as e:
        log(f"dados de fundo da CVM para ETFs falharam: {e}")
    for l in linhas:
        for k in CHAVES:
            l.setdefault(k, None)
    linhas.sort(key=lambda l: (l["tipo"], -(l["liq"] or 0)))
    salvar("b3.json", tabela(CHAVES, linhas, fonte="Yahoo Finance e dados abertos da CVM (ETFs)", cvm_status=STATUS_CVM))
    log(f"OK: {contagem}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"B3 (ETFs/BDRs) falhou: {e}")
        sys.exit(1)
