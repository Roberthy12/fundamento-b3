#!/usr/bin/env python3
"""Atualiza acoes.json com os indicadores mais recentes.

Ordem das fontes:
1. Busca avançada do Status Invest: todos os indicadores. Costuma recusar
   os servidores do GitHub (HTTP 403).
2. Cotações do Yahoo Finance, sem cadastro: atualiza o preço de cada ação e
   recalcula P/L, P/VP, DY e os outros múltiplos de preço. Os demais
   indicadores continuam os da última coleta completa.
3. Se existir a variável BRAPI_TOKEN, faz o mesmo pela brapi.dev para as
   ações que o Yahoo não trouxe.
Se nada der certo, mantém o arquivo anterior e termina com código 1.

Só usa a biblioteca padrão do Python. Uso: python atualizar_dados.py
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.abspath(__file__))
ARQUIVO = os.path.join(RAIZ, "acoes.json")
BRASILIA = timezone(timedelta(hours=-3))

TEXTO = {"t": "ticker", "n": "companyname", "s": "sectorname", "ss": "subsectorname", "sg": "segmentname"}
NUMEROS = [
    "price", "dy", "p_l", "p_vp", "p_ebit", "p_ativo", "ev_ebit", "margembruta", "margemebit",
    "margemliquida", "p_sr", "p_capitalgiro", "p_ativocirculante", "giroativos", "roe", "roa", "roic",
    "dividaliquidapatrimonioliquido", "dividaliquidaebit", "pl_ativo", "passivo_ativo",
    "liquidezcorrente", "peg_ratio", "receitas_cagr5", "lucros_cagr5", "liquidezmediadiaria",
    "vpa", "lpa", "valormercado",
]
CHAVES = list(TEXTO) + NUMEROS
# Múltiplos que andam junto com o preço (sobem na mesma proporção).
MULTIPLOS_DE_PRECO = ("p_l", "p_vp", "p_ebit", "p_sr", "p_ativo", "p_capitalgiro",
                      "p_ativocirculante", "peg_ratio", "valormercado")
# Variação acima disso costuma ser desdobramento ou grupamento; não recalcula.
SALTO_MAXIMO = 0.5

NAVEGADOR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "pt-BR,pt;q=0.9",
}


def agora():
    return datetime.now(BRASILIA).replace(microsecond=0).isoformat()


def data_br(iso):
    return "/".join(reversed(iso[:10].split("-")))


def http_json(url, headers=None, tentativas=3):
    erro = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={**NAVEGADOR, **(headers or {})})
            with urllib.request.urlopen(req, timeout=40) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # rede, bloqueio ou JSON inválido
            erro = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"{url[:80]}… → {erro}")


# ---------- fonte completa: Status Invest ----------
def baixar_status_invest(por_pagina=50):
    busca = json.dumps({"Sector": "", "SubSector": "", "Segment": "", "my_range": "-20;100"}, separators=(",", ":"))
    extra = {"X-Requested-With": "XMLHttpRequest", "Referer": "https://statusinvest.com.br/acoes/busca-avancada"}
    itens, pagina, total = [], 0, None
    while True:
        q = urllib.parse.urlencode({"search": busca, "orderColumn": "ticker", "isAsc": "true",
                                    "page": pagina, "take": por_pagina, "CategoryType": 1})
        dados = http_json("https://statusinvest.com.br/category/advancedsearchresultpaginated?" + q, extra)
        lote = dados.get("list") or []
        total = dados.get("totalResults", total)
        itens.extend(lote)
        if not lote or (total and len(itens) >= total):
            break
        pagina += 1
        time.sleep(1.5)
    return itens


def numero(v):
    if v is None or v == "":
        return None
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def montar_linhas(itens):
    linhas, vistos = [], set()
    for o in itens:
        ticker = (o.get("ticker") or "").strip().upper()
        preco = numero(o.get("price"))
        if not ticker or ticker in vistos or not preco or preco <= 0:
            continue
        vistos.add(ticker)
        texto = [ticker] + [(o.get(TEXTO[k]) or "").strip() for k in ("n", "s", "ss", "sg")]
        linhas.append(texto + [numero(o.get(k)) for k in NUMEROS])
    linhas.sort(key=lambda l: l[0])
    return linhas


def validar(linhas):
    tickers = {l[0] for l in linhas}
    faltando = {"PETR4", "VALE3", "ITUB4"} - tickers
    if len(linhas) < 300 or faltando:
        raise ValueError(f"resposta incompleta: {len(linhas)} ações, faltando {sorted(faltando)}")


# ---------- só cotações: Yahoo Finance e brapi.dev ----------
def cotacao_yahoo(ticker):
    for host in ("query1", "query2"):
        try:
            r = http_json(f"https://{host}.finance.yahoo.com/v8/finance/chart/{ticker}.SA?range=1d&interval=1d",
                          tentativas=2)
            meta = r["chart"]["result"][0]["meta"]
            preco = float(meta["regularMarketPrice"])
            if meta.get("currency", "BRL") == "BRL" and preco > 0:
                return preco
        except Exception:
            continue
    return None


def cotacao_brapi(ticker, token):
    r = http_json(f"https://brapi.dev/api/quote/{ticker}?token={urllib.parse.quote(token)}", tentativas=2)
    return float(r["results"][0]["regularMarketPrice"])


def aplicar_preco(linha, i, novo):
    """Troca o preço e recalcula os múltiplos de preço. Devolve True se aplicou."""
    velho = linha[i["price"]]
    if not velho or not novo or novo <= 0:
        return False
    q = novo / velho
    if abs(q - 1) > SALTO_MAXIMO:
        print(f"  {linha[i['t']]}: variação de {q - 1:+.0%}, ignorada (possível desdobramento)", file=sys.stderr)
        return False
    p_ebit_velho = linha[i["p_ebit"]]
    for c in MULTIPLOS_DE_PRECO:
        if linha[i[c]] is not None:
            linha[i[c]] = round(linha[i[c]] * q, 4)
    if linha[i["dy"]]:
        linha[i["dy"]] = round(linha[i["dy"]] / q, 4)
    if linha[i["ev_ebit"]] is not None and p_ebit_velho is not None:
        linha[i["ev_ebit"]] = round(linha[i["ev_ebit"]] + p_ebit_velho * (q - 1), 4)
    linha[i["price"]] = round(novo, 4)
    return True


def atualizar_cotacoes(token=""):
    atual = ler()
    k = atual["k"]
    i = {c: k.index(c) for c in k}
    feitos, por_fonte = set(), {"Yahoo Finance": 0, "brapi.dev": 0}

    for l in atual["d"]:
        preco = cotacao_yahoo(l[i["t"]])
        if preco and aplicar_preco(l, i, preco):
            feitos.add(l[i["t"]])
            por_fonte["Yahoo Finance"] += 1
        time.sleep(0.25)

    if token:
        for l in atual["d"]:
            if l[i["t"]] in feitos or (l[i["liquidezmediadiaria"]] or 0) < 1_000_000:
                continue
            try:
                if aplicar_preco(l, i, cotacao_brapi(l[i["t"]], token)):
                    feitos.add(l[i["t"]])
                    por_fonte["brapi.dev"] += 1
            except Exception as e:
                print(f"  {l[i['t']]}: sem cotação na brapi ({e})", file=sys.stderr)
            time.sleep(0.4)  # plano gratuito: 1 requisição por vez

    if len(feitos) < 100:
        raise RuntimeError(f"só {len(feitos)} cotações atualizadas")
    base = atual.get("base_completa") or atual.get("atualizado", "")[:10]
    fontes = " e ".join(f for f, n in por_fonte.items() if n)
    atual.update(atualizado=agora(), base_completa=base,
                 fonte=f"cotações do {fontes}; demais indicadores do Status Invest de {data_br(base)}")
    salvar(atual)
    return por_fonte, len(atual["d"])


# ---------- arquivo ----------
def ler():
    with open(ARQUIVO, encoding="utf-8") as f:
        return json.load(f)


def salvar(dados):
    tmp = ARQUIVO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, ARQUIVO)


def main():
    try:
        linhas = montar_linhas(baixar_status_invest())
        validar(linhas)
        salvar({"atualizado": agora(), "fonte": "busca avançada do Status Invest", "k": CHAVES, "d": linhas})
        print(f"OK: {len(linhas)} ações atualizadas pelo Status Invest.")
        return 0
    except Exception as e:
        print(f"Status Invest indisponível: {e}", file=sys.stderr)

    try:
        por_fonte, total = atualizar_cotacoes(os.environ.get("BRAPI_TOKEN", "").strip())
        detalhe = ", ".join(f"{n} pelo {f}" for f, n in por_fonte.items() if n)
        print(f"OK: cotações atualizadas ({detalhe}) de {total} ações; demais indicadores mantidos.")
        return 0
    except Exception as e:
        print(f"Cotações também falharam: {e}", file=sys.stderr)
    print("Nada foi atualizado; o site continua com os dados anteriores.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
