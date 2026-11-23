"""Histórico dos comandos digitados, para navegar com as setas.

Fica em ~/.horsch-terminal/historico.txt e sobrevive entre uma abertura e outra.
"""
import os

from .credenciais import PASTA

ARQUIVO = os.path.join(PASTA, "historico.txt")
MAXIMO = 200


def ler():
    try:
        with open(ARQUIVO, encoding="utf-8") as arquivo:
            linhas = [linha.rstrip("\r\n") for linha in arquivo]
    except (OSError, UnicodeDecodeError):
        return []
    return [linha for linha in linhas if linha.strip()][-MAXIMO:]


def adicionar(historico, linha):
    """Acrescenta a linha (sem repetir a última) e grava. Falha ao gravar é ignorada:
    o histórico continua valendo até fechar o app."""
    if not linha.strip() or (historico and historico[-1] == linha):
        return
    historico.append(linha)
    del historico[:-MAXIMO]
    try:
        os.makedirs(PASTA, exist_ok=True)
        with open(ARQUIVO, "w", encoding="utf-8") as arquivo:
            arquivo.write("\n".join(historico) + "\n")
    except OSError:
        pass
