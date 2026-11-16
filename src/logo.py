"""Desenho do banner: HORSCH como na logo.

Tudo é desenhado em pontos numa grade; cada ponto tem uma cor ou está vazio.
Duas linhas de pontos viram uma linha de texto, usando meios-blocos.
"""
from .tela import VERMELHO_HORSCH

BRANCO = "255;255;255"
ESTILOS = ("fill", "hollow")

ALTURA = 10  # em pontos: 8 das letras e 1 de margem em cima e embaixo

# # = ponto aceso
LETRAS = {
    "H": ["##...##", "##...##", "##...##", "#######", "#######", "##...##", "##...##", "##...##"],
    "O": [".#####.", "#######", "##...##", "##...##", "##...##", "##...##", "#######", ".#####."],
    "R": ["######.", "#######", "##...##", "#######", "######.", "##..##.", "##...##", "##...##"],
    "S": [".######", "#######", "##.....", "######.", ".######", ".....##", "#######", "######."],
    "C": [".######", "#######", "##.....", "##.....", "##.....", "##.....", "#######", ".######"],
}
VIZINHOS = ((-1, 0), (1, 0), (0, -1), (0, 1))


def _pontos_das_letras(palavra, vao, inclinacao=3):
    """Conjunto de (linha, coluna) acesos e a largura ocupada. As letras são
    inclinadas: cada linha de texto começa uma coluna à direita da de baixo."""
    acesos = set()
    largura = 0
    for linha in range(8):
        texto = (" " * vao).join(LETRAS[letra][linha] for letra in palavra)
        recuo = (7 - linha) // 2 * inclinacao // 3
        largura = len(texto) + inclinacao
        acesos.update((linha, recuo + coluna) for coluna, ponto in enumerate(texto) if ponto == "#")
    return acesos, largura


def _grade(estilo):
    if estilo == "hollow":
        # Só o contorno das letras, em vermelho; por dentro e por fora fica vazio.
        margem = 1
        letras, largura_das_letras = _pontos_das_letras("HORSCH", vao=4)
    else:
        # Retângulo vermelho preenchido com as letras em branco.
        margem = 3
        letras, largura_das_letras = _pontos_das_letras("HORSCH", vao=2)
    letras = {(linha + 1, coluna + margem) for linha, coluna in letras}
    largura = largura_das_letras + 2 * margem
    grade = [[None] * largura for _ in range(ALTURA)]
    for linha in range(ALTURA):
        for coluna in range(largura):
            if estilo == "hollow":
                apagado = (linha, coluna) not in letras
                if apagado and any((linha + a, coluna + b) in letras for a, b in VIZINHOS):
                    grade[linha][coluna] = VERMELHO_HORSCH
            else:
                grade[linha][coluna] = BRANCO if (linha, coluna) in letras else VERMELHO_HORSCH
    return grade


def montar(estilo="fill"):
    """Linhas do banner, cada uma como lista de trechos (texto, cor) para a Tela."""
    grade = _grade(estilo)
    linhas = []
    for linha in range(0, ALTURA, 2):
        trechos = []
        for cima, baixo in zip(grade[linha], grade[linha + 1]):
            if cima is None and baixo is None:
                letra, cor = " ", None
            elif baixo is None:
                letra, cor = "▀", "38;2;" + cima
            elif cima is None:
                letra, cor = "▄", "38;2;" + baixo
            elif cima == baixo:
                letra, cor = "█", "38;2;" + cima
            else:
                letra, cor = "▀", "38;2;%s;48;2;%s" % (cima, baixo)
            if trechos and trechos[-1][1] == cor:
                trechos[-1] = (trechos[-1][0] + letra, cor)
            else:
                trechos.append((letra, cor))
        linhas.append(trechos)
    return linhas


def largura(estilo="fill"):
    return len(_grade(estilo)[0])
