"""Criação de itens no Jira a partir de uma planilha .xlsx (comando /jira).

Usa a API REST do Jira Server/Data Center com um token pessoal. Cada linha da
planilha vira um item; o cabeçalho (linha 1) diz qual campo está em cada coluna.
Os textos ("Tarefa", "BRA Electronics", "Média") são traduzidos para os códigos
do Jira com a lista de campos e valores aceitos que o próprio Jira informa.
"""
import datetime
import json
import mimetypes
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid

from . import planilha


class ErroJira(Exception):
    pass


def _normal(texto):
    texto = unicodedata.normalize("NFKD", str(texto).strip().lower())
    return " ".join("".join(letra for letra in texto if not unicodedata.combining(letra)).split())


def _chaves(texto):
    """Formas aceitas de um nome de campo: "Componente(s)", "Componentes" e "componente"
    casam entre si; acentos, maiúsculas e pontuação não importam."""
    base = _normal(texto)
    sem_plural = re.sub(r"\(s\)", "", base).strip()
    so_letras = re.sub(r"[^a-z0-9]", "", sem_plural)
    return [base, sem_plural, so_letras, so_letras.rstrip("s")]


def _separar(texto):
    return [parte.strip() for parte in re.split(r"[;\n]", texto) if parte.strip()]


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class Cliente:
    def __init__(self, url, token):
        self.url = url.rstrip("/")
        self.token = token
        self._tipos = {}
        self._campos = {}
        self._vinculos = None

    def _pedido(self, metodo, caminho, corpo=None, cabecalhos=None):
        enviar = {"Authorization": "Bearer " + self.token, "Accept": "application/json",
                  "User-Agent": "horsch-terminal"}
        dados = None
        if isinstance(corpo, (dict, list)):
            dados = json.dumps(corpo).encode("utf-8")
            enviar["Content-Type"] = "application/json"
        elif corpo is not None:
            dados = corpo
        enviar.update(cabecalhos or {})
        pedido = urllib.request.Request(self.url + caminho, data=dados, headers=enviar, method=metodo)
        try:
            with urllib.request.urlopen(pedido, timeout=60) as resposta:
                texto = resposta.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as erro:
            raise ErroJira(_mensagem_de_erro(erro))
        except (urllib.error.URLError, OSError) as erro:
            raise ErroJira("sem acesso ao Jira (%s)" % getattr(erro, "reason", erro))
        try:
            return json.loads(texto) if texto.strip() else None
        except ValueError:
            raise ErroJira("o Jira respondeu algo inesperado (o endereço no jira.ini está certo?)")

    def _paginas(self, caminho):
        """Junta as páginas de uma consulta paginada (startAt/maxResults)."""
        valores, inicio = [], 0
        while True:
            separador = "&" if "?" in caminho else "?"
            resposta = self._pedido("GET", "%s%sstartAt=%d&maxResults=100" % (caminho, separador, inicio))
            pagina = resposta.get("values", []) if isinstance(resposta, dict) else []
            valores += pagina
            inicio += len(pagina)
            if not pagina or resposta.get("isLast", True) or inicio >= resposta.get("total", inicio):
                return valores

    def eu(self):
        return self._pedido("GET", "/rest/api/2/myself")

    def tipos(self, projeto):
        """{nome normalizado ou id: id} dos tipos de item que podem ser criados no projeto."""
        if projeto not in self._tipos:
            caminho = "/rest/api/2/issue/createmeta/%s/issuetypes" % urllib.parse.quote(projeto)
            try:
                tipos = self._paginas(caminho)
            except ErroJira:
                try:
                    tipos = self._meta_antigo(projeto).get("issuetypes", [])
                except ErroJira:
                    tipos = []
            if not tipos:
                raise ErroJira('o projeto "%s" não existe ou você não pode criar itens nele' % projeto)
            mapa = {}
            for tipo in tipos:
                mapa[_normal(tipo["name"])] = mapa[str(tipo["id"])] = str(tipo["id"])
            self._tipos[projeto] = (mapa, [tipo["name"] for tipo in tipos])
        return self._tipos[projeto]

    def campos(self, projeto, tipo_id):
        """{id do campo: {name, required, hasDefaultValue, schema, allowedValues}}."""
        chave = (projeto, tipo_id)
        if chave not in self._campos:
            caminho = "/rest/api/2/issue/createmeta/%s/issuetypes/%s" % (urllib.parse.quote(projeto), tipo_id)
            try:
                campos = {campo["fieldId"]: campo for campo in self._paginas(caminho)}
            except ErroJira:
                campos = {}
                try:
                    antigos = self._meta_antigo(projeto).get("issuetypes", [])
                except ErroJira:
                    antigos = []
                for tipo in antigos:
                    if str(tipo["id"]) == tipo_id:
                        campos = tipo.get("fields", {})
            self._campos[chave] = campos
        return self._campos[chave]

    def _meta_antigo(self, projeto):
        """Consulta usada pelas versões do Jira anteriores à 9."""
        resposta = self._pedido("GET", "/rest/api/2/issue/createmeta?projectKeys=%s&expand=projects.issuetypes.fields"
                                % urllib.parse.quote(projeto))
        projetos = resposta.get("projects", []) if resposta else []
        return projetos[0] if projetos else {}

    def vinculos(self):
        """{descrição normalizada ("blocks", "is blocked by"): (nome do tipo, lado)}."""
        if self._vinculos is None:
            self._vinculos = {}
            for tipo in (self._pedido("GET", "/rest/api/2/issueLinkType") or {}).get("issueLinkTypes", []):
                # Na criação, "outwardIssue" faz o item novo ficar no lado da descrição de saída.
                self._vinculos[_normal(tipo["outward"])] = (tipo["name"], "outwardIssue")
                self._vinculos.setdefault(_normal(tipo["inward"]), (tipo["name"], "inwardIssue"))
        return self._vinculos

    def criar(self, campos, atualizar=None):
        corpo = {"fields": campos}
        if atualizar:
            corpo["update"] = atualizar
        return self._pedido("POST", "/rest/api/2/issue", corpo)["key"]

    def anexar(self, chave, caminho):
        fronteira = uuid.uuid4().hex
        nome = os.path.basename(caminho).replace('"', "")
        tipo = mimetypes.guess_type(nome)[0] or "application/octet-stream"
        with open(caminho, "rb") as arquivo:
            conteudo = arquivo.read()
        corpo = (("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                  "Content-Type: %s\r\n\r\n" % (fronteira, nome, tipo)).encode("utf-8")
                 + conteudo + ("\r\n--%s--\r\n" % fronteira).encode("utf-8"))
        self._pedido("POST", "/rest/api/2/issue/%s/attachments" % urllib.parse.quote(chave), corpo,
                     {"Content-Type": "multipart/form-data; boundary=" + fronteira, "X-Atlassian-Token": "no-check"})


def _mensagem_de_erro(erro):
    if erro.code == 401:
        return "o Jira recusou o token (inválido ou expirado): gere um novo e troque no jira.ini"
    if erro.code == 403:
        return "o Jira negou o acesso (sem permissão para esta ação)"
    try:
        dados = json.loads(erro.read().decode("utf-8", "replace"))
    except (ValueError, OSError):
        return "o Jira respondeu com erro %d" % erro.code
    mensagens = list(dados.get("errorMessages") or [])
    mensagens += ["%s: %s" % (campo, texto) for campo, texto in (dados.get("errors") or {}).items()]
    return "; ".join(mensagens) or "o Jira respondeu com erro %d" % erro.code


# ---------------------------------------------------------------------------
# Conversão dos textos da planilha para o formato do Jira
# ---------------------------------------------------------------------------

def _data(texto):
    """dd.mm.aaaa, dd/mm/aaaa, aaaa-mm-dd ou data do Excel (número de dias) -> aaaa-mm-dd."""
    texto = texto.strip()
    if re.fullmatch(r"\d+(\.\d+)?", texto):  # o Excel guarda datas como número de dias desde 1899-12-30
        return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(float(texto)))).isoformat()
    partes = re.findall(r"\d+", texto)
    if len(partes) == 3:
        if len(partes[0]) == 4:
            ano, mes, dia = partes
        else:
            dia, mes, ano = partes
        try:
            return datetime.date(int(ano), int(mes), int(dia)).isoformat()
        except ValueError:
            pass
    raise ErroJira('data inválida: "%s" (use dd.mm.aaaa)' % texto)


def _opcao(campo, texto):
    alvo = _normal(texto)
    opcoes = campo.get("allowedValues") or []
    for opcao in opcoes:
        for chave in ("name", "value", "key", "id"):
            if chave in opcao and _normal(opcao[chave]) == alvo:
                return {"id": str(opcao["id"])} if "id" in opcao else {"name": opcao.get("name")}
    nomes = [str(opcao.get("name") or opcao.get("value")) for opcao in opcoes]
    resumo = ", ".join(nomes[:12]) + (", ..." if len(nomes) > 12 else "")
    raise ErroJira('%s: "%s" não é uma opção válida (opções: %s)' % (campo.get("name"), texto, resumo))


def converter(campo, texto):
    """Valor da célula no formato que a API espera para este campo."""
    texto = texto.strip()
    if texto[:1] in ("[", "{"):  # JSON escrito à mão, para campos que o app não conhece
        try:
            return json.loads(texto)
        except ValueError:
            pass
    esquema = campo.get("schema") or {}
    tipo, itens, extra = esquema.get("type"), esquema.get("items"), esquema.get("custom") or ""
    if extra.endswith(":gh-epic-link"):
        return texto
    if tipo == "array":
        partes = _separar(texto)
        if campo.get("allowedValues"):
            return [_opcao(campo, parte) for parte in partes]
        if itens == "user":
            return [{"name": parte} for parte in partes]
        return partes
    if tipo == "date":
        return _data(texto)
    if tipo == "datetime":
        return _data(texto) + "T00:00:00.000+0000"
    if tipo == "number":
        try:
            return float(texto.replace(",", "."))
        except ValueError:
            raise ErroJira('%s: "%s" não é um número' % (campo.get("name"), texto))
    if tipo == "user":
        return {"name": "-1" if _normal(texto) == "automatico" else texto}
    if campo.get("allowedValues"):
        return _opcao(campo, texto)
    if tipo in ("priority", "option", "component", "version", "resolution"):
        return {"name": texto}
    return texto


# ---------------------------------------------------------------------------
# Planilha
# ---------------------------------------------------------------------------

# Colunas com significado próprio (o resto é procurado entre os campos do Jira).
ESPECIAIS = {
    "projeto": "project", "project": "project",
    "tipo": "issuetype", "tipo de item": "issuetype", "issuetype": "issuetype",
    "chave": "chave", "key": "chave",
    "status": "status", "resultado": "status",
    "anexos": "anexos", "anexo": "anexos", "attachment": "anexos",
    "itens vinculados": "vinculos", "vinculos": "vinculos", "vinculo": "vinculos", "issuelinks": "vinculos",
}


def _letra(indice):
    letras = ""
    while indice:
        indice, resto = divmod(indice - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


class Planilha:
    """As linhas da planilha e onde fica cada coluna."""

    def __init__(self, caminho):
        self.caminho = caminho
        linhas = planilha.ler(caminho)
        cabecalho = linhas.get(1, {})
        if not cabecalho:
            raise ErroJira("a linha 1 da planilha precisa ter o cabeçalho (Projeto, Tipo, Resumo...)")
        self.colunas = {}  # coluna -> ("especial", nome) ou ("campo", título)
        for coluna, titulo in cabecalho.items():
            especial = ESPECIAIS.get(_normal(titulo))
            self.colunas[coluna] = ("especial", especial) if especial else ("campo", titulo)
        ultima = max(planilha._indice_da_coluna(coluna) for coluna in cabecalho)
        self.novas = {}  # colunas de resultado que ainda não existem no cabeçalho
        for nome, titulo in (("chave", "Chave"), ("status", "Status")):
            if not self.coluna_de(nome):
                ultima += 1
                self.colunas[_letra(ultima)] = ("especial", nome)
                self.novas[_letra(ultima)] = titulo
        self.linhas = {numero: valores for numero, valores in linhas.items() if numero > 1}

    def coluna_de(self, especial):
        return next((coluna for coluna, (tipo, nome) in self.colunas.items()
                     if tipo == "especial" and nome == especial), None)

    def valor(self, linha, especial):
        coluna = self.coluna_de(especial)
        return self.linhas.get(linha, {}).get(coluna, "").strip() if coluna else ""

    def gravar(self, linha, chave, status):
        valores = {self.coluna_de("chave"): chave, self.coluna_de("status"): status}
        if chave:
            self.linhas.setdefault(linha, {})[self.coluna_de("chave")] = chave
        cabecalho, self.novas = self.novas, {}
        if cabecalho:
            planilha.preencher(self.caminho, {1: cabecalho, linha: valores}, {1: "A"})
        else:
            planilha.preencher(self.caminho, {linha: valores})


def montar(cliente, tabela, linha):
    """Campos, vínculos e anexos de uma linha, já validados. Erro se algo estiver errado."""
    projeto = tabela.valor(linha, "project")
    tipo = tabela.valor(linha, "issuetype")
    if not projeto or not tipo:
        raise ErroJira("preencha Projeto e Tipo")
    tipos, nomes_dos_tipos = cliente.tipos(projeto)
    tipo_id = tipos.get(_normal(tipo)) or tipos.get(tipo)
    if not tipo_id:
        raise ErroJira('tipo "%s" não existe no projeto %s (tipos: %s)' % (tipo, projeto, ", ".join(nomes_dos_tipos)))
    campos_do_jira = cliente.campos(projeto, tipo_id)
    por_nome = {}
    for campo_id, campo in campos_do_jira.items():
        for chave in _chaves(campo.get("name", campo_id)) + [_normal(campo_id)]:
            por_nome.setdefault(chave, campo_id)

    campos = {"project": {"key": projeto}, "issuetype": {"id": tipo_id}}
    for coluna, (natureza, titulo) in sorted(tabela.colunas.items()):
        texto = tabela.linhas.get(linha, {}).get(coluna, "").strip()
        if natureza != "campo" or not texto:
            continue
        campo_id = next((por_nome[chave] for chave in _chaves(titulo) if chave in por_nome), None)
        if not campo_id or campo_id in ("project", "issuetype", "attachment", "issuelinks"):
            raise ErroJira('a coluna "%s" não é um campo de %s no projeto %s' % (titulo, tipo, projeto))
        campos[campo_id] = converter(campos_do_jira[campo_id], texto)

    faltando = [campo.get("name", campo_id) for campo_id, campo in campos_do_jira.items()
                if campo.get("required") and not campo.get("hasDefaultValue") and campo_id not in campos]
    if faltando:
        raise ErroJira("campo obrigatório vazio: " + ", ".join(faltando))

    atualizar = []
    for vinculo in _separar(tabela.valor(linha, "vinculos")):
        texto = _normal(vinculo)
        descricao = max((descricao for descricao in cliente.vinculos() if texto.startswith(descricao + " ")),
                        key=len, default=None)
        if not descricao:
            raise ErroJira('vínculo "%s" não reconhecido (use, por exemplo, "blocks BRASRD-123")' % vinculo)
        nome, lado = cliente.vinculos()[descricao]
        outro = vinculo.strip()[len(descricao):].strip().upper()
        atualizar.append({"add": {"type": {"name": nome}, lado: {"key": outro}}})

    anexos = _separar(tabela.valor(linha, "anexos"))
    faltando = [anexo for anexo in anexos if not os.path.isfile(anexo.strip('"'))]
    if faltando:
        raise ErroJira("anexo não encontrado: " + ", ".join(faltando))
    return campos, ({"issuelinks": atualizar} if atualizar else None), [anexo.strip('"') for anexo in anexos]


def executar(cliente, caminho, testar, mostrar, andamento=lambda texto: None, cancelar=lambda: False):
    """Cria um item por linha. mostrar(linha, ok, texto) recebe o resultado de cada uma.
    Devolve (criados, com_erro, pulados); no teste, "criados" são as linhas prontas."""
    tabela = Planilha(caminho)
    criados = com_erro = pulados = 0
    for linha in sorted(tabela.linhas):
        dados = {coluna: valor for coluna, valor in tabela.linhas[linha].items()
                 if tabela.colunas.get(coluna, ("", ""))[1] not in ("chave", "status") and valor.strip()}
        if not dados:
            continue  # linha vazia
        if tabela.valor(linha, "chave"):
            pulados += 1
            continue  # já criado antes
        if cancelar():
            break
        resumo = next((tabela.linhas[linha].get(coluna, "") for coluna, (natureza, titulo) in tabela.colunas.items()
                       if natureza == "campo" and _normal(titulo) in ("resumo", "summary")), "")
        andamento("Linha %d · %s" % (linha, resumo[:50]))
        try:
            campos, atualizar, anexos = montar(cliente, tabela, linha)
            if testar:
                criados += 1
                mostrar(linha, True, "pronta · " + resumo)
                continue
            chave = cliente.criar(campos, atualizar)
        except ErroJira as erro:
            com_erro += 1
            mostrar(linha, False, str(erro))
            if not testar:
                tabela.gravar(linha, "", "erro: %s" % erro)
            continue
        criados += 1
        avisos = []
        for anexo in anexos:
            try:
                cliente.anexar(chave, anexo)
            except (ErroJira, OSError) as erro:
                avisos.append("anexo %s não enviado (%s)" % (os.path.basename(anexo), erro))
        status = "criado" + ("; " + "; ".join(avisos) if avisos else "")
        tabela.gravar(linha, chave, status)  # grava já, para não criar de novo se algo parar no meio
        mostrar(linha, True, "%s · %s%s" % (chave, resumo, " (" + "; ".join(avisos) + ")" if avisos else ""))
    return criados, com_erro, pulados
