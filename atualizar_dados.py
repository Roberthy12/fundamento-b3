#!/usr/bin/env python3
"""Atualiza acoes.json com os indicadores mais recentes.

1. Tenta baixar a busca avançada do Status Invest (todos os indicadores).
2. Se falhar e existir a variável BRAPI_TOKEN, atualiza só as cotações das
   ações mais líquidas pela brapi.dev e recalcula P/L, P/VP, DY e afins.
3. Se nada der certo, mantém o arquivo anterior e termina com código 1.

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

NAVEGADOR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "pt-BR,pt;q=0.9",
}


def agora():
    return datetime.now(BRASILIA).replace(microsecond=0).isoformat()


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


# ---------- fonte principal: Status Invest ----------
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


# ---------- plano B: cotações pela brapi.dev ----------
def plano_b_brapi(token, liquidez_minima=1_000_000):
    atual = ler()
    k = atual["k"]
    i = {c: k.index(c) for c in k}
    alvo = [l for l in atual["d"] if (l[i["liquidezmediadiaria"]] or 0) >= liquidez_minima]
    mudou = 0
    for l in alvo:
        try:
            r = http_json(f"https://brapi.dev/api/quote/{l[i['t']]}?token={urllib.parse.quote(token)}", tentativas=2)
            novo = float(r["results"][0]["regularMarketPrice"])
        except Exception as e:
            print(f"  {l[i['t']]}: sem cotação ({e})", file=sys.stderr)
            continue
        velho = l[i["price"]]
        if not velho or novo <= 0:
            continue
        q = novo / velho
        p_ebit_velho = l[i["p_ebit"]]
        for c in ("p_l", "p_vp", "p_ebit", "p_sr", "p_ativo", "p_capitalgiro", "p_ativocirculante", "peg_ratio", "valormercado"):
            if l[i[c]] is not None:
                l[i[c]] = round(l[i[c]] * q, 4)
        if l[i["dy"]]:
            l[i["dy"]] = round(l[i["dy"]] / q, 4)
        if l[i["ev_ebit"]] is not None and p_ebit_velho is not None:
            l[i["ev_ebit"]] = round(l[i["ev_ebit"]] + p_ebit_velho * (q - 1), 4)
        l[i["price"]] = round(novo, 4)
        mudou += 1
        time.sleep(0.4)  # plano gratuito: 1 requisição por vez
    if mudou == 0:
        raise RuntimeError("nenhuma cotação atualizada")
    base = atual.get("base_completa") or atual.get("atualizado", "")[:10]
    atual.update(atualizado=agora(), base_completa=base,
                 fonte=f"cotações da brapi.dev; demais indicadores do Status Invest de {'/'.join(reversed(base.split('-')))}")
    salvar(atual)
    return mudou


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

    token = os.environ.get("BRAPI_TOKEN", "").strip()
    if token:
        try:
            n = plano_b_brapi(token)
            print(f"OK (plano B): cotações de {n} ações atualizadas pela brapi.dev.")
            return 0
        except Exception as e:
            print(f"brapi.dev também falhou: {e}", file=sys.stderr)
    print("Nada foi atualizado; o site continua com os dados anteriores.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
