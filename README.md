# Horsch Terminal

App de terminal para Windows que executa macros do SAP. É feito em Python e usa
só a biblioteca padrão: não tem `.exe` e não precisa instalar nenhum pacote,
basta ter o Python 3.8 ou mais novo.

## Uso

1. Copie a pasta inteira (`horsch-terminal.cmd`, `horsch_terminal` e `macros`) para o computador.
2. Abra o SAP e faça login.
3. Dê dois cliques em `horsch-terminal.cmd`, ou rode `python -m horsch_terminal` dentro da pasta.
4. Digite `/` para ver os comandos.

| Comando        | O que faz                                                        |
|----------------|------------------------------------------------------------------|
| `/pdfs`        | Abre no navegador o PDF de cada part number (MD04, centro 8500)  |
| `/ajuda`       | Mostra os comandos                                               |
| `/diagnostico` | Testa a conexão com o SAP passo a passo                          |
| `/limpar`      | Limpa a tela                                                     |
| `/sair`        | Fecha o app                                                      |

Em `/pdfs`, cole a lista de part numbers (um por linha, ou separados por espaço,
vírgula ou ponto e vírgula), tecle Enter e depois Enter de novo com a linha vazia
para executar. Também dá para passar direto: `/pdfs 12345 67890`.

O SAP GUI Scripting precisa estar habilitado, como já é exigido pelas macros VBA.
Se a conexão com o SAP falhar, rode `/diagnostico` para ver em que passo.

Para testar sem SAP, rode `python -m horsch_terminal --simular` (qualquer item contendo
"erro" falha).

## Estrutura

- `horsch_terminal/__main__.py`: ponto de entrada.
- `horsch_terminal/sap.py`: conexão com a sessão aberta do SAP GUI.
- `horsch_terminal/tela.py`: desenho da tela e leitura do teclado.
- `horsch_terminal/app.py`: comandos, lista de itens e execução.
- `macros/`: uma macro por arquivo.

## Nova macro

Cada arquivo `.py` dentro de `macros` é uma macro e aparece sozinho na lista de
comandos. Copie `macros/pdfs_md04.py`, troque o `COMANDO` e escreva os passos em
`por_item`. Os passos gravados pelo SAP em VBA viram:

| VBA                                         | Aqui                          |
|---------------------------------------------|-------------------------------|
| `session.findById(id).Text = valor`         | `sap.texto(id, valor)`        |
| `session.findById(janela).sendVKey n`       | `sap.tecla(janela, n)`        |
| `session.findById(id).press`                | `sap.clicar(id)`              |
| `session.findById(id).pressButton botao`    | `sap.botao(id, botao)`        |
| `session.findById(janela).maximize`         | `sap.maximizar(janela)`       |

`sap.conferir_status()` interrompe o item com a mensagem do SAP quando a barra de
status mostra erro.
