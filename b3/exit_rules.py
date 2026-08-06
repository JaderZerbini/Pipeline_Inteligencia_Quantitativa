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

__all__ = [
    "Saida",
    "com_niveis",
    "intradiaria",
    "no_fechamento",
    "trailing_com_alvo",
    "trailing_producao",
]


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


def trailing_com_alvo(
    entrada: float,
    pico: float,
    abertura: float,
    maxima: float,
    minima: float,
    fechamento: float,
    tp_pct: float,
    sl_pct: float,
) -> Saida | None:
    """Meio-termo entre os dois modelos medidos: ratchet do trailing + alvo fixo.

    A tabela 3.3 de ESTRATEGIA.md compara dois extremos, e nenhum domina: o
    stop fixo com alvo rende +2,02%/trade contra +1,16% do trailing, mas com o
    dobro da frequência de perda além de -10%. Os dois eixos que os separam são
    independentes — o **stop** (fixo na entrada vs móvel do topo) e o **alvo**
    (existe vs não existe). Esta variante isola isso: fica com o stop móvel, que
    é de onde vem a cauda menor, e acrescenta o alvo, de onde provavelmente vem
    o retorno maior.

    Regras, na ordem de `intradiaria` — inclusive o empate conservador, que aqui
    importa mais: o stop móvel sobe para perto do alvo, então candles que tocam
    os dois níveis ficam comuns, não raros.

    ``pico`` segue a mesma convenção de ``trailing_producao``: topo dos pregões
    anteriores, atualizado por quem chama **depois** desta checagem.
    """
    nivel_stop = pico * (1.0 - sl_pct)
    nivel_tp = entrada * (1.0 + tp_pct)

    if abertura <= nivel_stop:
        return Saida(abertura, "gap_baixa")
    if abertura >= nivel_tp:
        return Saida(abertura, "gap_alta")

    if minima <= nivel_stop:
        return Saida(nivel_stop, "stop")
    if maxima >= nivel_tp:
        return Saida(nivel_tp, "take_profit")
    return None


def com_niveis(saida, *, tp_pct: float = None, sl_pct: float = None):
    """Fixa ``tp_pct``/``sl_pct`` de um modelo, para varrer parâmetro.

    O backtester passa as constantes ``_TAKE_PROFIT``/``_STOP_LOSS`` em toda
    chamada. Sem isto, comparar -5% contra -10% exigiria mexer nessas constantes
    entre execuções — global mutável no meio de um estudo, com resultado
    dependendo da ordem em que as regras rodaram.

    O que **não** for passado continua vindo de quem chama, para a variante não
    congelar silenciosamente um parâmetro que o estudo não estava variando.
    """
    def wrapper(entrada, pico, abertura, maxima, minima, fechamento, tp, sl):
        return saida(
            entrada, pico, abertura, maxima, minima, fechamento,
            tp if tp_pct is None else tp_pct,
            sl if sl_pct is None else sl_pct,
        )

    base = getattr(saida, "__name__", str(saida))
    marcas = [f"{rot}={pct * 100:g}" for rot, pct in (("tp", tp_pct), ("sl", sl_pct))
              if pct is not None]
    wrapper.__name__ = f"{base}[{', '.join(marcas)}]"
    return wrapper
