"""O terminal do app: lê comandos, recebe a lista e acompanha a execução."""
import glob
import importlib.util
import os
import platform
import re
import struct
import time

from . import atualizador, credenciais, historico, logo, preferencias, sap
from .tela import BOM, DESTAQUE, FRACO, RUIM, TITULO, Teclado, Tela

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
        self.versao_numero, self.raiz = versao, raiz
        self.tela = Tela()
        self.comandos = [Comando(m.COMANDO, m.DESCRICAO, m) for m in carregar_macros(os.path.join(raiz, "macros"))]
        self.comandos += [
            Comando("login", "Abre o SAP e faz login com as credenciais salvas"),
            Comando("customizar", "Muda o estilo da logo: /customizar fill ou /customizar hollow"),
            Comando("atualizar", "Baixa e instala a versão mais nova do app"),
            Comando("ajuda", "Mostra os comandos disponíveis"),
            Comando("diagnostico", "Testa a conexão com o SAP passo a passo"),
            Comando("limpar", "Limpa a tela"),
            Comando("sair", "Fecha o app"),
        ]
        self.coluna = max(len(c.nome) for c in self.comandos)

        self.estilo_do_logo = preferencias.ler_estilo_do_logo()
        self.sair = False
        self.texto = ""
        self.cursor = 0
        self.escolhida = 0      # sugestão destacada
        self.historico = historico.ler()
        self.pos_historico = None  # posição ao navegar com as setas; None = digitando
        self.rascunho = ""         # o que estava digitado antes de navegar
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
                        if largura:
                            self.tela.redimensionar()
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
        # Em janela estreita demais para o desenho, fica só o texto.
        if logo.largura(self.estilo_do_logo) <= self.tela.largura:
            for linha in logo.montar(self.estilo_do_logo):
                self.tela.imprimir(*linha, cortar=True)
            self.tela.imprimir()
        legenda = [("Horsch Terminal", TITULO), ("  v" + self.versao, FRACO)]
        if sap.SIMULAR:
            legenda.append(("  [simulação]", RUIM))
        self.tela.imprimir(*legenda)
        self.tela.imprimir((DICA, FRACO))
        self.tela.imprimir()

    # ---- teclado ----

    def definir_texto(self, novo):
        self.texto, self.cursor, self.escolhida = novo, len(novo), 0
        self.pos_historico = None

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
        if self.pos_historico is not None:
            return []  # navegando pelo histórico: as setas continuam no histórico
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
            else:
                self.historico_anterior()
        elif tecla == "baixo":
            if escolha:
                self.escolhida = (self.escolhida + 1) % len(sugestoes)
            else:
                self.historico_seguinte()
        elif tecla == "tab":
            if escolha:
                self.definir_texto("/%s " % escolha.nome)
        elif tecla == "esc":
            self.definir_texto("")
        elif tecla == "enter":
            linha = "/" + escolha.nome if escolha else self.texto.strip()
            self.definir_texto("")
            if linha:
                historico.adicionar(self.historico, linha)
                self.executar_comando(linha)
        elif self.editar_texto(tecla):
            self.escolhida = 0
            self.pos_historico = None

    def historico_anterior(self):
        if not self.historico:
            return
        if self.pos_historico is None:
            self.rascunho = self.texto
            self.pos_historico = len(self.historico)
        if self.pos_historico > 0:
            self.pos_historico -= 1
        self.mostrar_no_campo(self.historico[self.pos_historico])

    def historico_seguinte(self):
        if self.pos_historico is None:
            return
        self.pos_historico += 1
        if self.pos_historico >= len(self.historico):
            self.pos_historico = None
            self.mostrar_no_campo(self.rascunho)
        else:
            self.mostrar_no_campo(self.historico[self.pos_historico])

    def mostrar_no_campo(self, texto):
        self.texto, self.cursor, self.escolhida = texto, len(texto), 0

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
        elif nome == "login":
            self.fazer_login()
        elif nome == "customizar":
            self.customizar(partes[1].strip().lower() if len(partes) > 1 else "")
        elif nome == "atualizar":
            self.atualizar()
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

    def customizar(self, estilo):
        """/customizar fill ou /customizar hollow"""
        if estilo not in logo.ESTILOS:
            self.tela.imprimir(("  Estilo atual da logo: ", FRACO), self.estilo_do_logo)
            self.tela.imprimir(("  /customizar fill  ", DESTAQUE), "  retângulo vermelho preenchido, letras brancas")
            self.tela.imprimir(("  /customizar hollow", DESTAQUE), "  só o contorno das letras em vermelho")
            self.tela.imprimir()
            return
        self.estilo_do_logo = estilo
        gravou = preferencias.salvar_estilo_do_logo(estilo)
        self.tela.limpar()
        self.imprimir_faixa()
        if not gravou:
            self.tela.imprimir(("  Não foi possível salvar a preferência; ela vale só até fechar o app.", FRACO))
            self.tela.imprimir()

    def atualizar(self):
        self.mostrar_andamento("Procurando versão nova no GitHub...", cancelavel=False)
        try:
            publicada = atualizador.versao_publicada()
            if not atualizador.mais_nova(publicada, self.versao_numero):
                self.tela.imprimir(("  √ ", BOM), "Você já está na versão mais nova", ("  v" + self.versao_numero, FRACO))
                self.tela.imprimir()
                return
            self.mostrar_andamento("Baixando a v%s..." % publicada, cancelavel=False)
            trocados, lancador_mudou = atualizador.instalar(self.raiz, self.versao_numero)
        except atualizador.ErroAtualizacao as erro:
            self.tela.imprimir(("  × %s" % erro, RUIM))
            self.tela.imprimir()
            return
        self.tela.imprimir(("  √ ", BOM), "Atualizado da v%s para a v%s" % (self.versao_numero, publicada),
                           ("  %d arquivos" % len(trocados), FRACO))
        self.tela.imprimir(("  Feche e abra o app de novo para usar a versão nova.", TITULO))
        if lancador_mudou:
            self.tela.imprimir(("  O atalho horsch-terminal.cmd também mudou e não pode ser trocado com o app aberto:", FRACO))
            self.tela.imprimir(("  baixe o zip completo do GitHub para atualizá-lo.", FRACO))
        self.tela.imprimir()

    def fazer_login(self):
        try:
            dados = credenciais.ler()
        except credenciais.ErroCredenciais as erro:
            problema, _, como_resolver = str(erro).partition("\n")
            self.tela.imprimir(("  × " + problema, RUIM))
            for linha in como_resolver.splitlines():
                self.tela.imprimir(("  " + linha, FRACO))
            self.tela.imprimir()
            return

        def avisar(texto):
            self.mostrar_andamento(texto, cancelavel=False)

        avisar("Conectando ao SAP...")
        try:
            self.tela.imprimir(("  √ ", BOM), sap.fazer_login(dados, avisar))
        except Exception as erro:
            self.tela.imprimir(("  × %s" % erro, RUIM))
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

        self.tela.imprimir(("  " + macro.TITULO, TITULO), (" · %d %s" % (total, macro.ROTULO), FRACO))
        self.mostrar_andamento("Conectando ao SAP...")
        # inicio() pode devolver outra sessão (uma janela nova) para os itens rodarem nela;
        # fim() roda sempre que inicio() deu certo, mesmo com falha ou cancelamento.
        sessao, preparada, aviso_do_fim = None, False, None
        try:
            sessao = sap.conectar()
            if hasattr(macro, "inicio"):
                self.mostrar_andamento("Preparando o SAP...", cancelavel=False)
                sessao = macro.inicio(sessao) or sessao
            preparada = True
        except Exception as erro:
            erro_geral = str(erro)

        try:
            if preparada:
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
        finally:
            if preparada and hasattr(macro, "fim"):
                self.mostrar_andamento("Finalizando...", cancelavel=False)
                try:
                    macro.fim(sessao)
                except Exception as erro:
                    aviso_do_fim = str(erro)

        if aviso_do_fim:
            self.tela.imprimir(("  × Ao finalizar: " + aviso_do_fim, RUIM))
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
            linhas.append([("  " + self.ativa.TITULO, TITULO), (" · %d %s na lista" % (len(self.itens), self.ativa.ROTULO), FRACO)])

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
