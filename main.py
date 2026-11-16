"""Horsch Terminal: terminal para executar macros do SAP GUI.

Abra com `python main.py` (ou pelo horsch-terminal.cmd). Só usa a biblioteca
padrão do Python 3.8 ou mais novo: não precisa instalar nenhum pacote.
"""
import os
import sys

from src import sap
from src.app import App

VERSAO = "0.6.0"


def main():
    # --simular executa as macros sem o SAP, para testar o app.
    sap.SIMULAR = "--simular" in sys.argv[1:]
    raiz = os.path.dirname(os.path.abspath(__file__))
    App(VERSAO, raiz).executar()


if __name__ == "__main__":
    main()
