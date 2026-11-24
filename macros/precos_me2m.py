"""Preço do pedido de compra mais recente de cada part number, lido direto da ME2M.

A lista da ME2M é lida na tela do SAP, sem exportar para planilha. Os preços são
divididos pela unidade de preço (preço por 100 vira preço por 1) e, no fim, vão
para a área de transferência na mesma ordem da lista colada, para colar de volta
no Excel ou no Google Sheets.
"""
import re

from src.sap import ErroSap

COMANDO = "precos"
TITULO = "Preços ME2M"
DESCRICAO = "Preço do pedido de compra mais recente de cada part number (ME2M)"
ROTULO = "part numbers"
LINHAS = True  # uma linha colada = um item, para os preços voltarem alinhados

CAMPO_MATERIAL = "wnd[0]/usr/ctxtEM_MATNR-LOW"

# Colunas procuradas na lista: primeiro pelo nome técnico, depois pelo título na tela.
COLUNAS = {
    "data": (("BEDAT",), ("data doc.", "data documento", "data do documento")),
    "preco": (("NETPR",), ("preço líq.", "preço líquido", "preço liq.")),
    "por": (("PEINH",), ("unidade preço", "unid.preço", "unidade de preço")),
    "moeda": (("WAERS",), ("moeda",)),
    "documento": (("EBELN",), ("documento compras", "documento de compras", "doc.compra")),
    "item": (("EBELP",), ("item",)),
}
OBRIGATORIAS = ("data", "preco", "por")


def inicio(sap):
    """Abre a ME2M numa janela nova do SAP, para não mexer na janela em que você está."""
    return sap.nova_janela("me2m")


def fim(sap):
    """Fecha a janela nova, mesmo se algum item falhar ou se a execução for cancelada."""
    sap.fechar()


def por_item(sap, material):
    sap.texto("wnd[0]/tbar[0]/okcd", "/nme2m")
    sap.tecla("wnd[0]", 0)
    sap.texto(CAMPO_MATERIAL, material)
    sap.tecla("wnd[0]", 8)  # Executar (F8)

    grade = sap.grade()
    if grade is None:
        _, texto = sap.status()
        raise ErroSap(texto or "nenhum pedido de compra encontrado")

    colunas = _localizar_colunas(grade.colunas())
    candidatos = []
    for ordem, linha in enumerate(grade.valores(list(colunas.values()))):
        data = data_iso(linha[colunas["data"]])
        preco = numero(linha[colunas["preco"]])
        por = numero(linha[colunas["por"]]) or 1
        if not data or not preco or preco <= 0:
            continue  # linhas de subtotal e itens sem preço (grátis) ficam de fora
        documento = linha.get(colunas.get("documento"), "")
        candidatos.append((data, documento, ordem, preco, por, linha.get(colunas.get("moeda"), "")))
    if not candidatos:
        raise ErroSap("nenhum pedido com preço na ME2M")

    data, documento, _, preco, por, moeda = max(candidatos)  # o mais recente
    return Preco(preco, por, moeda, documento, data)


def concluir(linhas, resultados):
    """Copia os preços unitários, um por linha e na ordem da lista, para colar ao
    lado dos part numbers. Linhas sem preço ficam em branco."""
    from src import area_de_transferencia

    valores = [resultados[pn].unitario_texto() if resultados.get(pn) else "" for pn in linhas]
    if area_de_transferencia.copiar("\n".join(valores)):
        return ["Preços copiados (%d linhas): cole na coluna ao lado dos part numbers com Ctrl+V." % len(valores),
                "Linhas sem preço ficam em branco."]
    # Sem área de transferência: mostra a coluna na tela, para copiar à mão.
    return ["Não foi possível copiar automaticamente. Preços na ordem da lista:"] + [valor or "-" for valor in valores]


class Preco:
    def __init__(self, preco, por, moeda, documento, data):
        self.preco, self.por, self.moeda, self.documento, self.data = preco, por, moeda, documento, data

    @property
    def unitario(self):
        return self.preco / self.por

    def unitario_texto(self):
        return decimal(self.unitario, maximo=4)

    def __str__(self):
        texto = "%s %s" % (self.unitario_texto(), self.moeda)
        if self.por != 1:
            texto += " · %s %s por %s" % (decimal(self.preco), self.moeda, decimal(self.por, minimo=0))
        if self.documento:
            texto += " · pedido %s" % self.documento
        return texto + " de %s" % ".".join(reversed(self.data.split("-")))


def _localizar_colunas(disponiveis):
    nomes = {nome.upper(): nome for nome, _ in disponiveis}
    titulos = {titulo.strip().lower(): nome for nome, titulo in disponiveis if titulo}
    achadas = {}
    for chave, (tecnicos, rotulos) in COLUNAS.items():
        for candidato in tecnicos:
            if candidato in nomes:
                achadas[chave] = nomes[candidato]
                break
        else:
            for rotulo in rotulos:
                if rotulo in titulos:
                    achadas[chave] = titulos[rotulo]
                    break
    faltando = [chave for chave in OBRIGATORIAS if chave not in achadas]
    if faltando:
        nomes_legiveis = {"data": "Data doc.", "preco": "Preço líq.", "por": "Unidade preço"}
        raise ErroSap("a ME2M não mostrou a(s) coluna(s) %s; colunas na tela: %s" % (
            ", ".join(nomes_legiveis[chave] for chave in faltando),
            ", ".join(titulo or nome for nome, titulo in disponiveis)))
    return achadas


def numero(texto):
    """Número no formato do SAP (1.002,62 ou 1,002.62; sinal pode vir no fim)."""
    texto = (texto or "").strip().replace(" ", "")
    negativo = texto.endswith("-") or texto.startswith("-")
    texto = texto.strip("-")
    if not texto or not re.fullmatch(r"[\d.,]+", texto):
        return None
    if "," in texto and "." in texto:
        decimal_ = "," if texto.rfind(",") > texto.rfind(".") else "."
    elif "," in texto or "." in texto:
        separador = "," if "," in texto else "."
        depois = texto.rsplit(separador, 1)[1]
        # 1.002 ou 1,002 (três dígitos no fim, ou o separador repetido) é milhar
        decimal_ = None if (len(depois) == 3 or texto.count(separador) > 1) else separador
    else:
        decimal_ = None
    inteiro, fracao = texto.rsplit(decimal_, 1) if decimal_ else (texto, "0")
    inteiro = re.sub(r"[.,]", "", inteiro) or "0"
    valor = float(inteiro + "." + (fracao or "0"))
    return -valor if negativo else valor


def data_iso(texto):
    """Data no formato do SAP (16.11.2026, 11/16/2026, 2026.11.16...) como 2026-11-16."""
    partes = re.findall(r"\d+", texto or "")
    if len(partes) != 3:
        return None
    if len(partes[0]) == 4:
        ano, mes, dia = partes
    elif "." in texto:
        dia, mes, ano = partes
    else:  # 11/16/2026 ou 11-16-2026
        mes, dia, ano = partes
    try:
        return "%04d-%02d-%02d" % (int(ano), int(mes), int(dia))
    except ValueError:
        return None


def decimal(valor, minimo=2, maximo=2):
    """Número com vírgula decimal, sem separador de milhar (o Sheets e o Excel em
    português leem assim), com no mínimo e no máximo tantas casas."""
    texto = "%.*f" % (maximo, valor)
    if "." in texto:
        inteiro, fracao = texto.split(".")
        fracao = fracao.rstrip("0").ljust(minimo, "0")
        texto = inteiro + ("," + fracao if fracao else "")
    return texto
