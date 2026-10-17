"""Outros ativos da B3: ETFs, BDRs, Fiagros e FI-Infra (lista e cotações do Yahoo Finance).

Usa acoes.json e dados/fiis.json para não repetir ações e FIIs. Grava dados/b3.json.
"""
import os
import re
import sys

from comum import RAIZ, Yahoo, dy_yahoo, eq, ler, log, mudanca_12m, num, salvar, tabela

CHAVES = ["t", "n", "tipo", "price", "var12", "liq", "dy", "pl", "pvp", "mcap", "cur"]
ETF = re.compile(r"\bETF\b|ÍNDICE|INDICE|ISHARES|IT NOW|\bTREND\b|HASHDEX|INVESTO|\bCI\b|INDEX|S&P|NASDAQ|IBOV|SMALL CAP|CRIPTO|BITCOIN|GOLD|OURO", re.I)


def tipo_de(ticker, nome, q):
    nome_u = nome.upper()
    if re.fullmatch(r"[A-Z0-9]{4}3[1-9]", ticker):
        return "BDR"
    if q.get("quoteType") == "ETF":
        return "ETF"
    if "FIAGRO" in nome_u or re.search(r"\bAGRO", nome_u):
        return "Fiagro"
    if "INFRA" in nome_u and not ETF.search(nome_u.replace("INFRA", "")):
        return "FI-Infra"
    if ticker.endswith("11") and ETF.search(nome_u):
        return "ETF"
    if ticker.endswith("11") and ("IMOBILI" in nome_u or " FII" in nome_u):
        return None  # FII fora do informe da CVM; fica de fora
    return None


def main():
    acoes = ler(os.path.join(RAIZ, "acoes.json"), {})
    ja = {l[0] for l in acoes.get("d", [])}
    ja |= {l[0] for l in (ler("fiis.json", {}) or {}).get("d", [])}
    y = Yahoo()
    lista = y.tela(eq("region", "br"), maximo=4000)
    log(f"Yahoo B3: {len(lista)} ativos")
    linhas, vistos = [], set()
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
            continue
        vistos.add(t)
        preco = num(q.get("regularMarketPrice"))
        linhas.append({
            "t": t, "n": nome, "tipo": tipo, "price": preco, "var12": mudanca_12m(q),
            "liq": num((num(q.get("averageDailyVolume3Month")) or 0) * preco, 0),
            "dy": dy_yahoo(q), "pl": num(q.get("trailingPE"), 2), "pvp": num(q.get("priceToBook"), 2),
            "mcap": num(q.get("marketCap"), 0), "cur": q.get("currency"),
        })
    contagem = {}
    for l in linhas:
        contagem[l["tipo"]] = contagem.get(l["tipo"], 0) + 1
    if len(linhas) < 100:
        raise RuntimeError(f"só {len(linhas)} ativos")
    linhas.sort(key=lambda l: (l["tipo"], -(l["liq"] or 0)))
    salvar("b3.json", tabela(CHAVES, linhas, fonte="Yahoo Finance"))
    log(f"OK: {contagem}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"B3 (ETFs/BDRs) falhou: {e}")
        sys.exit(1)
