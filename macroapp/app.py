"""O terminal do app: lê comandos, recebe a lista e acompanha a execução."""
import glob
import importlib.util
import os
import platform
import re
import struct
import time

from . import sap
from .tela import BOM, DESTAQUE, FRACO, RUIM, Teclado, Tela

DICA = "Digite / para ver os comandos · /ajuda para ajuda"


class Comando:
    def __init__(self, nome, descricao, macro=None):
        self.nome, self.descricao, self.macro = nome, descricao, macro


def carregar_macros(pasta):
    """Cada arquivo .py em macros/ é uma macro (veja macros/pdfs_md04.py)."""
    macros = []
    for caminho in sorted(glob.glob(os.path.join(pasta, "*.py"))):
        nome = os.path.splitext(os.path.basename(caminho))[0]
        if nome.startswith("_"):
            continue
        especificacao = importlib.util.spec_from_file_location("macros_" + nome, caminho)
        modulo = importlib.util.module_from_spec(especificacao)
        especificacao.loader.exec_module(modulo)
        macros.append(modulo)
    return macros


class App:
    def __init__(self, versao, raiz):
        bits = struct.calcsize("P") * 8
        self.versao = "%s (%d bits)" % (versao, bits)
        self.tela = Tela()
        self.comandos = [Comando(m.COMANDO, m.DESCRICAO, m) for m in carregar_macros(os.path.join(raiz, "macros"))]
        self.comandos += [
            Comando("ajuda", "Mostra os comandos disponíveis"),
            Comando("diagnostico", "Testa a conexão com o SAP passo a passo"),
            Comando("limpar", "Limpa a tela"),
            Comando("sair", "Fecha o app"),
        ]
        self.coluna = max(len(c.nome) for c in self.comandos)

        self.sair = False
        self.texto = ""
        self.cursor = 0
        self.escolhida = 0      # sugestão destacada
        self.ativa = None       # macro recebendo a lista
        self.itens = []
        self.ultima_tecla = 0.0

    # ---- laço principal ----

    def executar(self):
        with Teclado() as teclado:
            self.teclado = teclado
            try:
                self.imprimir_faixa()
                largura, redesenhar = 0, True
                while not self.sair:
                    for tecla in teclado.ler():
                        agora = time.monotonic()
                        desde = agora - self.ultima_tecla
                        self.ultima_tecla = agora
                        redesenhar = True
                        if tecla == "ctrl-c":
                            self.sair = True
                        elif self.ativa:
                            self.tecla_na_lista(tecla, desde)
                        else:
                            self.tecla_no_comando(tecla)
                        if self.sair:
                            break
                    if self.sair:
                        break
                    if largura != self.tela.largura:
                        largura, redesenhar = self.tela.largura, True
                    if redesenhar:
                        self.desenhar_entrada()
                        redesenhar = False
                    time.sleep(0.02)
            except KeyboardInterrupt:
                pass
            finally:
                self.tela.sair()

    def imprimir_faixa(self):
        titulo = [("│ ", DESTAQUE), ("* Macro App", DESTAQUE), ("  v" + self.versao, FRACO)]
        usado = 14 + len(self.versao)
        if sap.SIMULAR:
            titulo.append(("  [simulação]", RUIM))
            usado += 13
        titulo.append((" " * (len(DICA) - usado) + " │", DESTAQUE))
        barra = "─" * (len(DICA) + 2)
        self.tela.imprimir(("┌" + barra + "┐", DESTAQUE))
        self.tela.imprimir(*titulo)
        self.tela.imprimir(("│ ", DESTAQUE), (DICA, FRACO), (" │", DESTAQUE))
        self.tela.imprimir(("└" + barra + "┘", DESTAQUE))
        self.tela.imprimir()

    # ---- teclado ----

    def definir_texto(self, novo):
        self.texto, self.cursor, self.escolhida = novo, len(novo), 0

    def editar_texto(self, tecla):
        """Edição básica da linha. Devolve True se o texto mudou."""
        if tecla == "esquerda":
            self.cursor = max(0, self.cursor - 1)
        elif tecla == "direita":
            self.cursor = min(len(self.texto), self.cursor + 1)
        elif tecla == "home":
            self.cursor = 0
        elif tecla == "end":
            self.cursor = len(self.texto)
        elif tecla == "backspace" and self.cursor > 0:
            self.texto = self.texto[: self.cursor - 1] + self.texto[self.cursor:]
            self.cursor -= 1
            return True
        elif tecla == "delete" and self.cursor < len(self.texto):
            self.texto = self.texto[: self.cursor] + self.texto[self.cursor + 1:]
            return True
        elif len(tecla) == 1:
            self.texto = self.texto[: self.cursor] + tecla + self.texto[self.cursor:]
            self.cursor += 1
            return True
        return False

    def sugestoes(self):
        if self.ativa or not self.texto.startswith("/") or re.search(r"\s", self.texto):
            return []
        prefixo = self.texto[1:].lower()
        return [c for c in self.comandos if c.nome.startswith(prefixo)]

    def tecla_no_comando(self, tecla):
        sugestoes = self.sugestoes()
        escolha = sugestoes[min(self.escolhida, len(sugestoes) - 1)] if sugestoes else None
        if tecla == "cima":
            if escolha:
                self.escolhida = (self.escolhida - 1) % len(sugestoes)
        elif tecla == "baixo":
            if escolha:
                self.escolhida = (self.escolhida + 1) % len(sugestoes)
        elif tecla == "tab":
            if escolha:
                self.definir_texto("/%s " % escolha.nome)
        elif tecla == "esc":
            self.definir_texto("")
        elif tecla == "enter":
            linha = "/" + escolha.nome if escolha else self.texto.strip()
            self.definir_texto("")
            if linha:
                self.executar_comando(linha)
        elif self.editar_texto(tecla):
            self.escolhida = 0

    def tecla_na_lista(self, tecla, desde_anterior):
        if tecla == "esc":
            self.voltar_ao_comando()
            self.tela.imprimir(("  Cancelado.", FRACO))
            self.tela.imprimir()
        elif tecla == "enter":
            linha = self.texto.strip()
            self.definir_texto("")
            if linha:
                self.adicionar_itens(linha)
            # Linha em branco no meio de uma colagem não deve disparar a macro.
            elif self.itens and desde_anterior >= 0.15:
                self.executar_macro()
        else:
            self.editar_texto(tecla)

    # ---- comandos ----

    def voltar_ao_comando(self):
        self.ativa, self.itens = None, []
        self.definir_texto("")

    def adicionar_itens(self, texto):
        """Separa por espaço, vírgula, ponto e vírgula ou quebra de linha, sem repetir."""
        for item in re.split(r"[\s,;]+", texto):
            if item and item not in self.itens:
                self.itens.append(item)

    def executar_comando(self, linha):
        self.tela.imprimir(("> ", DESTAQUE), linha)
        partes = linha.split(None, 1)
        if not partes[0].startswith("/"):
            self.tela.imprimir(("  Os comandos começam com /. Digite /ajuda para ver a lista.", FRACO))
            self.tela.imprimir()
            return

        nome = partes[0][1:].lower()
        comando = next((c for c in self.comandos if c.nome == nome), None)
        if comando is None:
            self.tela.imprimir(("  Comando desconhecido: " + partes[0], RUIM), (" · /ajuda mostra a lista", FRACO))
            self.tela.imprimir()
        elif comando.macro:
            self.ativa = comando.macro
            if len(partes) > 1:
                self.adicionar_itens(partes[1])
            if self.itens:
                self.executar_macro()
        elif nome == "ajuda":
            for c in self.comandos:
                self.tela.imprimir(("  /" + c.nome.ljust(self.coluna), DESTAQUE), "  " + c.descricao)
            self.tela.imprimir()
            self.tela.imprimir(("  Dica: a lista pode ir junto do comando, ex.: /pdfs 12345 67890", FRACO))
            self.tela.imprimir()
        elif nome == "diagnostico":
            self.diagnosticar()
        elif nome == "limpar":
            self.tela.limpar()
            self.imprimir_faixa()
        elif nome == "sair":
            self.sair = True

    def diagnosticar(self):
        self.tela.imprimir(("  App v%s · Python %s · %s" % (self.versao, platform.python_version(), platform.platform()), FRACO))
        self.mostrar_andamento("Testando a conexão com o SAP...", cancelavel=False)
        for passo, resultado, ok in sap.diagnosticar():
            self.tela.imprimir(("  √ " if ok else "  × ", BOM if ok else RUIM), passo, ("  " + resultado, FRACO))
        self.tela.imprimir()

    # ---- execução ----

    def mostrar_andamento(self, texto, cancelavel=True):
        linha = [("  » ", DESTAQUE), texto]
        if cancelavel:
            linha.append(("   Esc para cancelar", FRACO))
        self.tela.desenhar([linha])

    def pediu_cancelamento(self):
        """Esc cancela entre um item e outro; Ctrl+C fecha o app."""
        teclas = self.teclado.ler()
        if "ctrl-c" in teclas:
            self.sair = True
        return "esc" in teclas or "ctrl-c" in teclas

    def executar_macro(self):
        macro, itens = self.ativa, list(self.itens)
        total, feitos, falhas = len(itens), 0, []
        cancelado, erro_geral = False, None

        self.tela.imprimir("  " + macro.TITULO, (" · %d %s" % (total, macro.ROTULO), FRACO))
        self.mostrar_andamento("Conectando ao SAP...")
        try:
            sessao = sap.conectar()
            if hasattr(macro, "inicio"):
                macro.inicio(sessao)
        except Exception as erro:
            erro_geral = str(erro)

        if erro_geral is None:
            for indice, item in enumerate(itens, 1):
                try:
                    if self.pediu_cancelamento():
                        cancelado = True
                        break
                    self.mostrar_andamento("Processando %d/%d · %s" % (indice, total, item))
                    macro.por_item(sessao, item)
                    feitos += 1
                    self.tela.imprimir(("  √ ", BOM), item, ("  " + getattr(macro, "SUCESSO", "ok"), FRACO))
                except KeyboardInterrupt:
                    cancelado = True
                    break
                except Exception as erro:
                    falhas.append(item)
                    self.tela.imprimir(("  × ", RUIM), item, ("  %s" % erro, RUIM))

        if erro_geral is not None:
            self.tela.imprimir(("  × " + erro_geral, RUIM))
        elif cancelado:
            self.tela.imprimir(("  Cancelado · %d concluídos de %d" % (feitos, total), FRACO))
        elif not falhas:
            self.tela.imprimir(("  Concluído · %d de %d" % (feitos, total), BOM))
        else:
            self.tela.imprimir("  Concluído · ", ("%d com sucesso" % feitos, BOM), " · ", ("%d com falha" % len(falhas), RUIM))
            self.tela.imprimir(("  Falharam: " + ", ".join(falhas), FRACO))
        self.tela.imprimir()
        self.voltar_ao_comando()

    # ---- tela ----

    def desenhar_entrada(self):
        linhas = []
        na_lista = self.ativa is not None
        if na_lista:
            linhas.append(["  " + self.ativa.TITULO, (" · %d %s na lista" % (len(self.itens), self.ativa.ROTULO), FRACO)])

        # caixa de entrada: mostra o trecho do texto em volta do cursor
        borda = DESTAQUE if na_lista else FRACO
        interno = self.tela.largura - 4
        espaco = interno - 2
        inicio = max(0, self.cursor - espaco + 1)
        visivel = self.texto[inicio: inicio + espaco]
        linha_da_entrada = len(linhas) + 1
        linhas.append([("┌" + "─" * (interno + 2) + "┐", borda)])
        linhas.append([("│ ", borda), ("+ " if na_lista else "> ", DESTAQUE), visivel.ljust(espaco), (" │", borda)])
        linhas.append([("└" + "─" * (interno + 2) + "┘", borda)])

        sugestoes = self.sugestoes()
        if na_lista:
            dica = "  Cole ou digite os %s e tecle Enter · Esc cancela" % self.ativa.ROTULO
            if self.itens:
                dica = "  Enter com a linha vazia executa · Esc cancela"
            linhas.append([(dica, FRACO)])
        elif not sugestoes:
            linhas.append([("  / para comandos · Ctrl+C para sair", FRACO)])
        for indice, comando in enumerate(sugestoes):
            nome = "  /" + comando.nome.ljust(self.coluna) + "  "
            if indice == min(self.escolhida, len(sugestoes) - 1):
                linhas.append([(nome, DESTAQUE), comando.descricao])
            else:
                linhas.append([(nome + comando.descricao, FRACO)])

        self.tela.desenhar(linhas, (linha_da_entrada, 4 + self.cursor - inicio))
