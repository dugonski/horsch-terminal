"""Credenciais usadas pelos comandos /login (SAP) e /jira.

Os arquivos ficam na pasta do usuário do Windows, fora da pasta do app, e são
criados à mão por quem usa: o app só lê, nunca grava nem mostra senhas ou tokens.
"""
import configparser
import os

PASTA = os.path.join(os.path.expanduser("~"), ".horsch-terminal")
ARQUIVO = os.path.join(PASTA, "sap.ini")
ARQUIVO_JIRA = os.path.join(PASTA, "jira.ini")

MODELO = """[sap]
conexao = NOME DA CONEXAO COMO APARECE NO SAP LOGON
mandante = 100
usuario = SEU_USUARIO
senha = SUA_SENHA
idioma = PT"""

MODELO_JIRA = """[jira]
url = https://jira.horsch.com
token = SEU_TOKEN_PESSOAL"""

OBRIGATORIOS = ("conexao", "usuario", "senha")


class ErroCredenciais(Exception):
    """A primeira linha é o problema; as demais explicam como resolver."""


def _como_criar(arquivo, modelo):
    return "\n".join(
        ["Crie este arquivo com o Bloco de Notas:", "  " + arquivo, "Com este conteúdo:"]
        + ["  " + linha for linha in modelo.splitlines()]
    )


def _ler(arquivo, modelo, secao, obrigatorios, opcionais=()):
    if not os.path.isfile(arquivo):
        raise ErroCredenciais("Arquivo de credenciais não encontrado.\n" + _como_criar(arquivo, modelo))
    leitor = configparser.ConfigParser(interpolation=None, delimiters=("=",))
    try:
        with open(arquivo, encoding="utf-8-sig") as aberto:
            leitor.read_file(aberto)
        valores = leitor[secao]
    except (configparser.Error, KeyError, UnicodeDecodeError, OSError):
        raise ErroCredenciais("Não foi possível ler o arquivo de credenciais.\n" + _como_criar(arquivo, modelo))
    dados = {chave: valores.get(chave, "").strip() for chave in tuple(obrigatorios) + tuple(opcionais)}
    faltando = [chave for chave in obrigatorios if not dados[chave]]
    if faltando:
        raise ErroCredenciais("Falta preencher no arquivo de credenciais: %s\n  %s" % (", ".join(faltando), arquivo))
    return dados


def ler():
    """Credenciais do SAP: conexao, mandante, usuario, senha, idioma e saplogon."""
    return _ler(ARQUIVO, MODELO, "sap", OBRIGATORIOS, ("mandante", "idioma", "saplogon"))


def ler_jira():
    """Endereço do Jira e token pessoal (Perfil > Personal Access Tokens)."""
    return _ler(ARQUIVO_JIRA, MODELO_JIRA, "jira", ("url", "token"))
