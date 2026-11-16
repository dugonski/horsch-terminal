"""Credenciais do SAP usadas pelo comando /login.

O arquivo fica na pasta do usuário do Windows, fora da pasta do app, e é criado
à mão por quem usa: o app só lê, nunca grava nem mostra a senha.
"""
import configparser
import os

PASTA = os.path.join(os.path.expanduser("~"), ".horsch-terminal")
ARQUIVO = os.path.join(PASTA, "sap.ini")

MODELO = """[sap]
conexao = NOME DA CONEXAO COMO APARECE NO SAP LOGON
mandante = 100
usuario = SEU_USUARIO
senha = SUA_SENHA
idioma = PT"""

OBRIGATORIOS = ("conexao", "usuario", "senha")


class ErroCredenciais(Exception):
    """A primeira linha é o problema; as demais explicam como resolver."""


def _como_criar():
    return "\n".join(
        ["Crie este arquivo com o Bloco de Notas:", "  " + ARQUIVO, "Com este conteúdo:"]
        + ["  " + linha for linha in MODELO.splitlines()]
    )


def ler():
    """Devolve um dicionário com conexao, mandante, usuario, senha, idioma e saplogon."""
    if not os.path.isfile(ARQUIVO):
        raise ErroCredenciais("Arquivo de credenciais não encontrado.\n" + _como_criar())

    leitor = configparser.ConfigParser(interpolation=None, delimiters=("=",))
    try:
        with open(ARQUIVO, encoding="utf-8-sig") as arquivo:
            leitor.read_file(arquivo)
        secao = leitor["sap"]
    except (configparser.Error, KeyError, UnicodeDecodeError, OSError):
        raise ErroCredenciais("Não foi possível ler o arquivo de credenciais.\n" + _como_criar())

    dados = {chave: secao.get(chave, "").strip() for chave in OBRIGATORIOS + ("mandante", "idioma", "saplogon")}
    faltando = [chave for chave in OBRIGATORIOS if not dados[chave]]
    if faltando:
        raise ErroCredenciais(
            "Falta preencher no arquivo de credenciais: %s\n  %s" % (", ".join(faltando), ARQUIVO)
        )
    return dados
