"""Índice de busca do app com todos os ativos: dados/busca.json = [[código, nome, classe], ...]."""
import os

from comum import RAIZ, ler, log, salvar, agora


def linhas(arq, raiz=False):
    d = ler(os.path.join(RAIZ, arq) if raiz else arq, {}) or {}
    k = d.get("k") or []
    return [dict(zip(k, l)) for l in d.get("d") or []]


def main():
    out = []
    for l in linhas("acoes.json", raiz=True):
        out.append([l["t"], l.get("n") or "", "acao"])
    for l in linhas("fiis.json"):
        out.append([l["t"], l.get("n") or "", "fii"])
    for l in linhas("b3.json"):
        out.append([l["t"], l.get("n") or "", l.get("tipo", "ETF").lower()])
    for l in linhas("exterior.json"):
        out.append([l["t"], l.get("n") or "", "ext"])
    for l in linhas("etfs_exterior.json"):
        out.append([l["t"], l.get("n") or "", "etfx"])
    for l in linhas("fundos.json"):
        out.append([l["c"], l.get("n") or "", "fundo"])
    for l in linhas("tesouro.json"):
        out.append([f"{l['titulo']} {l['venc'][:4]}", l["titulo"], "tesouro"])
    salvar("busca.json", {"atualizado": agora(), "d": out})
    cont = {}
    for _, _, c in out:
        cont[c] = cont.get(c, 0) + 1
    log(f"OK: índice com {len(out)} ativos {cont}")


if __name__ == "__main__":
    main()
