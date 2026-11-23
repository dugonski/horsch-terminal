"""Abre no navegador o PDF de cada part number pela MD04."""

COMANDO = "pdfs"
TITULO = "PDFs MD04"
DESCRICAO = "Abre no navegador o PDF de cada part number (MD04, centro 8500)"
ROTULO = "part numbers"
SUCESSO = "PDF aberto"

CENTRO = "8500"
CAMPOS = "wnd[0]/usr/tabsTAB300/tabpF01/ssubINCLUDE300:SAPMM61R:0301/"


def inicio(sap):
    """Roda uma vez, antes do primeiro item. Abre a MD04 numa janela nova do SAP,
    para não mexer na janela em que você está trabalhando. Todos os itens rodam
    nessa janela nova."""
    return sap.nova_janela("md04")


def fim(sap):
    """Roda uma vez no fim, mesmo se algum item falhar ou se a execução for
    cancelada: fecha a janela nova."""
    sap.fechar()


def por_item(sap, material):
    """Roda para cada item da lista. Se der erro, o item é marcado como falha
    e o app segue para o próximo."""
    sap.texto("wnd[0]/tbar[0]/okcd", "/nmd04")
    sap.tecla("wnd[0]", 0)

    sap.texto(CAMPOS + "ctxtRM61R-MATNR", material)
    sap.texto(CAMPOS + "ctxtRM61R-WERKS", CENTRO)
    sap.tecla("wnd[0]", 0)
    sap.conferir_status()

    sap.tecla("wnd[0]", 2)
    sap.botao("wnd[0]/titl/shellcont[1]/shell", "ZZZ_VIEW")

    # Volta para a tela inicial; o próximo item recomeça com /nmd04 de qualquer forma.
    for _ in range(3):
        sap.clicar("wnd[0]/tbar[0]/btn[3]", ignorar_erro=True)
