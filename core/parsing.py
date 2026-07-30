"""Parsing tolerante de respostas JSON dos LLMs (só stdlib).

Os modelos violam com frequência o "responda apenas com JSON": embrulham em
prosa, anexam um segundo objeto (JSONDecodeError "Extra data") ou emitem quebras
de linha cruas dentro das strings (JSONDecodeError "Invalid control character").
Estes helpers recuperam o primeiro objeto válido em vez de derrubar o voto do
modelo no consenso. Sem imports pesados de propósito — os testes importam este
módulo direto, sem arrastar dotenv/SDKs de IA para o CI.
"""

import json

_REQUIRED_FIELDS = {"score", "verdict", "reason", "flags"}


def _strip_leading_plus(text: str) -> str:
    """Remove o ``+`` de números com sinal explícito (``+60`` → ``60``).

    JSON não admite sinal positivo, mas modelos copiam o formato do enunciado
    quando o prompt pede uma faixa tipo "-100 a +100". Observado no
    llama-3.3-70b, que derrubava o próprio voto no consenso com JSONDecodeError.

    A varredura acompanha se está dentro de string (respeitando escapes) para
    não corromper texto livre como ``"alta de +5% no trimestre"``.
    """
    out = []
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if ch == "\\" and in_string:
            out.append(ch)
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        # Fora de string, um "+" só é sinal numérico se vier depois de um
        # delimitador de valor e antes de um dígito.
        if (
            not in_string
            and ch == "+"
            and i + 1 < len(text)
            and text[i + 1].isdigit()
            and text[:i].rstrip()[-1:] in {":", ",", "["}
        ):
            continue  # descarta o sinal
        out.append(ch)
    return "".join(out)


def extract_json_object(text: str) -> dict:
    """Retorna o primeiro objeto JSON presente em ``text``.

    Tolera prosa antes do objeto, cercas markdown (```json), lixo depois do
    objeto ("Extra data"), caracteres de controle não-escapados dentro das
    strings (``strict=False``) e números com ``+`` explícito. Levanta
    ``ValueError`` se ``text`` for None, vazio ou não contiver objeto — o
    chamador trata e cai no fallback.
    """
    if not text or not text.strip():
        raise ValueError("Resposta vazia do modelo")
    start = text.find("{")
    if start == -1:
        raise ValueError("Nenhum objeto JSON na resposta")
    candidate = text[start:]
    decoder = json.JSONDecoder(strict=False)
    # raw_decode lê o primeiro valor JSON e ignora o que vier depois.
    try:
        obj, _ = decoder.raw_decode(candidate)
    except json.JSONDecodeError:
        # Só reescreve depois de falhar: o caminho felizmente nunca é tocado.
        obj, _ = decoder.raw_decode(_strip_leading_plus(candidate))
    return obj


def parse_audit_json(text: str) -> dict:
    """Extrai o objeto de auditoria e valida/normaliza os campos obrigatórios.

    Levanta ``ValueError`` se faltar algum de {score, verdict, reason, flags}.
    Garante ``score`` inteiro em [0, 100] e ``commodity_risk`` com default BAIXO.
    """
    result = extract_json_object(text)
    if not _REQUIRED_FIELDS.issubset(result):
        raise ValueError(f"Campos obrigatórios ausentes: {list(result)}")
    result["score"] = max(0, min(100, int(result["score"])))
    result.setdefault("commodity_risk", "BAIXO")
    return result
