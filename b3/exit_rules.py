"""Modelos de saída, para medir quanto do prejuízo vem do modelo e não do mercado.

O simulador original avaliava TP e SL contra o **fechamento**: só saía se o
candle fechasse além do nível. Isso não é o que uma ordem stop faz — ela
dispara assim que o preço toca o nível, durante o pregão. As duas coisas dão
resultados diferentes, e a diferença é justamente onde mora o risco de gap:

- No fechamento, um papel que caiu 25% no dia sai a -25%: o "stop de -7%"
  nunca existiu de fato, era só um teste no fim do dia.
- Intradiário, o mesmo papel sai a -7% **se** o preço passou por lá durante o
  pregão. Se abriu com gap abaixo de -7%, sai na abertura — o stop não
  protege contra o que acontece com o mercado fechado.

Só stdlib, sem pandas — testável no CI, mesmo padrão de `b3/entry_rules.py`.
"""

from typing import NamedTuple

__all__ = ["Saida", "intradiaria", "no_fechamento", "trailing_producao"]


class Saida(NamedTuple):
    """Preço de saída e o motivo, para separar stop honrado de gap.

    Attributes:
        preco:  preço de execução assumido.
        motivo: ``take_profit``, ``stop``, ``gap_baixa`` ou ``gap_alta``.
                ``gap_*`` marca execução na abertura, fora do nível pedido.
    """

    preco: float
    motivo: str


def no_fechamento(
    entrada: float,
    pico: float,
    abertura: float,
    maxima: float,
    minima: float,
    fechamento: float,
    tp_pct: float,
    sl_pct: float,
) -> Saida | None:
    """Modelo original: avalia os níveis apenas contra o fechamento.

    Mantido como padrão porque é a régua que gerou
    ``data/backtest_results.json`` e o gate de compra de produção. Trocar o
    padrão mudaria silenciosamente o que a produção considera aprovado.

    Não representa uma ordem stop real — representa alguém conferindo a cotação
    uma vez por dia, no fim do pregão.

    ``pico`` é ignorado: este modelo mede tudo contra o preço de entrada.
    """
    ret = (fechamento - entrada) / entrada
    if ret >= tp_pct:
        return Saida(fechamento, "take_profit")
    if ret <= -sl_pct:
        return Saida(fechamento, "stop")
    return None


def intradiaria(
    entrada: float,
    pico: float,
    abertura: float,
    maxima: float,
    minima: float,
    fechamento: float,
    tp_pct: float,
    sl_pct: float,
) -> Saida | None:
    """Ordem stop/alvo de verdade, com gap tratado na abertura.

    Regras, em ordem:

    1. Abertura já além de um dos níveis -> executa na abertura (gap). É o
       único caso em que o resultado passa do nível pedido, e é o que o stop
       estruturalmente não consegue evitar.
    2. Mínima tocou o stop **e** máxima tocou o alvo no mesmo candle -> assume
       o **stop**. Com dado diário não dá para saber a ordem dos eventos;
       supor o alvo inflaria o retorno com informação que não existe. Errar
       para o lado conservador aqui é obrigatório: o outro lado transforma
       perda em ganho no papel.
    3. Tocou só um dos níveis -> executa nesse nível.

    ``pico`` é ignorado: os níveis são fixos, ancorados na entrada.
    """
    nivel_stop = entrada * (1.0 - sl_pct)
    nivel_tp = entrada * (1.0 + tp_pct)

    if abertura <= nivel_stop:
        return Saida(abertura, "gap_baixa")
    if abertura >= nivel_tp:
        return Saida(abertura, "gap_alta")

    tocou_stop = minima <= nivel_stop
    tocou_tp = maxima >= nivel_tp

    if tocou_stop:
        return Saida(nivel_stop, "stop")
    if tocou_tp:
        return Saida(nivel_tp, "take_profit")
    return None


def trailing_producao(
    entrada: float,
    pico: float,
    abertura: float,
    maxima: float,
    minima: float,
    fechamento: float,
    tp_pct: float,
    sl_pct: float,
) -> Saida | None:
    """A saída que ``b3/monitor.py`` realmente executa: trailing stop, sem alvo.

    ``check_trailing_stop`` (monitor.py:18) vende quando o preço cai ``sl_pct``
    **do topo já atingido**, não da entrada. E não existe take profit em lugar
    nenhum de ``b3/``, ``paper/`` ou ``core/`` — ``_TAKE_PROFIT`` só existe
    dentro do backtester. Por isso ``tp_pct`` é ignorado aqui: acrescentar alvo
    mediria de novo uma estratégia que a produção não roda.

    ``pico`` é o topo dos pregões **anteriores**; quem chama atualiza com a
    máxima de hoje depois desta checagem. Com barra diária não dá para saber se
    o topo do dia veio antes ou depois da queda, e supor a sequência inventaria
    disparos que talvez não tenham acontecido.

    Ainda é otimista em relação à produção, que confere o preço a cada ~30 min
    e vende a mercado: aqui a execução sai no nível exato, exceto em gap.
    """
    nivel = pico * (1.0 - sl_pct)

    if abertura <= nivel:
        return Saida(abertura, "gap_baixa")
    if minima <= nivel:
        return Saida(nivel, "stop")
    return None
