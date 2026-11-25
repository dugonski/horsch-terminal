# Horsch Terminal

App de terminal para Windows que executa macros do SAP. É feito em Python e usa
só a biblioteca padrão: não tem `.exe` e não precisa instalar nenhum pacote,
basta ter o Python 3.8 ou mais novo.

## Uso

1. Copie a pasta inteira (`horsch-terminal.cmd`, `main.py`, `src` e `macros`) para o computador.
2. Abra o SAP e faça login.
3. Dê dois cliques em `horsch-terminal.cmd`, ou rode `python main.py` dentro da pasta.
4. Digite `/` para ver os comandos.

| Comando        | O que faz                                                        |
|----------------|------------------------------------------------------------------|
| `/pdfs`        | Abre no navegador o PDF de cada part number (MD04, centro 8500)  |
| `/precos`      | Preço do pedido de compra mais recente de cada part number (ME2M, centro 8500) |
| `/login`       | Abre o SAP e faz login com as credenciais salvas                 |
| `/customizar`  | Muda o estilo da logo: `/customizar fill` ou `/customizar hollow` |
| `/atualizar`   | Baixa e instala a versão mais nova do app                        |
| `/ajuda`       | Mostra os comandos                                               |
| `/diagnostico` | Testa a conexão com o SAP passo a passo                          |
| `/limpar`      | Limpa a tela                                                     |
| `/sair`        | Fecha o app                                                      |

Em `/pdfs`, cole a lista de part numbers (um por linha, ou separados por espaço,
vírgula ou ponto e vírgula), tecle Enter e depois Enter de novo com a linha vazia
para executar. Também dá para passar direto: `/pdfs 12345 67890`.

O `/pdfs` abre a MD04 numa janela nova do SAP (como digitar `/omd04`) e roda
todos os part numbers nela, sem mexer na janela em que você está trabalhando. No
fim, mesmo se algum item falhar ou você cancelar, essa janela nova é fechada.

O SAP GUI Scripting precisa estar habilitado, como já é exigido pelas macros VBA.
Se a conexão com o SAP falhar, rode `/diagnostico` para ver em que passo.

Para testar sem SAP, rode `python main.py --simular` (qualquer item contendo
"erro" falha).

## Preços (`/precos`)

Busca na ME2M o preço do pedido de compra mais recente de cada part number, lendo
a lista direto da tela do SAP (sem exportar para planilha). Roda numa janela nova
do SAP, que é fechada no fim.

- Faz **uma consulta só** com todos os part numbers (seleção múltipla da ME2M). Para
  isso, a lista precisa mostrar a coluna **Material**. Se o seu layout não tiver
  essa coluna, o app avisa e consulta um part number por vez, o que funciona igual,
  só mais devagar. Para ativar a consulta única, inclua a coluna Material no layout
  da ME2M (Alterar layout, Ctrl+F8) e salve como layout padrão.
- A seleção múltipla é preenchida pela área de transferência, que depois recebe os
  preços.
- O preço é dividido pela **unidade de preço**: 13,03 EUR por 100 vira 0,1303 EUR.
- Só considera pedidos do **centro 8500**: o centro é preenchido na seleção da
  ME2M e, por garantia, linhas de outros centros são descartadas pela coluna Cen.
- "Mais recente" é o pedido com a **Data doc.** mais nova. O **texto breve** é o
  desse mesmo pedido.
- Itens com preço zero e linhas de subtotal são ignorados.

Para usar com o Excel ou o Google Sheets:

1. Selecione a coluna de part numbers (pode incluir a coluna de preço ao lado) e
   copie com Ctrl+C.
2. No terminal, digite `/precos`, cole e tecle Enter duas vezes.
3. No fim aparece "Conteúdo copiado para o Ctrl+V": preço e texto breve já estão
   copiados, um part number por linha e na mesma ordem da lista. Clique na primeira célula da coluna de preço e cole com
   Ctrl+V: o preço fica nessa coluna e o texto breve na seguinte. Linhas vazias ou
   sem pedido ficam em branco, então o alinhamento se mantém.

Também dá para passar direto: `/precos 60103019 60217124`. Os números saem com
vírgula decimal e sem separador de milhar, como o Excel e o Sheets em português leem.

### Com uma planilha `.xlsx`

Passe o caminho do arquivo (ou arraste o arquivo para o terminal depois de digitar
`/precos`):

    /precos C:\Users\voce\Documents\precos.xlsx

Formato esperado, na primeira aba:

| A          | B         | C     | D     |
|------------|-----------|-------|-------|
| PartNumber | Descrição | Preço | Moeda |
| 60103019   |           |       |       |
| 60217124   |           |       |       |

- Os part numbers são lidos da **coluna A**, quantos houver. A linha 1 é tratada
  como cabeçalho quando não tem números.
- O app preenche **Descrição** (texto breve), **Preço** (unitário, já dividido pela
  unidade de preço, gravado como número) e **Moeda**. As colunas são achadas pelo
  cabeçalho; sem cabeçalho, usa B, C e D.
- Se a linha 1 for cabeçalho, os títulos que faltarem (Descrição, Preço, Moeda) são
  escritos com a mesma formatação da A1. Títulos que já existem não são trocados.
- Só essas células mudam: formatação, outras colunas e outras abas ficam como
  estavam. Linhas sem pedido não são alteradas.
- **Feche o arquivo no Excel antes**; se ele estiver aberto, o app avisa antes de
  consultar o SAP.
- Com o Google Sheets: Arquivo > Fazer download > Microsoft Excel (.xlsx), rode o
  `/precos` e importe o arquivo de volta.

O `/pdfs` também aceita uma planilha, lendo os part numbers da coluna A.

## Login automático

O comando `/login` abre o SAP Logon (se estiver fechado), abre a conexão e entra
com o seu usuário e senha. As credenciais ficam em um arquivo que **você cria à
mão**, na sua pasta de usuário do Windows, fora da pasta do app:

```
C:\Users\SEU_USUARIO_DO_WINDOWS\.horsch-terminal\sap.ini
```

Conteúdo:

```ini
[sap]
conexao = NOME DA CONEXAO COMO APARECE NO SAP LOGON
mandante = 100
usuario = SEU_USUARIO
senha = SUA_SENHA
idioma = PT
```

`conexao`, `usuario` e `senha` são obrigatórios. Se o app não achar o SAP Logon
sozinho, acrescente `saplogon = C:\caminho\para\saplogon.exe`.

O app só lê esse arquivo: nunca grava, nunca mostra a senha na tela e não a envia
a lugar nenhum além do campo de senha do SAP. A senha fica em texto puro, então
quem tiver acesso ao seu usuário do Windows consegue ler; não copie esse arquivo
para pastas compartilhadas nem para o repositório.

## Histórico de comandos

Com a caixa de entrada vazia, a seta para cima traz os comandos anteriores e a
seta para baixo volta. Enter executa de novo. O histórico fica em
`.horsch-terminal\historico.txt`, na sua pasta de usuário, e continua lá depois
de fechar o app.

## Atualização

`/atualizar` compara a sua versão com a publicada no GitHub e, se houver uma mais
nova, baixa e troca os arquivos do app. Depois, feche e abra o app de novo.

- As suas configurações e as macros que você criou em `macros` não são tocadas.
- Antes de trocar, uma cópia de cada arquivo fica em
  `.horsch-terminal\backup\v<versão anterior>`, na sua pasta de usuário.
- O atalho `horsch-terminal.cmd` não é trocado com o app aberto; se ele mudar, o
  app avisa para baixar o zip completo.
- Precisa de acesso a `raw.githubusercontent.com` e `codeload.github.com`; se a
  rede da empresa bloquear, o app mostra o erro e nada é alterado.

## Aparência

`/customizar fill` mostra a logo como um retângulo vermelho com letras brancas;
`/customizar hollow` mostra só o contorno das letras em vermelho. A escolha fica
salva em `.horsch-terminal\preferencias.ini`, na sua pasta de usuário.

## Estrutura

- `main.py`: ponto de entrada.
- `src/sap.py`: conexão com a sessão aberta do SAP GUI e login.
- `src/credenciais.py`: leitura do arquivo de credenciais.
- `src/logo.py`: desenho da logo no banner.
- `src/preferencias.py`: estilo da logo escolhido em `/customizar`.
- `src/historico.py`: histórico de comandos.
- `src/atualizador.py`: comando `/atualizar`.
- `src/area_de_transferencia.py`: copiar texto para o Ctrl+V.
- `src/planilha.py`: leitura e preenchimento de `.xlsx`, sem bibliotecas externas.
- `src/tela.py`: desenho da tela e leitura do teclado.
- `src/app.py`: comandos, lista de itens e execução.
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

Em `por_item`, o que a função devolver aparece ao lado do item na tela. Uma macro
também pode definir `por_lote(sap, itens)`, que trata todos de uma vez e devolve
`{item: resultado}`; se ela der erro, o app usa `por_item` para cada um. Com
`LINHAS = True`, a macro recebe a lista linha a linha (com repetidos e linhas
vazias) e pode definir `concluir(linhas, resultados)` para fazer algo no fim, como
copiar os resultados. Veja `macros/precos_me2m.py`. Para ler uma lista em grade
(ALV) da tela, use `sap.grade()`.

Para a macro rodar numa janela nova do SAP, devolva `sap.nova_janela("transacao")`
em `inicio` e feche com `sap.fechar()` em `fim`, que roda sempre no final. Veja
`macros/pdfs_md04.py`.
