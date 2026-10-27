"""Adaptador mock: determinístico, sem rede, sem modelo. Padrão (decisão pendente nº 3)."""
from __future__ import annotations

from .base import Context, Proposal, SemanticAdapter


def baseline_narration(ctx: Context) -> str:
    """Narração determinística derivada só dos dados do mundo (também é o fallback do núcleo)."""
    sc = ctx.scene
    if ctx.action == "look":
        parts = [sc["description"]]
        if sc["entities"]:
            parts.append("Você nota: " + ", ".join(e["name"] for e in sc["entities"]) + ".")
        av = [x["label"] for x in sc["exits"] if x.get("available", True)]
        bl = [x["label"] for x in sc["exits"] if not x.get("available", True)]
        if av:
            parts.append("Saídas: " + ", ".join(av) + ".")
        if bl:
            parts.append("Bloqueado: " + ", ".join(bl) + ".")
        return " ".join(parts)
    if ctx.action == "inspect" and ctx.target:
        return ctx.target.get("inspect_text") or ctx.target["description"]
    if ctx.action == "speak":
        said = f'Você diz: "{ctx.text}". ' if ctx.text else ""
        listener = next((e for e in sc["entities"] if e.get("speakable")), None)
        if listener and listener.get("speak_reply"):
            return said + listener["speak_reply"]
        return said + "Suas palavras se perdem no silêncio."
    if ctx.action == "go" and ctx.destination:
        label = ctx.target["label"] if ctx.target else "a saída"
        return f"Você segue por {label}. " + ctx.destination["description"]
    return sc["description"]


class MockAdapter(SemanticAdapter):
    """Sem rede, sem aleatoriedade. Nunca propõe eventos (as consequências vêm do núcleo)."""

    name = "mock"
    model_id = "mock-deterministic-0.1"

    def propose(self, ctx: Context) -> Proposal:
        text = baseline_narration(ctx)
        return Proposal(narration=text, proposed_events=[], audio_request={"kind": "speech", "text": text})
