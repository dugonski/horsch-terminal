"""Copiar texto para a área de transferência do Windows (Ctrl+V), só com a biblioteca padrão."""
import os
import time


def copiar(texto):
    """Devolve True se o texto foi copiado."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32")
    kernel32 = ctypes.WinDLL("kernel32")
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalFree.argtypes = [wintypes.HANDLE]

    dados = (texto.replace("\r\n", "\n").replace("\n", "\r\n") + "\0").encode("utf-16-le")
    for _ in range(20):  # outro programa pode estar usando a área de transferência
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return False
    try:
        user32.EmptyClipboard()
        memoria = kernel32.GlobalAlloc(0x0002, len(dados))  # GMEM_MOVEABLE
        if not memoria:
            return False
        destino = kernel32.GlobalLock(memoria)
        if not destino:
            kernel32.GlobalFree(memoria)
            return False
        ctypes.memmove(destino, dados, len(dados))
        kernel32.GlobalUnlock(memoria)
        if not user32.SetClipboardData(13, memoria):  # CF_UNICODETEXT
            kernel32.GlobalFree(memoria)
            return False
        return True
    finally:
        user32.CloseClipboard()
