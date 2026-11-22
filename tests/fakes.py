"""Cliente IA falso para pruebas (sin red)."""

import hashlib
import math

from guiospro.services.ai_client import AIUnavailable


def _vec(text: str, dim: int = 16) -> list[float]:
    words = text.lower().split()
    v = [0.0] * dim
    for w in words:
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % dim] += 1
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class FakeAI:
    def __init__(self, responder=None, fail=False):
        self.responder = responder
        self.fail = fail
        self.calls: list[tuple[str, str, str]] = []

    def embed(self, texts, kind, progress=None):
        if self.fail:
            raise AIUnavailable("caída simulada")
        return [_vec(t) for t in texts]

    def generate_json(self, model, system_instruction, content, schema):
        if self.fail:
            raise AIUnavailable("caída simulada")
        self.calls.append((model, system_instruction, content))
        return schema.model_validate(self.responder(content, schema))

    async def agenerate_json(self, model, system_instruction, content, schema):
        return self.generate_json(model, system_instruction, content, schema)
