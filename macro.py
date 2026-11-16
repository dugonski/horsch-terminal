"""Macro App: terminal para executar macros do SAP GUI.

Abra com `python macro.py` (ou pelo macro.cmd). Só usa a biblioteca padrão do
Python 3.8 ou mais novo: não precisa instalar nenhum pacote.
"""
import os
import sys

from macroapp import sap
from macroapp.app import App

VERSAO = "0.2.0"


def main():
    # --simular executa as macros sem o SAP, para testar o app.
    sap.SIMULAR = "--simular" in sys.argv[1:]
    raiz = os.path.dirname(os.path.abspath(__file__))
    App(VERSAO, raiz).executar()


if __name__ == "__main__":
    main()
