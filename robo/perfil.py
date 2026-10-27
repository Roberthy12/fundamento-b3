"""Perfil das empresas da CVM: ano de fundação e número de empregados.

Fontes (dados abertos da CVM, sem cadastro):
- cad_cia_aberta.csv: cadastro das companhias (CNPJ, código CVM, situação)
- Formulário de Referência (FRE), arquivo fre_cia_historico_emissor: data de constituição (item 6.1)
- Formulário de Referência (FRE), arquivos fre_cia_aberta_empregado_posicao_local: quantidade de
  empregados por cargo e local (item 10.1A). Somamos a última data de referência de cada empresa.

As companhias são ligadas pelo código CVM quando o arquivo traz essa coluna, ou pelo CNPJ quando não traz.
Os nomes das colunas são localizados pelo texto do cabeçalho, porque a CVM já os renomeou ao longo
dos anos. Quando um dado não é encontrado, fica de fora (o app mostra "não informado").

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


def _norm(s):
    return re.sub(r"[^a-z]", "", s.lower().replace("ç", "c").replace("ã", "a").replace("ê", "e"))


def _coluna(cabecalho, *palavras):
    """Primeira coluna cujo nome contém todas as palavras (sem diferenciar maiúsculas e acentos)."""
    for c in cabecalho:
        n = _norm(c)
        if all(_norm(p) in n for p in palavras):
            return c
    return None


def _so_digitos(v):
    return re.sub(r"\D", "", v or "")


def _ano(valor):
    m = re.search(r"(1[89]|20)\d{2}", valor or "")
    return int(m.group(0)) if m else None


def cadastro():
    """(nomes {codigo CVM: nome}, codigo por CNPJ {cnpj: codigo CVM}) das companhias ativas."""
    nomes, por_cnpj = {}, {}
    for l in _csv(baixar(CAD, timeout=120)):
        if (l.get("SIT") or "").upper() != "ATIVO":
            continue
        cod = (l.get("CD_CVM") or "").lstrip("0")
        if not cod:
            continue
        nomes[cod] = l.get("DENOM_SOCIAL", "")
        por_cnpj[_so_digitos(l.get("CNPJ_CIA"))] = cod
    log(f"  cadastro CVM: {len(nomes)} companhias ativas")
    return nomes, por_cnpj


def fre(ano):
    """Arquivos do FRE de um ano: {nome: (cabecalho, linhas)}. Vazio se o pacote não existe."""
    try:
        z = zipfile.ZipFile(io.BytesIO(baixar(FRE.format(ano), timeout=600)))
    except Exception as ex:
        log(f"  FRE {ano}: {ex}")
        return {}
    arquivos = {}
    for n in z.namelist():
        if not n.lower().endswith(".csv"):
            continue
        if "historico_emissor" in n or "empregado_posicao_local" in n:
            linhas = _csv(z.read(n))
            arquivos[n] = (list(linhas[0].keys()) if linhas else [], linhas)
    log(f"  FRE {ano}: {len(arquivos)} arquivos de interesse")
    for n, (cab, _) in arquivos.items():
        log(f"    {n}: colunas {cab[:14]}")
    return arquivos


def _codigo(l, cab, por_cnpj):
    """Código CVM da linha: pela coluna de código, ou pelo CNPJ quando o arquivo não tem o código."""
    col = _coluna(cab, "codigo", "cvm") or _coluna(cab, "cvm")
    if col:
        return (l.get(col) or "").lstrip("0")
    col = _coluna(cab, "cnpj")
    if col:
        return por_cnpj.get(_so_digitos(l.get(col)), "")
    return ""


def fundacoes(arquivos, por_cnpj):
    out = {}
    for nome, (cab, linhas) in arquivos.items():
        if "historico_emissor" not in nome:
            continue
        dt = _coluna(cab, "constitu")
        if not dt:
            log(f"  fundação: coluna de constituição não encontrada em {nome}")
            continue
        for l in linhas:
            ano = _ano(l.get(dt))
            k = _codigo(l, cab, por_cnpj)
            if k and ano:
                out[k] = ano
    return out


def empregados(arquivos, por_cnpj):
    """Soma dos empregados (todas as regiões) na data de referência mais recente de cada companhia, até hoje."""
    hoje = date.today().isoformat()
    melhor = {}  # cod -> (data, total)
    posicoes = set()
    for nome, (cab, linhas) in arquivos.items():
        if "empregado_posicao_local" not in nome:
            continue
        ref = _coluna(cab, "data", "referencia")
        qtds = [c for c in cab if c.lower().startswith("quantidade")]
        pos = _coluna(cab, "posicao")
        if not (ref and qtds):
            log(f"  empregados: colunas de data ou quantidade não encontradas em {nome}")
            continue
        por_data = {}
        for l in linhas:
            if pos:
                posicoes.add((l.get(pos) or "").strip())
            k = _codigo(l, cab, por_cnpj)
            d = (l.get(ref) or "")[:10]
            if not k or not d or d > hoje:
                continue
            total = 0
            for c in qtds:
                try:
                    total += int(float((l.get(c) or "0").replace(",", ".")))
                except ValueError:
                    pass
            por_data.setdefault(k, {}).setdefault(d, 0)
            por_data[k][d] += total
        for k, datas in por_data.items():
            d = max(datas)
            if k not in melhor or d > melhor[k][0]:
                melhor[k] = (d, datas[d])
    log(f"  posições encontradas: {sorted(posicoes)[:20]}")
    return {k: {"empregados": v[1], "emp_ref": v[0]} for k, v in melhor.items()}


FCA = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{}.zip"


def fca(ano):
    """Formulário cadastral (FCA): data de constituição e descrição da atividade de cada companhia."""
    try:
        z = zipfile.ZipFile(io.BytesIO(baixar(FCA.format(ano), timeout=600)))
    except Exception as ex:
        log(f"  FCA {ano}: {ex}")
        return {}, {}
    nome = next((n for n in z.namelist() if "_geral_" in n and n.lower().endswith(".csv")), None)
    if not nome:
        return {}, {}
    linhas = _csv(z.read(nome))
    cab = list(linhas[0].keys()) if linhas else []
    dt, at = _coluna(cab, "constitu"), _coluna(cab, "descricao", "atividade")
    log(f"  FCA {ano}: {len(linhas)} linhas; constituição='{dt}', atividade='{at}'")
    fund, ativ = {}, {}
    for l in linhas:
        cod = (l.get("Codigo_CVM") or "").lstrip("0") or _codigo(l, cab, {})
        if not cod:
            continue
        if dt and _ano(l.get(dt)):
            fund[cod] = _ano(l.get(dt))
        if at and (l.get(at) or "").strip():
            ativ[cod] = (l.get(at) or "").strip()
    return fund, ativ


def main():
    nomes, por_cnpj = cadastro()
    arquivos = {}
    for ano in (ANO, ANO - 1):  # o pacote de um ano pode não ter todos os arquivos
        arquivos.update(fre(ano))
    fund = fundacoes(arquivos, por_cnpj)
    emp = empregados(arquivos, por_cnpj)
    # a data de constituição e a atividade estão no FCA (mais completo que o FRE); o FRE, quando traz, prevalece
    fca_fund, fca_ativ = {}, {}
    for ano in (ANO, ANO - 1):
        f_, a_ = fca(ano)
        fca_fund.update({k: v for k, v in f_.items() if k not in fca_fund})
        fca_ativ.update({k: v for k, v in a_.items() if k not in fca_ativ})
    saida = {}
    for cod in nomes:
        p = {}
        fu = fund.get(cod) or fca_fund.get(cod)
        if fu:
            p["fundacao"] = fu
        if cod in emp:
            p.update(emp[cod])
        if cod in fca_ativ:
            p["atividade"] = fca_ativ[cod]
        if p:
            saida[cod] = p
    log(f"perfil: {len(saida)} companhias ({sum('fundacao' in v for v in saida.values())} com fundação, "
        f"{sum('empregados' in v for v in saida.values())} com empregados, "
        f"{sum('atividade' in v for v in saida.values())} com atividade)")
    salvar("perfil.json", {"atualizado": agora(), "cias": saida})


if __name__ == "__main__":
    main()
