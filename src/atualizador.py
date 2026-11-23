"""Atualização do app a partir do GitHub (comando /atualizar)."""
import io
import os
import re
import urllib.error
import urllib.request
import zipfile

from .credenciais import PASTA

REPOSITORIO = "dugonski/Horsch-terminal"
RAMO = "main"
URL_VERSAO = "https://raw.githubusercontent.com/%s/%s/main.py" % (REPOSITORIO, RAMO)
URL_PACOTE = "https://codeload.github.com/%s/zip/refs/heads/%s" % (REPOSITORIO, RAMO)

# O atalho está rodando enquanto o app está aberto; trocar um .cmd durante a execução
# confunde o Windows, então ele nunca é trocado pelo /atualizar.
LANCADOR = "horsch-terminal.cmd"


class ErroAtualizacao(Exception):
    pass


def _atualizavel(caminho):
    """Só o código do app é trocado. Macros novas que você criou em macros/ e as suas
    configurações (na pasta do usuário) não são tocadas."""
    partes = caminho.split("/")
    if caminho in ("main.py", "README.md"):
        return True
    return len(partes) == 2 and partes[0] in ("src", "macros") and partes[1].endswith(".py")


def _baixar(url):
    pedido = urllib.request.Request(url, headers={"User-Agent": "horsch-terminal"})
    try:
        with urllib.request.urlopen(pedido, timeout=30) as resposta:
            return resposta.read()
    except urllib.error.HTTPError as erro:
        if erro.code == 404:
            raise ErroAtualizacao("versão não encontrada no GitHub (o repositório pode estar privado ou ter mudado de nome)")
        raise ErroAtualizacao("o GitHub respondeu com erro %d" % erro.code)
    except (urllib.error.URLError, OSError) as erro:
        raise ErroAtualizacao("sem acesso ao GitHub (%s); a rede da empresa pode estar bloqueando" % getattr(erro, "reason", erro))


def _numeros(versao):
    return tuple(int(numero) for numero in re.findall(r"\d+", versao))


def versao_do_codigo(texto):
    encontrada = re.search(r'^VERSAO\s*=\s*"([^"]+)"', texto, re.M)
    return encontrada.group(1) if encontrada else None


def versao_publicada():
    versao = versao_do_codigo(_baixar(URL_VERSAO).decode("utf-8", "replace"))
    if not versao:
        raise ErroAtualizacao("não foi possível ler a versão publicada no GitHub")
    return versao


def mais_nova(publicada, local):
    return _numeros(publicada) > _numeros(local)


def instalar(raiz, versao_local):
    """Baixa a versão publicada e troca os arquivos que mudaram.

    Devolve (arquivos_trocados, lancador_mudou). Antes de trocar, guarda uma cópia
    de cada arquivo em ~/.horsch-terminal/backup/v<versão atual>. Os arquivos novos
    são todos gravados primeiro e só depois colocados no lugar, para uma falha no
    meio não deixar o app com metade dos arquivos de cada versão."""
    try:
        pacote = zipfile.ZipFile(io.BytesIO(_baixar(URL_PACOTE)))
    except zipfile.BadZipFile:
        raise ErroAtualizacao("o arquivo baixado do GitHub está corrompido")

    novos = {}
    for info in pacote.infolist():
        if info.is_dir():
            continue
        _, _, caminho = info.filename.partition("/")  # o zip do GitHub tem uma pasta-raiz
        if _atualizavel(caminho) or caminho == LANCADOR:
            novos[caminho] = pacote.read(info)
    if "main.py" not in novos:
        raise ErroAtualizacao("o pacote baixado não parece ser do Horsch Terminal")

    trocar, lancador_mudou = [], False
    for caminho, conteudo in sorted(novos.items()):
        destino = os.path.join(raiz, *caminho.split("/"))
        atual = None
        if os.path.isfile(destino):
            with open(destino, "rb") as arquivo:
                atual = arquivo.read()
        if atual == conteudo:
            continue
        if caminho == LANCADOR:
            lancador_mudou = True
            continue
        trocar.append((caminho, destino, atual, conteudo))

    backup = os.path.join(PASTA, "backup", "v" + versao_local)
    try:
        for caminho, destino, atual, conteudo in trocar:
            if atual is not None:
                copia = os.path.join(backup, *caminho.split("/"))
                os.makedirs(os.path.dirname(copia), exist_ok=True)
                with open(copia, "wb") as arquivo:
                    arquivo.write(atual)
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            with open(destino + ".novo", "wb") as arquivo:
                arquivo.write(conteudo)
        for _, destino, _, _ in trocar:
            os.replace(destino + ".novo", destino)
    except OSError as erro:
        for _, destino, _, _ in trocar:
            try:
                os.remove(destino + ".novo")
            except OSError:
                pass
        raise ErroAtualizacao("não foi possível gravar os arquivos do app (%s)" % erro)
    return [caminho for caminho, _, _, _ in trocar], lancador_mudou
