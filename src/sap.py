"""Conexão com a sessão aberta do SAP GUI (SAP GUI Scripting).

Fala com o SAP do mesmo jeito que o VBA: chamando métodos pelo nome (IDispatch).
É feito só com ctypes, da biblioteca padrão, e não carrega a biblioteca de tipos
do SAP GUI, que em algumas máquinas não abre fora do VBA.
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import POINTER, byref, c_long, c_uint, c_ulong, c_ushort, c_void_p, c_wchar_p

# Troca o SAP real por uma sessão falsa (para testar o app sem SAP).
SIMULAR = False

NAO_ENCONTRADO = "SAP não encontrado: abra o SAP e faça login antes de executar"


class ErroSap(Exception):
    pass


# ---------------------------------------------------------------------------
# COM por ctypes
# ---------------------------------------------------------------------------

class _Guid(ctypes.Structure):
    _fields_ = [("d1", c_ulong), ("d2", c_ushort), ("d3", c_ushort), ("d4", ctypes.c_ubyte * 8)]


class _Par(ctypes.Structure):
    _fields_ = [("a", c_void_p), ("b", c_void_p)]


class _Valor(ctypes.Union):
    _fields_ = [
        ("llVal", ctypes.c_longlong),
        ("lVal", c_long),
        ("iVal", ctypes.c_short),
        ("dblVal", ctypes.c_double),
        ("ptr", c_void_p),
        ("par", _Par),  # só para a união ter o tamanho certo em 32 e 64 bits
    ]


class _Variant(ctypes.Structure):
    _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort), ("v", _Valor)]


class _DispParams(ctypes.Structure):
    _fields_ = [
        ("rgvarg", POINTER(_Variant)),
        ("rgdispidNamedArgs", POINTER(c_long)),
        ("cArgs", c_uint),
        ("cNamedArgs", c_uint),
    ]


class _ExcepInfo(ctypes.Structure):
    _fields_ = [
        ("wCode", c_ushort),
        ("wReserved", c_ushort),
        ("bstrSource", c_void_p),
        ("bstrDescription", c_void_p),
        ("bstrHelpFile", c_void_p),
        ("dwHelpContext", c_ulong),
        ("pvReserved", c_void_p),
        ("pfnDeferredFillIn", c_void_p),
        ("scode", c_long),
    ]


_IID_IDISPATCH = _Guid(0x00020400, 0, 0, (ctypes.c_ubyte * 8)(0xC0, 0, 0, 0, 0, 0, 0, 0x46))
_IID_NULL = _Guid()

_VT_I2, _VT_I4, _VT_R8, _VT_BSTR, _VT_DISPATCH, _VT_BOOL, _VT_UNKNOWN = 2, 3, 5, 8, 9, 11, 13
_INTEIROS = {_VT_I2: "iVal", _VT_I4: "lVal", 16: "iVal", 17: "iVal", 18: "iVal", 19: "lVal", 22: "lVal", 23: "lVal"}
_CHAMAR = 1 | 2          # DISPATCH_METHOD | DISPATCH_PROPERTYGET, como o VBA
_ATRIBUIR = 4            # DISPATCH_PROPERTYPUT
_DISPID_PROPERTYPUT = -3
_DISP_E_EXCEPTION = 0x80020009
_LCID = 0x0400           # idioma do usuário

_ole32 = None
_oleaut32 = None


def _carregar_dlls():
    global _ole32, _oleaut32
    if _ole32 is not None:
        return
    ole32 = ctypes.WinDLL("ole32")
    oleaut32 = ctypes.WinDLL("oleaut32")
    ole32.CoInitialize.argtypes = [c_void_p]
    ole32.CoInitialize.restype = c_long
    ole32.CoGetObject.argtypes = [c_wchar_p, c_void_p, POINTER(_Guid), POINTER(c_void_p)]
    ole32.CoGetObject.restype = c_long
    oleaut32.SysAllocString.argtypes = [c_wchar_p]
    oleaut32.SysAllocString.restype = c_void_p
    oleaut32.SysFreeString.argtypes = [c_void_p]
    oleaut32.SysFreeString.restype = None
    oleaut32.SysStringLen.argtypes = [c_void_p]
    oleaut32.SysStringLen.restype = c_uint
    oleaut32.VariantClear.argtypes = [POINTER(_Variant)]
    oleaut32.VariantClear.restype = c_long
    _ole32, _oleaut32 = ole32, oleaut32
    ole32.CoInitialize(None)


def _metodo(ponteiro, indice, *tipos):
    """Função número `indice` da tabela de métodos do objeto COM."""
    tabela = ctypes.cast(c_void_p(ponteiro), POINTER(c_void_p))[0]
    endereco = ctypes.cast(c_void_p(tabela), POINTER(c_void_p))[indice]
    return ctypes.WINFUNCTYPE(c_long, c_void_p, *tipos)(endereco)


def _texto_bstr(ponteiro):
    if not ponteiro:
        return ""
    return ctypes.wstring_at(ponteiro, _oleaut32.SysStringLen(ponteiro))


def _descrever(hr):
    codigo = hr & 0xFFFFFFFF
    try:
        texto = ctypes.FormatError(hr).strip()
    except Exception:
        texto = ""
    return "%s (0x%08X)" % (texto, codigo) if texto else "erro 0x%08X" % codigo


class ObjetoCom:
    """Um objeto do SAP, usado só por nome de método ou propriedade."""

    def __init__(self, ponteiro):
        self._ponteiro = ponteiro

    def __del__(self):
        try:
            if self._ponteiro:
                _metodo(self._ponteiro, 2)(self._ponteiro)  # Release
                self._ponteiro = None
        except Exception:
            pass

    def chamar(self, nome, *argumentos):
        """obj.nome(argumentos) ou leitura de obj.nome"""
        return self._invocar(nome, _CHAMAR, argumentos)

    def atribuir(self, nome, valor):
        """obj.nome = valor"""
        self._invocar(nome, _ATRIBUIR, (valor,))

    def _id_do_nome(self, nome):
        nomes = (c_wchar_p * 1)(nome)
        dispid = c_long()
        funcao = _metodo(self._ponteiro, 5, POINTER(_Guid), POINTER(c_wchar_p), c_uint, c_ulong, POINTER(c_long))
        hr = funcao(self._ponteiro, byref(_IID_NULL), nomes, 1, _LCID, byref(dispid))
        if hr < 0:
            raise ErroSap("%s não existe neste objeto: %s" % (nome, _descrever(hr)))
        return dispid.value

    def _invocar(self, nome, modo, argumentos):
        dispid = self._id_do_nome(nome)

        # Os argumentos vão em ordem inversa.
        quantidade = len(argumentos)
        variantes = (_Variant * max(1, quantidade))()
        for posicao, valor in enumerate(reversed(argumentos)):
            _preencher(variantes[posicao], valor)
        parametros = _DispParams()
        parametros.rgvarg = variantes
        parametros.cArgs = quantidade
        if modo == _ATRIBUIR:
            nomeado = c_long(_DISPID_PROPERTYPUT)
            parametros.rgdispidNamedArgs = ctypes.pointer(nomeado)
            parametros.cNamedArgs = 1

        resultado = _Variant()
        excecao = _ExcepInfo()
        erro_de_argumento = c_uint()
        funcao = _metodo(
            self._ponteiro, 6, c_long, POINTER(_Guid), c_ulong, c_ushort,
            POINTER(_DispParams), POINTER(_Variant), POINTER(_ExcepInfo), POINTER(c_uint),
        )
        try:
            hr = funcao(
                self._ponteiro, dispid, byref(_IID_NULL), _LCID, modo,
                byref(parametros), byref(resultado), byref(excecao), byref(erro_de_argumento),
            )
        finally:
            for posicao in range(quantidade):
                _oleaut32.VariantClear(byref(variantes[posicao]))

        if hr < 0:
            detalhe = ""
            if (hr & 0xFFFFFFFF) == _DISP_E_EXCEPTION:
                detalhe = _texto_bstr(excecao.bstrDescription).strip()
                for bstr in (excecao.bstrSource, excecao.bstrDescription, excecao.bstrHelpFile):
                    if bstr:
                        _oleaut32.SysFreeString(bstr)
            raise ErroSap("%s falhou: %s" % (nome, detalhe or _descrever(hr)))
        return _converter(resultado)


def _preencher(variante, valor):
    if isinstance(valor, bool):
        variante.vt = _VT_BOOL
        variante.v.iVal = -1 if valor else 0
    elif isinstance(valor, int):
        variante.vt = _VT_I4
        variante.v.lVal = valor
    else:
        variante.vt = _VT_BSTR
        variante.v.ptr = _oleaut32.SysAllocString(str(valor))


def _converter(variante):
    """Transforma o retorno do SAP em valor do Python."""
    tipo = variante.vt
    if tipo == _VT_DISPATCH:
        # A referência passa a ser do ObjetoCom, que a libera ao ser descartado.
        return ObjetoCom(variante.v.ptr) if variante.v.ptr else None
    if tipo == _VT_UNKNOWN:
        desconhecido = variante.v.ptr
        if not desconhecido:
            return None
        despacho = c_void_p()
        hr = _metodo(desconhecido, 0, POINTER(_Guid), POINTER(c_void_p))(desconhecido, byref(_IID_IDISPATCH), byref(despacho))
        _metodo(desconhecido, 2)(desconhecido)
        return ObjetoCom(despacho.value) if hr >= 0 and despacho.value else None
    try:
        if tipo == _VT_BSTR:
            return _texto_bstr(variante.v.ptr)
        if tipo == _VT_BOOL:
            return variante.v.iVal != 0
        if tipo == _VT_R8:
            return variante.v.dblVal
        if tipo in _INTEIROS:
            return getattr(variante.v, _INTEIROS[tipo])
        return None
    finally:
        _oleaut32.VariantClear(byref(variante))


def _objeto_sapgui():
    """Equivale a GetObject("SAPGUI") do VBA."""
    _carregar_dlls()
    ponteiro = c_void_p()
    hr = _ole32.CoGetObject("SAPGUI", None, byref(_IID_IDISPATCH), byref(ponteiro))
    if hr < 0 or not ponteiro.value:
        raise ErroSap(NAO_ENCONTRADO)
    return ObjetoCom(ponteiro.value)


def _primeiro_filho(objeto):
    """Equivale a objeto.Children(0) do VBA."""
    try:
        return objeto.chamar("Children", 0)
    except ErroSap:
        return objeto.chamar("Children").chamar("ElementAt", 0)


def _sessoes(conexao):
    """Lista de (Id, sessão) de todas as janelas abertas na conexão."""
    colecao = conexao.chamar("Children")
    sessoes = []
    for indice in range(int(colecao.chamar("Count") or 0)):
        try:
            sessao = colecao.chamar("ElementAt", indice)
        except ErroSap:
            sessao = colecao.chamar("Item", indice)
        if sessao is not None:
            sessoes.append((str(sessao.chamar("Id")), sessao))
    return sessoes


# ---------------------------------------------------------------------------
# Sessão: as operações que as macros usam
# ---------------------------------------------------------------------------

class Sessao:
    """Sessão real do SAP GUI."""

    def __init__(self, sessao=None, conexao=None):
        self._conexao = conexao
        self._aberta_pelo_app = False  # só janelas abertas pelo app podem ser fechadas por ele
        if sessao is not None:
            self._sessao = sessao
            return
        if sys.platform != "win32":
            raise ErroSap("o SAP GUI só está disponível no Windows (use --simular para testar)")
        gui = _objeto_sapgui()
        try:
            motor = gui.chamar("GetScriptingEngine")
        except ErroSap as erro:
            raise ErroSap("SAP GUI Scripting indisponível (%s). Rode /diagnostico e envie o resultado" % erro)
        if motor is None:
            raise ErroSap("SAP GUI Scripting indisponível: verifique se o scripting está habilitado")
        try:
            conexao = _primeiro_filho(motor)
            sessao = _primeiro_filho(conexao) if conexao is not None else None
        except ErroSap as erro:
            raise ErroSap("SAP aberto, mas sem sessão logada (%s)" % erro)
        if sessao is None:
            raise ErroSap("SAP aberto, mas sem sessão logada")
        self._sessao = sessao
        self._conexao = conexao

    def _elemento(self, id_):
        try:
            elemento = self._sessao.chamar("findById", id_)
        except ErroSap:
            elemento = None
        if elemento is None:
            raise ErroSap('elemento "%s" não encontrado na tela do SAP' % id_)
        return elemento

    def existe(self, id_):
        """True se o elemento está na tela."""
        try:
            return self._sessao.chamar("findById", id_, False) is not None
        except ErroSap:
            return False

    def ler(self, id_, propriedade="Text"):
        """valor = session.findById(id).Text (ou outra propriedade)"""
        return self._elemento(id_).chamar(propriedade)

    def selecionar(self, id_):
        """session.findById(id).Selected = True (opções e caixas de seleção)"""
        self._elemento(id_).atribuir("Selected", True)

    def texto(self, id_, valor):
        """session.findById(id).Text = valor"""
        self._elemento(id_).atribuir("Text", valor)

    def tecla(self, janela, tecla):
        """session.findById(janela).sendVKey tecla"""
        self._elemento(janela).chamar("sendVKey", int(tecla))

    def clicar(self, id_, ignorar_erro=False):
        """session.findById(id).press"""
        try:
            self._elemento(id_).chamar("press")
        except ErroSap:
            if not ignorar_erro:
                raise

    def botao(self, id_, botao):
        """session.findById(id).pressButton botao"""
        self._elemento(id_).chamar("pressButton", botao)

    def maximizar(self, janela):
        """session.findById(janela).maximize"""
        try:
            self._elemento(janela).chamar("maximize")
        except ErroSap:
            pass

    def status(self):
        """Tipo (S, W, E, A, I) e texto da barra de status."""
        barra = self._elemento("wnd[0]/sbar")
        return str(barra.chamar("MessageType") or ""), str(barra.chamar("Text") or "")

    _status = status

    def selecao_multipla(self, botao, valores):
        """Preenche a seleção múltipla de um campo (o botão de seta ao lado dele) com
        vários valores de uma vez, pelo "Importar da área de transferência" do SAP."""
        from . import area_de_transferencia

        if not area_de_transferencia.copiar("\n".join(valores)):
            raise ErroSap("não foi possível usar a área de transferência")
        self.clicar(botao)
        try:
            self.clicar("wnd[1]/tbar[0]/btn[24]")  # Importar da área de transferência (Shift+F12)
            self.clicar("wnd[1]/tbar[0]/btn[8]")   # Copiar (F8)
        except ErroSap:
            self.clicar("wnd[1]/tbar[0]/btn[12]", ignorar_erro=True)  # Cancelar: não deixa a janela aberta
            raise

    def grade(self, base="wnd[0]/usr"):
        """A primeira lista em grade (ALV) da tela, ou None se a tela não tiver uma.
        Procura pela tela em vez de usar um id fixo, que muda de transação para transação."""
        try:
            pendentes = [(self._elemento(base), 0)]
        except ErroSap:
            return None
        while pendentes:
            objeto, nivel = pendentes.pop(0)
            try:
                if str(objeto.chamar("Type")) == "GuiShell" and str(objeto.chamar("SubType")) == "GridView":
                    return Grade(objeto)
            except ErroSap:
                pass
            if nivel >= 8:
                continue
            try:
                filhos = objeto.chamar("Children")
                quantidade = int(filhos.chamar("Count") or 0) if filhos is not None else 0
            except ErroSap:
                continue
            for indice in range(quantidade):
                try:
                    filho = filhos.chamar("ElementAt", indice)
                except ErroSap:
                    continue
                if filho is not None:
                    pendentes.append((filho, nivel + 1))
        return None

    def conferir_status(self):
        """Lança erro com o texto da barra de status se o SAP recusou a última ação."""
        tipo, texto = self._status()
        if tipo in ("E", "A"):
            raise ErroSap(texto or "o SAP recusou o item")

    def aguardar(self, espera=30):
        """Espera o SAP terminar de processar a tela atual."""
        limite = time.monotonic() + espera
        while time.monotonic() < limite:
            try:
                if not self._sessao.chamar("Busy"):
                    return
            except ErroSap:
                return
            time.sleep(0.2)

    def nova_janela(self, transacao, espera=20):
        """Abre a transação numa janela nova do SAP (como digitar /o + transação)
        e devolve a sessão dessa janela. A janela atual não é mexida."""
        if self._conexao is None:
            raise ErroSap("não foi possível abrir uma janela nova: conexão do SAP desconhecida")
        antes = {id_ for id_, _ in _sessoes(self._conexao)}
        self.texto("wnd[0]/tbar[0]/okcd", "/o" + transacao)
        self.tecla("wnd[0]", 0)

        limite = time.monotonic() + espera
        while time.monotonic() < limite:
            for id_, sessao in _sessoes(self._conexao):
                if id_ not in antes:
                    nova = Sessao(sessao, self._conexao)
                    nova._aberta_pelo_app = True
                    nova.aguardar()
                    return nova
            time.sleep(0.3)

        texto = ""
        try:
            texto = self._status()[1]
        except ErroSap:
            pass
        raise ErroSap("o SAP não abriu a janela nova (%s)" % (texto or "o limite de janelas abertas pode ter sido atingido"))

    def fechar(self):
        """Fecha a janela, se foi o app que a abriu. Nunca fecha a janela do usuário."""
        if not self._aberta_pelo_app:
            return
        self._aberta_pelo_app = False
        try:
            self._conexao.chamar("CloseSession", str(self._sessao.chamar("Id")))
        except ErroSap:
            # Alternativa: /i encerra a janela atual.
            self.texto("wnd[0]/tbar[0]/okcd", "/i")
            self.tecla("wnd[0]", 0)


class Grade:
    """Uma lista ALV em formato de grade (GuiGridView), lida célula a célula."""

    def __init__(self, objeto):
        self._grade = objeto

    def colunas(self):
        """Lista de (nome técnico, título na tela) das colunas, na ordem da tela."""
        ordem = self._grade.chamar("ColumnOrder")
        nomes = []
        for indice in range(int(ordem.chamar("Count") or 0)):
            try:
                nomes.append(str(ordem.chamar("ElementAt", indice)))
            except ErroSap:
                nomes.append(str(ordem.chamar("Item", indice)))
        colunas = []
        for nome in nomes:
            try:
                titulo = str(self._grade.chamar("GetDisplayedColumnTitle", nome) or "")
            except ErroSap:
                titulo = ""
            colunas.append((nome, titulo))
        return colunas

    def coluna_oculta(self, nome, amostra=30):
        """True se a coluna existe na lista mesmo sem aparecer na tela (oculta no layout)
        e tem algum valor nas primeiras linhas."""
        try:
            self._grade.atribuir("FirstVisibleRow", 0)
            total = int(self._grade.chamar("RowCount") or 0)
            for linha in range(min(total, amostra)):
                if str(self._grade.chamar("GetCellValue", linha, nome) or "").strip():
                    return True
        except ErroSap:
            pass
        return False

    def valores(self, colunas):
        """Uma lista de {coluna: texto} por linha. O SAP só manda para a tela as linhas
        visíveis, então a grade é rolada em blocos enquanto é lida."""
        total = int(self._grade.chamar("RowCount") or 0)
        try:
            bloco = max(1, int(self._grade.chamar("VisibleRowCount") or 0))
        except ErroSap:
            bloco = max(1, total)
        linhas = []
        for linha in range(total):
            if linha % bloco == 0:
                try:
                    self._grade.atribuir("FirstVisibleRow", linha)
                except ErroSap:
                    pass
            linhas.append({coluna: str(self._grade.chamar("GetCellValue", linha, coluna) or "").strip() for coluna in colunas})
        return linhas


class GradeSimulada:
    """Grade de mentira da ME2M usada com --simular."""

    COLUNAS = [("MATNR", "Material"), ("TXZ01", "Texto breve"), ("EBELN", "Documento compras"), ("EBELP", "Item"), ("BEDAT", "Data doc."),
               ("WERKS", "Cen."), ("NETPR", "Preço líq."), ("WAERS", "Moeda"), ("PEINH", "Unidade preço")]

    def __init__(self, materiais):
        self._linhas = []
        for material in materiais:
            base = sum(ord(letra) for letra in material) % 90 + 5
            por = 100 if base % 2 else 1
            preco = base * por + 0.18
            self._linhas += [
                {"MATNR": material, "TXZ01": "Chicote PWR Relé %s" % material[-3:], "EBELN": "4501707798", "EBELP": "20", "BEDAT": "16.11.2026", "WERKS": "8500",
                 "NETPR": ("%.2f" % preco).replace(".", ","), "WAERS": "EUR", "PEINH": str(por)},
                {"MATNR": material, "TXZ01": "Chicote PWR Relé %s" % material[-3:], "EBELN": "4501672232", "EBELP": "110", "BEDAT": "20.08.2026", "WERKS": "8500",
                 "NETPR": ("%.2f" % (preco * 0.8)).replace(".", ","), "WAERS": "EUR", "PEINH": str(por)},
            ]

    def colunas(self):
        return list(self.COLUNAS)

    def coluna_oculta(self, nome, amostra=30):
        return False

    def valores(self, colunas):
        return [{coluna: linha.get(coluna, "") for coluna in colunas} for linha in self._linhas]


class SessaoSimulada:
    """Sessão de mentira usada com --simular. Itens contendo "erro" falham."""

    def __init__(self):
        self._material = ""
        self._lote = []

    def texto(self, id_, valor):
        if id_.endswith("MATNR") or id_.endswith("MATNR-LOW"):
            self._material, self._lote = valor, []
        elif id_.endswith("okcd"):
            self._material, self._lote = "", []

    def selecao_multipla(self, botao, valores):
        self._lote = list(valores)

    def status(self):
        if not self._com_pedido():
            return "S", "Nenhum documento de compras selecionado (simulado)"
        return "", ""

    def _com_pedido(self):
        return [material for material in (self._lote or [self._material]) if "erro" not in material.lower()]

    def grade(self, base="wnd[0]/usr"):
        time.sleep(0.2 + 0.05 * len(self._lote))
        return GradeSimulada(self._com_pedido()) if self._com_pedido() else None

    def tecla(self, janela, tecla):
        time.sleep(0.15)

    def clicar(self, id_, ignorar_erro=False):
        pass

    def botao(self, id_, botao):
        time.sleep(0.3)

    def maximizar(self, janela):
        pass

    def conferir_status(self):
        if "erro" in self._material.lower():
            raise ErroSap("Material %s não existe (simulado)" % self._material)

    def nova_janela(self, transacao):
        time.sleep(0.4)
        return SessaoSimulada()

    def fechar(self):
        time.sleep(0.2)


# ---------------------------------------------------------------------------
# Login: abre o SAP Logon, a conexão e entra com usuário e senha
# ---------------------------------------------------------------------------

def _caminho_do_saplogon(informado=""):
    candidatos = [informado] if informado else []
    try:
        import winreg

        chave = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\saplogon.exe"
        for vista in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, chave, 0, winreg.KEY_READ | vista) as aberta:
                    candidatos.append(winreg.QueryValueEx(aberta, None)[0].strip('"'))
            except OSError:
                pass
    except ImportError:
        pass
    for variavel in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        base = os.environ.get(variavel)
        if base:
            candidatos.append(os.path.join(base, "SAP", "FrontEnd", "SAPgui", "saplogon.exe"))
    for caminho in candidatos:
        if caminho and os.path.isfile(caminho):
            return caminho
    raise ErroSap("saplogon.exe não encontrado: informe o caminho em 'saplogon =' no arquivo de credenciais")


def _motor_de_scripting(caminho_do_saplogon, avisar, espera=45):
    """Devolve o motor de scripting, abrindo o SAP Logon se ele não estiver aberto."""
    def tentar():
        try:
            return _objeto_sapgui().chamar("GetScriptingEngine")
        except ErroSap:
            return None

    motor = tentar()
    if motor is not None:
        return motor
    avisar("Abrindo o SAP Logon...")
    subprocess.Popen([_caminho_do_saplogon(caminho_do_saplogon)])
    limite = time.monotonic() + espera
    while time.monotonic() < limite:
        time.sleep(0.5)
        motor = tentar()
        if motor is not None:
            return motor
    raise ErroSap("o SAP Logon abriu, mas o scripting não respondeu em %d segundos" % espera)


def _usuario_logado(sessao):
    try:
        return str(sessao.chamar("Info").chamar("User") or "")
    except ErroSap:
        return ""


def fazer_login(credenciais, avisar=lambda texto: None):
    """Abre o SAP e faz login. Devolve uma frase dizendo o que aconteceu.
    A senha só é escrita no campo de senha do SAP; nunca aparece em mensagens."""
    if SIMULAR:
        avisar("Abrindo o SAP Logon...")
        time.sleep(0.6)
        return "Logado como %s (simulado)" % credenciais["usuario"]
    if sys.platform != "win32":
        raise ErroSap("o SAP GUI só está disponível no Windows (use --simular para testar)")

    motor = _motor_de_scripting(credenciais.get("saplogon", ""), avisar)

    # Reaproveita uma conexão já aberta; senão abre a que está no arquivo.
    conexao = None
    try:
        if int(motor.chamar("Children").chamar("Count") or 0) > 0:
            conexao = _primeiro_filho(motor)
    except ErroSap:
        conexao = None
    if conexao is None:
        avisar("Abrindo a conexão %s..." % credenciais["conexao"])
        try:
            conexao = motor.chamar("OpenConnection", credenciais["conexao"], True)
        except ErroSap as erro:
            raise ErroSap('não foi possível abrir a conexão "%s" do SAP Logon (%s)' % (credenciais["conexao"], erro))
    objeto_da_sessao = None
    limite = time.monotonic() + 30
    while objeto_da_sessao is None and time.monotonic() < limite:
        try:
            objeto_da_sessao = _primeiro_filho(conexao)
        except ErroSap:
            objeto_da_sessao = None
        if objeto_da_sessao is None:
            time.sleep(0.5)
    if objeto_da_sessao is None:
        raise ErroSap("a conexão abriu, mas a tela de login não apareceu")

    usuario = _usuario_logado(objeto_da_sessao)
    if usuario:
        return "O SAP já estava logado como %s" % usuario

    avisar("Fazendo login...")
    sessao = Sessao(objeto_da_sessao, conexao)
    if not sessao.existe("wnd[0]/usr/pwdRSYST-BCODE"):
        raise ErroSap("a tela de login do SAP não foi encontrada")
    if credenciais.get("mandante"):
        sessao.texto("wnd[0]/usr/txtRSYST-MANDT", credenciais["mandante"])
    sessao.texto("wnd[0]/usr/txtRSYST-BNAME", credenciais["usuario"])
    sessao.texto("wnd[0]/usr/pwdRSYST-BCODE", credenciais["senha"])
    if credenciais.get("idioma"):
        sessao.texto("wnd[0]/usr/txtRSYST-LANGU", credenciais["idioma"])
    sessao.tecla("wnd[0]", 0)
    sessao.conferir_status()  # usuário ou senha errados aparecem aqui

    # Aviso de "usuário já logado em outro lugar": continua sem derrubar o outro login.
    if sessao.existe("wnd[1]/usr/radMULTI_LOGON_OPT2"):
        sessao.selecionar("wnd[1]/usr/radMULTI_LOGON_OPT2")
        sessao.clicar("wnd[1]/tbar[0]/btn[0]")
        sessao.conferir_status()

    usuario = _usuario_logado(objeto_da_sessao)
    if sessao.existe("wnd[1]"):
        titulo = ""
        try:
            titulo = str(sessao.ler("wnd[1]") or "")
        except ErroSap:
            pass
        raise ErroSap("o SAP abriu uma janela que precisa de você%s" % (": " + titulo if titulo else ""))
    if not usuario:
        raise ErroSap("o login não foi concluído: confira a tela do SAP")
    return "Logado como %s" % usuario


def conectar():
    """Devolve a sessão ativa do SAP: GetObject("SAPGUI").GetScriptingEngine.Children(0).Children(0)."""
    return SessaoSimulada() if SIMULAR else Sessao()


def diagnosticar():
    """Testa a conexão passo a passo. Devolve uma lista de (passo, resultado, deu_certo)."""
    passos = []

    def tentar(passo, acao):
        try:
            valor = acao()
        except Exception as erro:  # o diagnóstico nunca deve derrubar o app
            passos.append((passo, "%s" % erro, False))
            return None
        if valor is None:
            passos.append((passo, "não devolveu nada", False))
        else:
            passos.append((passo, "ok" if isinstance(valor, ObjetoCom) else "ok: %s" % (valor,), True))
        return valor

    if sys.platform != "win32":
        return [("Sistema", "o diagnóstico só funciona no Windows", False)]
    gui = tentar('GetObject("SAPGUI")', _objeto_sapgui)
    motor = tentar("GetScriptingEngine", lambda: gui.chamar("GetScriptingEngine")) if gui else None
    conexao = tentar("Conexão: Children(0)", lambda: _primeiro_filho(motor)) if motor else None
    sessao = tentar("Sessão: Children(0)", lambda: _primeiro_filho(conexao)) if conexao else None
    if sessao:
        tentar("Sessão: Name", lambda: sessao.chamar("Name"))
        info = tentar("Sessão: Info", lambda: sessao.chamar("Info"))
        if info:
            tentar("Transação atual", lambda: info.chamar("Transaction"))
        tentar('findById("wnd[0]")', lambda: sessao.chamar("findById", "wnd[0]"))
    return passos
