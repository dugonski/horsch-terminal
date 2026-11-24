"""Monta as notas da Release a partir dos commits desde a tag anterior.

Os commits seguem o padrão "tipo: descrição" (feat:, fix:, docs:...) e são agrupados
por tipo. Uso: python .github/changelog.py v0.9.0 notas.md
"""
import os
import re
import subprocess
import sys

SECOES = [
    ("feat", "Novidades"),
    ("fix", "Correções"),
    ("perf", "Desempenho"),
    ("style", "Visual"),
    ("refactor", "Melhorias internas"),
    ("docs", "Documentação"),
    ("ci", "Manutenção"),
    ("build", "Manutenção"),
    ("chore", "Manutenção"),
    ("test", "Manutenção"),
]
PADRAO = re.compile(r"^(\w+)(\([^)]*\))?!?:\s*(.+)$")


def git(*argumentos):
    resultado = subprocess.run(["git"] + list(argumentos), stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, universal_newlines=True, encoding="utf-8")
    return resultado.stdout.strip() if resultado.returncode == 0 else None


def main():
    tag, destino = sys.argv[1], sys.argv[2]
    anterior = git("describe", "--tags", "--abbrev=0", "--match", "v*", "--exclude", tag, tag)
    intervalo = "%s..%s" % (anterior, tag) if anterior else tag
    assuntos = (git("log", "--no-merges", "--reverse", "--format=%s", intervalo) or "").splitlines()

    grupos, outros = {}, []
    for assunto in assuntos:
        encontrado = PADRAO.match(assunto)
        titulo = dict(SECOES).get(encontrado.group(1).lower()) if encontrado else None
        if titulo:
            grupos.setdefault(titulo, []).append(encontrado.group(3))
        elif assunto.strip():
            outros.append(assunto.strip())

    linhas = []
    for titulo in dict.fromkeys(titulo for _, titulo in SECOES):
        if titulo in grupos:
            linhas += ["## " + titulo] + ["- " + item for item in grupos[titulo]] + [""]
    if outros:
        linhas += ["## Outros"] + ["- " + item for item in outros] + [""]
    if not assuntos:
        linhas += ["Sem mudanças desde a versão anterior.", ""]

    repositorio = os.environ.get("GITHUB_REPOSITORY")
    if anterior and repositorio:
        linhas.append("**Comparação completa**: https://github.com/%s/compare/%s...%s" % (repositorio, anterior, tag))
    elif not anterior:
        linhas.append("Primeira versão publicada.")

    with open(destino, "w", encoding="utf-8") as arquivo:
        arquivo.write("\n".join(linhas) + "\n")


if __name__ == "__main__":
    main()
