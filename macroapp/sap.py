"""Conexão com a sessão aberta do SAP GUI (SAP GUI Scripting).

Fala com o SAP do mesmo jeito que o VBA: chamando métodos pelo nome (IDispatch).
É feito só com ctypes, da biblioteca padrão, e não carrega a biblioteca de tipos
do SAP GUI, que em algumas máquinas não abre fora do VBA.
"""
import ctypes
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


# ---------------------------------------------------------------------------
# Sessão: as operações que as macros usam
# ---------------------------------------------------------------------------

class Sessao:
    """Sessão real do SAP GUI."""

    def __init__(self):
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

    def _elemento(self, id_):
        try:
            elemento = self._sessao.chamar("findById", id_)
        except ErroSap:
            elemento = None
        if elemento is None:
            raise ErroSap('elemento "%s" não encontrado na tela do SAP' % id_)
        return elemento

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

    def conferir_status(self):
        """Lança erro com o texto da barra de status se o SAP recusou a última ação."""
        barra = self._elemento("wnd[0]/sbar")
        if str(barra.chamar("MessageType") or "") in ("E", "A"):
            raise ErroSap(str(barra.chamar("Text") or "") or "o SAP recusou o item")


class SessaoSimulada:
    """Sessão de mentira usada com --simular. Itens contendo "erro" falham."""

    def __init__(self):
        self._material = ""

    def texto(self, id_, valor):
        if id_.endswith("MATNR"):
            self._material = valor

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
