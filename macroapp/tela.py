"""Tela e teclado do terminal.

O histórico rola normalmente; a área viva no fim (caixa de entrada, sugestões,
progresso) é redesenhada. Uma linha é uma lista de trechos (texto, cor).
"""
import os
import shutil
import sys

DESTAQUE, FRACO, BOM, RUIM = "33", "90", "92", "91"


def _montar(partes, limite=0):
    """Texto com cores. Com limite, corta para a linha nunca quebrar sozinha."""
    saida, usado = [], 0
    for parte in partes:
        texto, cor = (parte, None) if isinstance(parte, str) else parte
        if limite and usado + len(texto) > limite:
            texto = texto[: limite - usado]
        if not texto:
            continue
        saida.append("\x1b[%sm%s\x1b[0m" % (cor, texto) if cor else texto)
        usado += len(texto)
    return "".join(saida)


class Tela:
    def __init__(self):
        self._linha_do_cursor = 0  # posição do cursor dentro da área viva
        if os.name == "nt":
            self._ligar_cores_no_windows()
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _ligar_cores_no_windows():
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetStdHandle.restype = ctypes.c_void_p
        kernel32.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel32.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        saida = kernel32.GetStdHandle(-11)
        modo = ctypes.c_ulong()
        if kernel32.GetConsoleMode(saida, ctypes.byref(modo)):
            kernel32.SetConsoleMode(saida, modo.value | 0x0004)  # sequências de cor e cursor
        kernel32.SetConsoleTitleW("Macro App")

    @property
    def largura(self):
        # Uma coluna a menos para o console nunca quebrar a linha sozinho.
        return max(24, shutil.get_terminal_size((80, 24)).columns) - 1

    def _voltar_ao_topo(self):
        subir = "\x1b[%dA" % self._linha_do_cursor if self._linha_do_cursor else ""
        self._linha_do_cursor = 0
        return subir + "\r"

    def imprimir(self, *partes):
        """Escreve uma linha no histórico, acima da área viva."""
        sys.stdout.write("\x1b[?25l" + self._voltar_ao_topo() + "\x1b[J" + _montar(partes) + "\n")
        sys.stdout.flush()

    def desenhar(self, linhas, cursor=None):
        """Redesenha a área viva. cursor = (linha, coluna); sem ele, o cursor fica escondido."""
        limite = self.largura
        saida = ["\x1b[?25l", self._voltar_ao_topo()]
        for indice, linha in enumerate(linhas):
            if indice:
                saida.append("\n")
            saida.append("\x1b[2K" + _montar(linha, limite))
        saida.append("\x1b[J")
        posicao = max(0, len(linhas) - 1)
        if cursor:
            linha, coluna = cursor
            if posicao > linha:
                saida.append("\x1b[%dA" % (posicao - linha))
            saida.append("\x1b[%dG\x1b[?25h" % (min(coluna, limite) + 1))
            posicao = linha
        else:
            saida.append("\r")
        self._linha_do_cursor = posicao
        sys.stdout.write("".join(saida))
        sys.stdout.flush()

    def limpar(self):
        sys.stdout.write("\x1b[2J\x1b[3J\x1b[H")
        self._linha_do_cursor = 0

    def sair(self):
        """Apaga a área viva e devolve o cursor, para o app sair limpo."""
        sys.stdout.write(self._voltar_ao_topo() + "\x1b[J\x1b[?25h\x1b[0m")
        sys.stdout.flush()


class Teclado:
    """Lê as teclas pendentes sem travar. Cada tecla é um nome ("enter", "esc",
    "cima"...) ou o próprio caractere digitado."""

    _ESPECIAIS_WINDOWS = {"H": "cima", "P": "baixo", "K": "esquerda", "M": "direita",
                          "G": "home", "O": "end", "S": "delete"}
    _CONTROLES = {"\r": "enter", "\n": "enter", "\x1b": "esc", "\t": "tab",
                  "\x08": "backspace", "\x7f": "backspace", "\x03": "ctrl-c"}
    _SEQUENCIAS = {"[A": "cima", "[B": "baixo", "[C": "direita", "[D": "esquerda",
                   "[H": "home", "[F": "end", "[1~": "home", "[4~": "end", "[3~": "delete",
                   "OH": "home", "OF": "end"}

    def __enter__(self):
        if os.name != "nt":
            import termios
            import tty

            self._arquivo = sys.stdin.fileno()
            self._modo_anterior = termios.tcgetattr(self._arquivo)
            tty.setcbreak(self._arquivo)
        return self

    def __exit__(self, *_):
        if os.name != "nt":
            import termios

            termios.tcsetattr(self._arquivo, termios.TCSADRAIN, self._modo_anterior)

    def ler(self):
        return self._ler_windows() if os.name == "nt" else self._ler_unix()

    def _ler_windows(self):
        import msvcrt

        teclas = []
        while msvcrt.kbhit():
            letra = msvcrt.getwch()
            if letra in ("\x00", "\xe0"):  # tecla especial: vem em dois passos
                tecla = self._ESPECIAIS_WINDOWS.get(msvcrt.getwch())
                if tecla:
                    teclas.append(tecla)
            elif letra in self._CONTROLES:
                teclas.append(self._CONTROLES[letra])
            elif letra.isprintable():
                teclas.append(letra)
        return teclas

    def _ler_unix(self):
        import select

        teclas = []
        if not select.select([self._arquivo], [], [], 0)[0]:
            return teclas
        texto = os.read(self._arquivo, 4096).decode("utf-8", "ignore")
        indice = 0
        while indice < len(texto):
            letra = texto[indice]
            indice += 1
            if letra == "\x1b":
                for sequencia, tecla in self._SEQUENCIAS.items():
                    if texto.startswith(sequencia, indice):
                        teclas.append(tecla)
                        indice += len(sequencia)
                        break
                else:
                    teclas.append("esc")
            elif letra in self._CONTROLES:
                teclas.append(self._CONTROLES[letra])
            elif letra.isprintable():
                teclas.append(letra)
        return teclas
