"""Perfil das empresas da CVM: ano de fundação e número de empregados.

Fontes (dados abertos da CVM, sem cadastro):
- cad_cia_aberta.csv: cadastro das companhias (código CVM, situação, setor)
- Formulário de Referência (FRE), arquivo fre_cia_historico_emissor: data de constituição (item 6.1)
- Formulário de Referência (FRE), arquivos fre_cia_aberta_empregado_posicao_local: quantidade de
  empregados por cargo e local (item 10.1A). Somamos a última data de referência de cada empresa.

Os nomes das colunas são localizados pelo texto do cabeçalho, porque a CVM já os renomeou
ao longo dos anos. Quando um dado não é encontrado, fica de fora (o app mostra "não informado").

Saída: dados/perfil.json -> {"atualizado": ..., "cias": {"<codigo CVM>": {"fundacao": 1990, "empregados": 1234, "emp_ref": "2025-12-31"}}}
"""
import csv
import io
import re
import zipfile
from datetime import date

from comum import agora, baixar, log, salvar, texto

ANO = date.today().year
FRE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FRE/DADOS/fre_cia_aberta_{}.zip"
CAD = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"


def _csv(conteudo):
    return list(csv.DictReader(io.StringIO(texto(conteudo)), delimiter=";"))


def _coluna(cabecalho, *palavras):
    """Primeira coluna cujo nome contém todas as palavras (sem diferenciar maiúsculas e acentos)."""
    norm = lambda s: re.sub(r"[^a-z]", "", s.lower().replace("ç", "c").replace("ã", "a").replace("ê", "e"))
    for c in cabecalho:
        n = norm(c)
        if all(norm(p) in n for p in palavras):
            return c
    return None


def _ano(valor):
    m = re.search(r"(1[89]|20)\d{2}", valor or "")
    return int(m.group(0)) if m else None


def cadastro():
    """{codigo CVM: nome} das companhias em situação ativa."""
    cias = {}
    for l in _csv(baixar(CAD, timeout=120)):
        if (l.get("SIT") or "").upper() != "ATIVO":
            continue
        cod = (l.get("CD_CVM") or "").lstrip("0")
        if cod:
            cias[cod] = l.get("DENOM_SOCIAL", "")
    log(f"  cadastro CVM: {len(cias)} companhias ativas")
    return cias


def fre(ano):
    """Arquivos do FRE de um ano: {nome: linhas}. Vazio se o pacote ainda não existe."""
    try:
        z = zipfile.ZipFile(io.BytesIO(baixar(FRE.format(ano), timeout=600)))
    except Exception as ex:
        log(f"  FRE {ano}: {ex}")
        return {}
    arquivos = {}
    for n in z.namelist():
        if n.lower().endswith(".csv") and ("historico_emissor" in n or "empregado_posicao_local" in n):
            arquivos[n] = _csv(z.read(n))
    log(f"  FRE {ano}: {sorted(arquivos)}")
    return arquivos


def fundacoes(arquivos):
    out = {}
    for nome, linhas in arquivos.items():
        if "historico_emissor" not in nome or not linhas:
            continue
        cab = linhas[0].keys()
        cod = _coluna(cab, "codigo", "cvm") or _coluna(cab, "cvm")
        dt = _coluna(cab, "constitu")
        if not (cod and dt):
            log(f"  fundação: colunas não encontradas em {nome}")
            continue
        for l in linhas:
            ano = _ano(l.get(dt))
            k = (l.get(cod) or "").lstrip("0")
            if k and ano:
                out[k] = ano
    return out


def empregados(arquivos):
    """Soma dos empregados na data de referência mais recente de cada companhia."""
    melhor = {}  # cod -> (data, total)
    for nome, linhas in arquivos.items():
        if "empregado_posicao_local" not in nome or not linhas:
            continue
        cab = linhas[0].keys()
        cod = _coluna(cab, "codigo", "cvm") or _coluna(cab, "cvm")
        ref = _coluna(cab, "data", "referencia")
        qtd = _coluna(cab, "quant")
        if not (cod and ref and qtd):
            log(f"  empregados: colunas não encontradas em {nome}")
            continue
        por_data = {}
        for l in linhas:
            k = (l.get(cod) or "").lstrip("0")
            d = l.get(ref) or ""
            try:
                n = int(float((l.get(qtd) or "").replace(",", ".")))
            except ValueError:
                continue
            por_data.setdefault(k, {}).setdefault(d, 0)
            por_data[k][d] += n
        for k, datas in por_data.items():
            d = max(datas)
            if k not in melhor or d > melhor[k][0]:
                melhor[k] = (d, datas[d])
    return {k: {"empregados": v[1], "emp_ref": v[0]} for k, v in melhor.items()}


def main():
    cias = cadastro()
    arquivos = {}
    for ano in (ANO, ANO - 1):  # o pacote do ano corrente sai no início do ano seguinte
        arquivos.update(fre(ano))
        if arquivos:
            break
    fund = fundacoes(arquivos)
    emp = empregados(arquivos)
    saida = {}
    for cod in cias:
        p = {}
        if cod in fund:
            p["fundacao"] = fund[cod]
        if cod in emp:
            p.update(emp[cod])
        if p:
            saida[cod] = p
    log(f"perfil: {len(saida)} companhias ({sum('fundacao' in v for v in saida.values())} com fundação, "
        f"{sum('empregados' in v for v in saida.values())} com empregados)")
    salvar("perfil.json", {"atualizado": agora(), "cias": saida})


if __name__ == "__main__":
    main()
