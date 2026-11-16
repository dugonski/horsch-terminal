"""Preferências de aparência, guardadas na pasta do usuário do Windows."""
import configparser
import os

from . import logo
from .credenciais import PASTA

ARQUIVO = os.path.join(PASTA, "preferencias.ini")


def ler_estilo_do_logo():
    leitor = configparser.ConfigParser()
    try:
        leitor.read(ARQUIVO, encoding="utf-8-sig")
        estilo = leitor.get("aparencia", "logo", fallback="").strip().lower()
    except (configparser.Error, OSError, UnicodeDecodeError):
        estilo = ""
    return estilo if estilo in logo.ESTILOS else logo.ESTILOS[0]


def salvar_estilo_do_logo(estilo):
    """Devolve False se não foi possível gravar (a escolha vale só até fechar o app)."""
    leitor = configparser.ConfigParser()
    leitor["aparencia"] = {"logo": estilo}
    try:
        os.makedirs(PASTA, exist_ok=True)
        with open(ARQUIVO, "w", encoding="utf-8") as arquivo:
            leitor.write(arquivo)
        return True
    except OSError:
        return False
