"""Construção dos prompts enviados às IAs (só stdlib).

Vive separado de sentiment_analyzer.py de propósito: aquele módulo importa
dotenv e os SDKs de IA no topo, então os testes não podem tocá-lo sem arrastar
essas deps para o CI. Mesmo motivo de core/parsing.py existir.

O prompt do B3 recebe os indicadores técnicos junto da manchete. Sem eles a IA
julga a notícia no vácuo — sabe que houve um anúncio de dividendos, mas não que
o RSI está em 58 e o ativo está 12% acima da MA200, então não consegue dizer se
a notícia confirma ou contradiz o que o preço já mostra.
"""

# Eixo direcional, separado do `score`. O score responde "esse sinal é
# confiável?"; não havia canal para "isso é altista ou baixista?", então
# notícia boa não conseguia virar score alto. Compartilhado pelos dois prompts
# para que a escala seja idêntica em B3 e cripto — comparar os dois depende
# disso.
_IMPACT_INSTRUCTION = (
    "Além do score, devolva 'impact': a direção e a força esperadas no preço, "
    "de -100 (forte pressão de queda) a +100 (forte pressão de alta), com 0 "
    "para neutro ou indeterminado.\n"
    "'impact' e 'score' medem coisas diferentes e NÃO devem ser iguais: "
    "'score' é credibilidade (dá para confiar nesta informação?), 'impact' é "
    "direção (para onde o preço tende?). Uma notícia muito crível de conteúdo "
    "ruim é score alto com impact negativo. Um rumor otimista de fonte fraca é "
    "score baixo com impact positivo."
)

# Campos técnicos injetados no prompt, na ordem de exibição.
# (chave no dict de entrada, rótulo, formatador)
_INDICATOR_FIELDS: list[tuple[str, str, str]] = [
    ("price",          "Preço",              "R$ {:.2f}"),
    ("rsi",            "RSI(14)",            "{:.1f}"),
    ("volume_ratio",   "Volume vs média",    "{:.2f}x"),
    ("pct_from_ma200", "Distância da MA200", "{:+.1f}%"),
    ("hist_trend",     "Tendência",          "{}"),
]


def _format_indicators(indicators: dict) -> str:
    """Renderiza os indicadores como linhas 'Rótulo: valor'.

    Campos ausentes viram N/A explícito em vez de desaparecerem — a IA precisa
    saber que o dado falta, senão preenche a lacuna por conta própria.
    """
    lines = []
    for key, label, fmt in _INDICATOR_FIELDS:
        value = indicators.get(key)
        if value is None:
            lines.append(f"- {label}: N/A")
            continue
        try:
            lines.append(f"- {label}: {fmt.format(value)}")
        except (TypeError, ValueError):
            lines.append(f"- {label}: {value}")
    return "\n".join(lines)


def build_b3_audit_prompt(
    headline: str,
    ticker: str,
    indicators: dict | None = None,
) -> str:
    """Monta o prompt de auditoria de notícia para um ativo da B3.

    Args:
        headline:   Manchete (ou manchetes concatenadas) a auditar.
        ticker:     Ticker sem sufixo, ex. 'PETR4'.
        indicators: Opcional. Aceita as chaves price, rsi, volume_ratio,
                    pct_from_ma200 e hist_trend. Quando ausente ou vazio, o
                    prompt sai sem o bloco técnico — mantém o comportamento
                    antigo para chamadores como b3/validator.py.

    Returns:
        O prompt completo, incluindo o contrato JSON que b3/decision.py consome.
    """
    blocks = [
        "Você é um analista financeiro especializado em B3 e cadeias de "
        "suprimentos globais.",
        f'Analise as manchetes recentes sobre fatores que impactam o ativo '
        f'{ticker} e retorne APENAS JSON válido.',
        f'Manchetes: "{headline}"',
    ]

    if indicators:
        blocks.append(
            f"Indicadores técnicos atuais de {ticker}:\n"
            f"{_format_indicators(indicators)}"
        )
        blocks.append(
            "A manchete CONFIRMA, CONTRADIZ ou é IRRELEVANTE frente ao que "
            "esses indicadores mostram? Uma notícia positiva com o ativo já "
            "esticado acima da média tem menos margem de alta do que a mesma "
            "notícia com o ativo sobrevendido. Considere essa relação no score."
        )
        # Guard obrigatório: sem isto o modelo usa MANIPULACAO para expressar
        # "timing ruim", e MANIPULACAO dispara BLOQUEADO irrevogável no engine.
        blocks.append(
            "ATENÇÃO ao separar os dois eixos: o campo 'verdict' avalia APENAS "
            "a credibilidade da notícia em si. Indicadores técnicos "
            "desfavoráveis (ativo esticado, tendência de baixa, volume fraco) "
            "devem reduzir o 'score', mas NUNCA justificam "
            "verdict=MANIPULACAO. Use MANIPULACAO somente com evidência de "
            "manipulação na própria notícia — fonte duvidosa, promessa "
            "irreal, pump coordenado. Notícia legítima com timing técnico "
            "ruim é verdict=CONFIAVEL ou RUIDO com score baixo."
        )

    blocks.append(
        "Considere impactos INDIRETOS: guerras afetam commodities, que afetam "
        "margens das empresas. Eventos climáticos afetam oferta de "
        "matérias-primas. Decisões de bancos centrais afetam custo de capital."
    )
    blocks.append(_IMPACT_INSTRUCTION)
    blocks.append(
        "Retorne exatamente:\n"
        '{"score": <0-100>, "impact": <-100 a +100>, '
        '"verdict": "<CONFIAVEL|RUIDO|MANIPULACAO>", '
        '"reason": "<uma frase sobre o impacto no ativo>", '
        '"commodity_risk": "<ALTO|MEDIO|BAIXO>", '
        '"flags": [<lista de fatores de risco identificados>]}'
    )
    blocks.append(
        "Score: 70-100=notícia fundamentada com impacto claro no ativo, "
        "40-69=impacto indireto ou incerto, 0-39=sem relação ou manipulação.\n"
        "Responda SOMENTE com o JSON."
    )

    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Cripto
# ---------------------------------------------------------------------------

# Indicadores macro relevantes para cripto: risk-on/risk-off e força do dólar.
# Nada de brent/minério — aquilo move ação de commodity, não BTC.
_MACRO_LABELS: dict[str, str] = {
    "dxy":  "DXY (índice do dólar)",
    "gold": "Ouro",
    "spx":  "S&P 500",
}


def _format_macro(macro: dict) -> str:
    """Renderiza o snapshot macro como linhas legíveis, tolerando None."""
    lines = []
    for key, label in _MACRO_LABELS.items():
        entry = macro.get(key)
        if not entry:
            continue
        price = entry.get("price")
        change = entry.get("change_pct")
        parts = [f"- {label}: {price}"]
        if change is not None:
            parts.append(f"({change:+.1f}% 24h)")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def build_crypto_audit_prompt(
    signal: dict,
    news: str | None = None,
    macro: dict | None = None,
) -> str:
    """Monta o prompt de auditoria de um sinal de cripto.

    Args:
        signal: Saída do crypto/scanner. Usa symbol, price, change_pct_24h,
                rsi_1h, galaxy_score, social_volume_24h e sentiment.
        news:   Opcional. String de manchetes já formatada pelo news_fetcher.
        macro:  Opcional. Snapshot com as chaves dxy/gold/spx.

    Returns:
        O prompt completo com o contrato JSON que crypto/decision.py consome.
    """
    def _fmt(key: str, fmt: str = "{}") -> str:
        value = signal.get(key)
        if value is None:
            return "N/A"
        try:
            return fmt.format(value)
        except (TypeError, ValueError):
            return str(value)

    social_vol = signal.get("social_volume_24h") or 0

    blocks = [
        f"Ativo: {signal.get('symbol', 'N/A')}\n"
        f"Preço: ${_fmt('price', '{:,.2f}')}\n"
        f"Variação 24h: {_fmt('change_pct_24h', '{:+.2f}')}%\n"
        f"RSI(1h): {_fmt('rsi_1h')}\n"
        f"Galaxy Score: {_fmt('galaxy_score')} / 100\n"
        f"Volume social (proxy comunidade): {social_vol:,}\n"
        f"Sentimento: {signal.get('sentiment', 'unknown')}",

        "Nota: volume social é proxy de comunidade (seguidores Twitter+Reddit), "
        "NÃO volume de negociação. Zero indica dado indisponível, não "
        "manipulação. Volume social zero NÃO é evidência de manipulação. "
        "Baseie a avaliação de manipulação APENAS em padrões de preço "
        "(pump súbito, dump rápido, variação >20% em 1h).",
    ]

    if macro:
        rendered = _format_macro(macro)
        if rendered:
            blocks.append(
                "Contexto macro (cripto responde a risk-on/risk-off e à força "
                f"do dólar):\n{rendered}"
            )

    if news:
        blocks.append(news)
        blocks.append(
            "As manchetes CONFIRMAM, CONTRADIZEM ou são IRRELEVANTES frente "
            "aos indicadores acima? Notícia positiva com RSI já alto tem menos "
            "margem de alta do que a mesma notícia com o ativo sobrevendido. "
            "Considere essa relação no score."
        )
        # Mesmo guard do B3: sem isto o modelo usa MANIPULACAO para dizer
        # "timing ruim", e isso dispara BLOQUEADO irrevogável no engine.
        blocks.append(
            "ATENÇÃO ao separar os eixos: 'verdict' avalia APENAS a "
            "credibilidade do sinal e da notícia. Indicadores ou macro "
            "desfavoráveis devem reduzir o 'score', mas NUNCA justificam "
            "MANIPULACAO, PUMP ou FUD_COORDENADO — esses exigem evidência de "
            "manipulação real (pump coordenado, fonte duvidosa, dump súbito). "
            "Sinal legítimo com timing ruim é CONFIAVEL ou RUIDO com score baixo."
        )

    blocks.append(_IMPACT_INSTRUCTION)
    blocks.append(
        'Responda SOMENTE com JSON: '
        '{"score": 0-100, "impact": -100 a +100, '
        '"verdict": "CONFIAVEL|RUIDO|MANIPULACAO|PUMP|FUD_COORDENADO", '
        '"reason": "uma frase curta", "flags": []}'
    )

    return "\n\n".join(blocks)
