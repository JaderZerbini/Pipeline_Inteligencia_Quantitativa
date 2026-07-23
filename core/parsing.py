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


def extract_json_object(text: str) -> dict:
    """Retorna o primeiro objeto JSON presente em ``text``.

    Tolera prosa antes do objeto, cercas markdown (```json), lixo depois do
    objeto ("Extra data") e caracteres de controle não-escapados dentro das
    strings (``strict=False``). Levanta ``ValueError`` se ``text`` for None,
    vazio ou não contiver objeto — o chamador trata e cai no fallback.
    """
    if not text or not text.strip():
        raise ValueError("Resposta vazia do modelo")
    start = text.find("{")
    if start == -1:
        raise ValueError("Nenhum objeto JSON na resposta")
    # raw_decode lê o primeiro valor JSON e ignora o que vier depois.
    obj, _ = json.JSONDecoder(strict=False).raw_decode(text[start:])
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
