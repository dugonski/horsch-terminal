"""Preço do pedido de compra mais recente de cada part number, lido direto da ME2M.

A lista da ME2M é lida na tela do SAP, sem exportar para planilha. Os preços são
divididos pela unidade de preço (preço por 100 vira preço por 1) e, no fim, vão
para a área de transferência na mesma ordem da lista colada, para colar de volta
no Excel ou no Google Sheets.
"""
import re
import unicodedata

from src.sap import ErroSap

COMANDO = "precos"
TITULO = "Preços ME2M"
DESCRICAO = "Preço do pedido de compra mais recente de cada part number (ME2M, centro 8500)"
ROTULO = "part numbers"
LINHAS = True  # uma linha colada = um item, para os preços voltarem alinhados

CENTRO = "8500"
CAMPO_MATERIAL = "wnd[0]/usr/ctxtEM_MATNR-LOW"
CAMPO_CENTRO = "wnd[0]/usr/ctxtEM_WERKS-LOW"
SELECAO_MULTIPLA = "wnd[0]/usr/btn%_EM_MATNR_%_APP_%-VALU_PUSH"

# Colunas procuradas na lista: primeiro pelo nome técnico, depois pelo título na tela.
COLUNAS = {
    "data": (("BEDAT",), ("data doc.", "data documento", "data do documento")),
    "preco": (("NETPR",), ("preço líq.", "preço líquido", "preço liq.")),
    "por": (("PEINH",), ("unidade preço", "unid.preço", "unidade de preço", "por")),
    "moeda": (("WAERS",), ("moeda",)),
    "documento": (("EBELN",), ("documento compras", "documento de compras", "doc.compra")),
    "item": (("EBELP",), ("item",)),
    "material": (("MATNR",), ("material",)),
    "texto": (("TXZ01",), ("texto breve", "txt.breve")),
    "centro": (("WERKS",), ("cen.", "centro")),
}
OBRIGATORIAS = ("data", "preco", "por")


def inicio(sap):
    """Abre a ME2M numa janela nova do SAP, para não mexer na janela em que você está."""
    return sap.nova_janela("me2m")


def fim(sap):
    """Fecha a janela nova, mesmo se algum item falhar ou se a execução for cancelada."""
    sap.fechar()


def por_lote(sap, materiais):
    """Uma consulta só na ME2M com todos os part numbers (seleção múltipla). Precisa
    da coluna Material na lista para saber de quem é cada pedido; sem ela, o app
    consulta um part number por vez com por_item()."""
    sap.texto("wnd[0]/tbar[0]/okcd", "/nme2m")
    sap.tecla("wnd[0]", 0)
    centro_na_selecao = _preencher_centro(sap)
    sap.selecao_multipla(SELECAO_MULTIPLA, materiais)
    sap.tecla("wnd[0]", 8)  # Executar (F8)

    grade = sap.grade()
    if grade is None:
        _, texto = sap.status()
        erro = ErroSap(texto or "nenhum pedido de compra encontrado")
        return {material: erro for material in materiais}

    colunas = _localizar_colunas(grade.colunas())
    _completar_com_ocultas(grade, colunas, ("material", "documento", "texto", "centro"))
    _garantir_centro(colunas, centro_na_selecao)
    if "material" not in colunas:
        raise ErroSap("a lista da ME2M não tem a coluna Material, nem oculta")
    por_material = {}
    for candidato, linha in _candidatos(grade, colunas):
        por_material.setdefault(_chave(linha[colunas["material"]]), []).append(candidato)

    resultado = {}
    for material in materiais:
        candidatos = por_material.get(_chave(material))
        resultado[material] = _mais_recente(candidatos) if candidatos else ErroSap(SEM_PEDIDO)
    return resultado


def por_item(sap, material):
    sap.texto("wnd[0]/tbar[0]/okcd", "/nme2m")
    sap.tecla("wnd[0]", 0)
    centro_na_selecao = _preencher_centro(sap)
    sap.texto(CAMPO_MATERIAL, material)
    sap.tecla("wnd[0]", 8)  # Executar (F8)

    grade = sap.grade()
    if grade is None:
        _, texto = sap.status()
        raise ErroSap(texto or "nenhum pedido de compra encontrado")

    colunas = _localizar_colunas(grade.colunas())
    _completar_com_ocultas(grade, colunas, ("documento", "texto", "centro"))
    _garantir_centro(colunas, centro_na_selecao)
    candidatos = [candidato for candidato, _ in _candidatos(grade, colunas)]
    if not candidatos:
        raise ErroSap(SEM_PEDIDO)
    return _mais_recente(candidatos)


SEM_PEDIDO = "nenhum pedido com preço no centro %s" % CENTRO


def _preencher_centro(sap):
    """Filtra a ME2M pelo centro já na seleção. Devolve False se o campo não existir."""
    try:
        sap.texto(CAMPO_CENTRO, CENTRO)
        return True
    except ErroSap:
        return False


def _garantir_centro(colunas, centro_na_selecao):
    """Sem o filtro na seleção e sem a coluna Cen. na lista, não há como garantir o
    centro: melhor parar do que devolver o preço de outro centro."""
    if not centro_na_selecao and "centro" not in colunas:
        raise ErroSap("não foi possível filtrar pelo centro %s: o campo Centro não apareceu na seleção "
                      "da ME2M e a lista não tem a coluna Cen." % CENTRO)


def _candidatos(grade, colunas):
    """Pedidos do centro com data e preço, como (candidato, linha). Linhas de
    subtotal, itens sem preço (grátis) e pedidos de outros centros ficam de fora."""
    for ordem, linha in enumerate(grade.valores(list(colunas.values()))):
        if "centro" in colunas and linha[colunas["centro"]].strip() != CENTRO:
            continue
        data = data_iso(linha[colunas["data"]])
        preco = numero(linha[colunas["preco"]])
        por = numero(linha[colunas["por"]]) or 1
        if not data or not preco or preco <= 0:
            continue
        documento = linha.get(colunas.get("documento"), "")
        moeda, texto = linha.get(colunas.get("moeda"), ""), linha.get(colunas.get("texto"), "")
        yield (data, documento, ordem, preco, por, moeda, texto), linha


def _mais_recente(candidatos):
    data, documento, _, preco, por, moeda, texto = max(candidatos)
    return Preco(preco, por, moeda, documento, data, texto)


def _chave(material):
    """O SAP mostra materiais numéricos sem os zeros à esquerda."""
    material = material.strip().upper()
    return material.lstrip("0") or material if material.isdigit() else material


def concluir(linhas, resultados):
    """Copia preço unitário e texto breve, uma linha por part number e na ordem da
    lista, em duas colunas: colado ao lado dos part numbers, o preço fica na coluna
    seguinte e o texto breve na outra. Linhas sem preço ficam em branco."""
    from src import area_de_transferencia

    valores = []
    for pn in linhas:
        resultado = resultados.get(pn) if pn else None
        valores.append("%s\t%s" % (resultado.unitario_texto(), resultado.texto) if resultado else "")
    if area_de_transferencia.copiar("\n".join(valores)):
        return ["Conteúdo copiado para o Ctrl+V"]
    # Sem área de transferência: mostra na tela, para copiar à mão.
    return ["Não foi possível copiar automaticamente. Preços na ordem da lista:"] + [
        valor.replace("\t", "  ") or "-" for valor in valores]


# Colunas da planilha: achadas pelo cabeçalho da linha 1; sem cabeçalho, B, C e D.
# (coluna padrão, nomes aceitos no cabeçalho, título escrito quando ele está vazio)
COLUNAS_DA_PLANILHA = {
    "descricao": ("B", ("descricao", "texto breve", "texto"), "Descrição"),
    "preco": ("C", ("preco", "preco unitario", "preco liquido"), "Preço"),
    "moeda": ("D", ("moeda",), "Moeda"),
}


def preencher_planilha(caminho, linhas, cabecalho, resultados):
    """Grava descrição (texto breve), preço unitário e moeda ao lado de cada part
    number da planilha. Linhas sem pedido ficam como estavam."""
    from src import planilha

    titulos = {_sem_acento(titulo): coluna for coluna, titulo in cabecalho.items()}
    colunas = {}
    for chave, (padrao, nomes, _) in COLUNAS_DA_PLANILHA.items():
        colunas[chave] = next((titulos[nome] for nome in nomes if nome in titulos), padrao)

    valores, estilos = {}, {}
    # Linha 1 é cabeçalho (não é um part number): completa os títulos que faltam, com a
    # formatação da A1, sem trocar um título já escrito.
    if cabecalho and all(linha != 1 for linha, _ in linhas):
        faltando = {colunas[chave]: titulo for chave, (_, _, titulo) in COLUNAS_DA_PLANILHA.items()
                    if not cabecalho.get(colunas[chave])}
        if faltando:
            valores[1], estilos[1] = faltando, "A"

    for linha, pn in linhas:
        resultado = resultados.get(pn)
        if resultado:
            valores[linha] = {colunas["descricao"]: resultado.texto,
                              colunas["preco"]: round(resultado.unitario, 6),
                              colunas["moeda"]: resultado.moeda}
    preenchidas = len([linha for linha in valores if linha != 1 or 1 not in estilos])
    if not preenchidas:
        return ["Nenhum preço encontrado; a planilha não foi alterada."]
    planilha.preencher(caminho, valores, estilos)
    if preenchidas < len(linhas):
        return ["Linhas sem pedido no centro %s ficaram como estavam na planilha." % CENTRO]
    return []


def _sem_acento(texto):
    texto = unicodedata.normalize("NFKD", texto.strip().lower())
    return "".join(letra for letra in texto if not unicodedata.combining(letra))


class Preco:
    def __init__(self, preco, por, moeda, documento, data, texto=""):
        self.preco, self.por, self.moeda, self.documento, self.data = preco, por, moeda, documento, data
        self.texto = " ".join(texto.split())  # sem tabs ou quebras, para não desalinhar a colagem

    @property
    def unitario(self):
        return self.preco / self.por

    def unitario_texto(self):
        return decimal(self.unitario, maximo=4)

    # Larguras das colunas na tela. O texto breve do SAP tem no máximo 40 caracteres.
    LARGURA_DO_TEXTO = 40
    LARGURA_DO_PRECO = 10

    def __str__(self):
        """Uma linha em colunas de largura fixa: texto breve, preço unitário e moeda,
        data e pedido; o preço original (por 100 etc.) vai no fim."""
        texto = self.texto
        if len(texto) > self.LARGURA_DO_TEXTO:
            texto = texto[:self.LARGURA_DO_TEXTO - 1] + "…"
        colunas = [texto.ljust(self.LARGURA_DO_TEXTO),
                   self.unitario_texto().rjust(self.LARGURA_DO_PRECO) + " " + self.moeda.ljust(3),
                   ".".join(reversed(self.data.split("-")))]
        if self.documento:
            colunas.append("pedido " + self.documento)
        if self.por != 1:
            colunas.append("(%s %s por %s)" % (decimal(self.preco), self.moeda, decimal(self.por, minimo=0)))
        return "  ".join(colunas)


def _completar_com_ocultas(grade, colunas, chaves):
    """Material, número do pedido e texto breve podem estar ocultos no layout
    (aparecendo só nas linhas de agrupamento); tenta lê-los pelo nome técnico."""
    for chave in chaves:
        if chave not in colunas:
            nome = COLUNAS[chave][0][0]
            if grade.coluna_oculta(nome):
                colunas[chave] = nome


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
