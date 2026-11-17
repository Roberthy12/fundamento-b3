"""Compara a lista publicada com a nova e avisa quem sumiu (mudança de código de BDR, cadastro da CVM etc.).
Só informa: não altera nada. Roda antes de publicar."""
import json
import os
import urllib.request

SITE = os.environ.get("SITE", "").rstrip("/")


def codigos(j):
    k = j.get("k") or []
    i = k.index("t") if "t" in k else None
    return {r[i] for r in j.get("d") or []} if i is not None else set()


def main():
    if not SITE or not os.path.exists("acoes.json"):
        print("sem SITE ou acoes.json: nada a conferir")
        return
    with urllib.request.urlopen(urllib.request.Request(SITE + "/acoes.json", headers={"User-Agent": "Fundamento-B3"}), timeout=60) as r:
        antigo = codigos(json.loads(r.read()))
    with open("acoes.json", encoding="utf-8") as fh:
        novo = codigos(json.load(fh))
    sumiram, entraram = sorted(antigo - novo), sorted(novo - antigo)
    print(f"publicado: {len(antigo)} códigos; novo: {len(novo)}")
    print(f"SUMIRAM ({len(sumiram)}): {', '.join(sumiram) or '-'}")
    print(f"ENTRARAM ({len(entraram)}): {', '.join(entraram) or '-'}")


if __name__ == "__main__":
    main()
