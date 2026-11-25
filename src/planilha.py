"""Leitura e preenchimento de planilhas .xlsx só com a biblioteca padrão.

Um .xlsx é um zip com arquivos XML. A leitura usa a primeira aba. O preenchimento
troca apenas as células pedidas, editando o XML da aba como texto, para não mexer
em formatação, larguras de coluna ou outras abas.
"""
import os
import re
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


class ErroPlanilha(Exception):
    pass


def eh_planilha(texto):
    """Caminho de .xlsx (com ou sem aspas, como o Windows cola ao arrastar o arquivo)."""
    caminho = texto.strip().strip('"').strip("'").strip()
    return caminho if caminho.lower().endswith(".xlsx") else None


def _abrir(caminho):
    if not os.path.isfile(caminho):
        raise ErroPlanilha("arquivo não encontrado: %s" % caminho)
    try:
        return zipfile.ZipFile(caminho)
    except (zipfile.BadZipFile, OSError):
        raise ErroPlanilha("o arquivo não é um .xlsx válido (ou está aberto e bloqueado)")


def _caminho_da_primeira_aba(pacote):
    try:
        livro = ET.fromstring(pacote.read("xl/workbook.xml"))
        relacoes = ET.fromstring(pacote.read("xl/_rels/workbook.xml.rels"))
    except KeyError:
        raise ErroPlanilha("o arquivo não parece uma planilha do Excel")
    aba = livro.find("m:sheets/m:sheet", NS)
    if aba is None:
        raise ErroPlanilha("a planilha não tem nenhuma aba")
    id_ = aba.get("{%s}id" % NS["r"])
    for relacao in relacoes.findall("rel:Relationship", NS):
        if relacao.get("Id") == id_:
            alvo = relacao.get("Target").replace("\\", "/")
            return alvo.lstrip("/") if alvo.startswith("/") else "xl/" + alvo
    raise ErroPlanilha("não foi possível achar a primeira aba da planilha")


def _textos_compartilhados(pacote):
    try:
        raiz = ET.fromstring(pacote.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(t.text or "" for t in item.iter("{%s}t" % NS["m"])) for item in raiz.findall("m:si", NS)]


def _coluna_e_linha(referencia):
    letras, numero = re.match(r"([A-Z]+)(\d+)", referencia).groups()
    return letras, int(numero)


def _indice_da_coluna(letras):
    indice = 0
    for letra in letras:
        indice = indice * 26 + ord(letra) - 64
    return indice


def _valor(celula, compartilhados):
    tipo = celula.get("t")
    if tipo == "inlineStr":
        return "".join(t.text or "" for t in celula.iter("{%s}t" % NS["m"]))
    valor = celula.find("m:v", NS)
    texto = valor.text if valor is not None and valor.text else ""
    if tipo == "s":
        try:
            return compartilhados[int(texto)]
        except (ValueError, IndexError):
            return ""
    if tipo in (None, "n") and texto:
        try:  # 60103019, 60103019.0 ou 6.0103019E7 viram 60103019
            numero = float(texto)
            if numero.is_integer():
                return str(int(numero))
        except ValueError:
            pass
    return texto


def ler(caminho):
    """Devolve as linhas da primeira aba como {número da linha: {coluna: texto}}."""
    with _abrir(caminho) as pacote:
        aba = _caminho_da_primeira_aba(pacote)
        compartilhados = _textos_compartilhados(pacote)
        try:
            raiz = ET.fromstring(pacote.read(aba))
        except KeyError:
            raise ErroPlanilha("a primeira aba da planilha está vazia ou corrompida")
    linhas = {}
    for celula in raiz.iter("{%s}c" % NS["m"]):
        referencia = celula.get("r")
        if not referencia:
            continue
        coluna, linha = _coluna_e_linha(referencia)
        valor = _valor(celula, compartilhados).strip()
        if valor:
            linhas.setdefault(linha, {})[coluna] = valor
    return linhas


def verificar_gravacao(caminho):
    """Erro já no começo se o arquivo estiver aberto no Excel (bloqueado para gravar)."""
    try:
        with open(caminho, "r+b"):
            pass
    except PermissionError:
        raise ErroPlanilha("não foi possível gravar na planilha: feche o arquivo no Excel e tente de novo")
    except OSError as erro:
        raise ErroPlanilha("não foi possível gravar na planilha (%s)" % erro)


def _celula_nova(prefixo, referencia, valor, estilo):
    atributos = ' r="%s"' % referencia + (' s="%s"' % estilo if estilo else "")
    if valor is None or valor == "":
        return "<%sc%s/>" % (prefixo, atributos)
    if isinstance(valor, (int, float)):
        numero = ("%.6f" % valor).rstrip("0").rstrip(".")
        return "<%sc%s><%sv>%s</%sv></%sc>" % (prefixo, atributos, prefixo, numero, prefixo, prefixo)
    texto = escape(str(valor))
    return '<%sc%s t="inlineStr"><%sis><%st xml:space="preserve">%s</%st></%sis></%sc>' % (
        prefixo, atributos, prefixo, prefixo, texto, prefixo, prefixo, prefixo)


def _preencher_linha(conteudo, prefixo, linha, valores):
    """Troca ou insere as células de uma linha, mantendo a ordem das colunas."""
    padrao_celula = re.compile(r'<%sc\b[^>]*?\br="([A-Z]+)%d"[^>]*?(?:/>|>.*?</%sc>)' % (prefixo, linha, prefixo), re.S)
    for coluna, valor in sorted(valores.items(), key=lambda item: _indice_da_coluna(item[0])):
        referencia = "%s%d" % (coluna, linha)
        existentes = list(padrao_celula.finditer(conteudo))
        atual = next((celula for celula in existentes if celula.group(1) == coluna), None)
        if atual:
            estilo = re.search(r'\bs="(\d+)"', atual.group(0).split(">", 1)[0])
            nova = _celula_nova(prefixo, referencia, valor, estilo.group(1) if estilo else None)
            conteudo = conteudo[:atual.start()] + nova + conteudo[atual.end():]
            continue
        nova = _celula_nova(prefixo, referencia, valor, None)
        depois = next((celula for celula in existentes
                       if _indice_da_coluna(celula.group(1)) > _indice_da_coluna(coluna)), None)
        posicao = depois.start() if depois else len(conteudo)
        conteudo = conteudo[:posicao] + nova + conteudo[posicao:]
    return conteudo


def preencher(caminho, valores):
    """Grava os valores {número da linha: {coluna: valor}} na primeira aba. Números
    viram células numéricas; textos, células de texto. As linhas já têm de existir
    (são as linhas dos part numbers)."""
    with _abrir(caminho) as pacote:
        aba = _caminho_da_primeira_aba(pacote)
        xml = pacote.read(aba).decode("utf-8")
        itens = [(info, pacote.read(info.filename)) for info in pacote.infolist()]

    raiz = re.search(r"<(\w+:)?worksheet\b", xml)
    prefixo = (raiz.group(1) or "") if raiz else ""
    for linha, colunas in sorted(valores.items()):
        padrao_linha = re.compile(r'(<%srow\b[^>]*?\br="%d"[^>]*>)(.*?)(</%srow>)' % (prefixo, linha, prefixo), re.S)
        encontrada = padrao_linha.search(xml)
        if not encontrada:
            continue
        conteudo = _preencher_linha(encontrada.group(2), prefixo, linha, colunas)
        xml = xml[:encontrada.start(2)] + conteudo + xml[encontrada.end(2):]

    pasta = os.path.dirname(os.path.abspath(caminho))
    descritor, temporario = tempfile.mkstemp(suffix=".xlsx", dir=pasta)
    os.close(descritor)
    try:
        with zipfile.ZipFile(temporario, "w", zipfile.ZIP_DEFLATED) as novo:
            for info, dados in itens:
                novo.writestr(info, xml.encode("utf-8") if info.filename == aba else dados)
        os.replace(temporario, caminho)
    except PermissionError:
        raise ErroPlanilha("não foi possível gravar na planilha: feche o arquivo no Excel e tente de novo")
    except OSError as erro:
        raise ErroPlanilha("não foi possível gravar na planilha (%s)" % erro)
    finally:
        if os.path.exists(temporario):
            os.remove(temporario)
