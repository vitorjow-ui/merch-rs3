# Merch RS3

Painel em português para comparar flips e receitas no Grand Exchange do RuneScape 3.

## Abrir

[Abra o painel no GitHub Pages](https://vitorjow-ui.github.io/merch-rs3/) pelo celular ou computador. O site consulta as cotações no navegador. Seu caixa, ofertas e histórico ficam salvos nesse navegador. Use **Exportar CSV** para baixar o histórico de execuções.

No Windows, execute `Iniciar-Merch-RS3.cmd`. Ele inicia o painel em [127.0.0.1:8765](http://127.0.0.1:8765/) e abre o navegador. Pelo terminal da pasta do projeto, use `python server.py`. Se a porta estiver em uso, abra a instância já em execução ou passe `--port 8766` e use o endereço informado no terminal.

Em **Configurações**, informe o caixa inicial destinado ao merch. Os campos de orçamento e capital aceitam valores inteiros e abreviações como **1,5B**, **300M** e **50K**. Selecione o perfil da conta e o teto por item. Com o caixa inicial em **0 GP**, a página inicial usa **1B GP em simulação** e um teto de **20% por operação**. Use **Simular** para comparar outro orçamento. A simulação vale para a aba do navegador e preserva o caixa e o histórico registrados. Feche a janela do servidor para encerrar o painel.

## Escolher a operação

- **Visão geral** mostra a rodada sugerida, o lucro líquido total, o GP aplicado e o caixa após as compras. Expanda a rodada para conferir os lotes de Flip e Crafting. Os preços exatos ficam nos detalhes, com botões para copiar ao GE.
- **Flip** reúne giro rápido e equipamentos de maior valor. Abra o detalhe para conferir o preço e a idade dos trades de compra e venda, a liquidez observada, a tarifa e o preço de equilíbrio.
- **Crafting** compara receitas verificadas com saída negociável no GE. O detalhe mostra insumos, níveis e requisitos em tokens. Você pode editar quantidade, preços e outros custos em GP. Essa aba projeta a operação. Para registrar compras e vendas, use **Ofertas**.

A rodada maximiza o lucro estimado entre os lotes sugeridos que passam pelo cenário de saída 2% menor. A seleção considera o caixa total, os slots e os insumos compartilhados. Ela inclui Flip e Crafting quando há um par que cabe. Cada receita reserva um slot para comprar os materiais em sequência. **A confirmar** identifica uma projeção condicional, por exemplo quando há pouco volume, preço antigo, requisito em tokens ou custo acima do teto. O texto junto ao item identifica a condição.

## Registrar um flip

1. Abra um item em **Flip**. Confira os preços, a idade dos trades, o volume, o buy limit e o custo do lote. Use **Calculadora** para testar valores próprios.
2. Crie a oferta de compra no jogo e registre-a no painel. Em **Ofertas e posições**, registre cada execução com o preço pago e a quantidade. Marque a coleta depois de recolher no jogo o GP e os itens indicados.
3. Faça a oferta de venda no GE e registre-a pelo estoque disponível. As execuções de venda geram lucro ou prejuízo realizado pelo custo dos lotes mais antigos já coletados. O GP da venda volta ao caixa livre quando a coleta for registrada.
4. Consulte **Histórico** para revisar os preços executados, as tarifas e o resultado de cada venda. O CSV exporta esse registro.

## Dados e estimativas

O painel usa o catálogo, as últimas compras e vendas instantâneas e os agregados de 5 minutos e 1 hora da [API de preços do RS3](https://runescape.wiki/w/RuneScape:Real-time_Prices). O detalhe do flip mostra o histórico de 24 h e o preço-guia do [histórico Weird Gloop](https://runescape.wiki/w/RuneScape:Grand_Exchange_Market_Watch/Usage_and_APIs).

O tamanho sugerido considera o orçamento, o teto por operação, os slots e o buy limit. Flip rápido cruza os volumes dos dois lados de até 30 min e 1 h. Equipamentos usam janelas de até 6 h e lotes menores. Crafting usa compras instantâneas para estimar o custo dos insumos e considera o giro dos insumos e da saída. Quando a receita exige tokens, o painel informa a quantidade à parte e os custos em GP podem ser ajustados na simulação. Os preços são de trades concluídos. Confira a disponibilidade e o limite vigente no jogo, incluindo grupos de itens e compras feitas fora do painel.

O registro manual e as calculadoras funcionam quando a API estiver indisponível. Se houver cache, consulte os resultados marcados como **A confirmar** ou abra **Catálogo completo e favoritos** em **Flip**. O servidor local conserva configurações, ofertas, execuções, posições e cache em `.merch/merch.sqlite3`. Para copiar o banco como backup, encerre o servidor primeiro.

O workflow **Publicar painel** prepara a versão pública a cada push em `main`. Para testá-la localmente, rode `python build_pages.py`, depois `python -m http.server --bind 127.0.0.1 --directory dist 8080` e abra [127.0.0.1:8080/merch-rs3/](http://127.0.0.1:8080/merch-rs3/).

