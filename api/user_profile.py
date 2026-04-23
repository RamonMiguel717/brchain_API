import math

from api.config import PREFERENCE_SATURATION


class UserProfile:
    """Representa o estado de afinidade do usuario por categoria."""

    def __init__(self, categorias: list[dict], preferences: dict | None = None):
        self.preferences: dict[str, float] = {
            categoria["nome"]: 0.0
            for categoria in categorias
            if categoria.get("ativa")
        }

        if preferences:
            for categoria, valor in preferences.items():
                self.preferences[categoria] = float(valor)

    def atualizar(self, categorias_noticia: dict[str, float], acao: str) -> None:
        """Ajusta as preferencias a partir do feedback positivo ou negativo."""
        if acao not in {"gostei", "nao_gostei"}:
            raise ValueError("Acao invalida. Use 'gostei' ou 'nao_gostei'.")

        direction = 1.0 if acao == "gostei" else -1.0

        for categoria, peso in categorias_noticia.items():
            self.preferences.setdefault(categoria, 0.0)
            self.preferences[categoria] += direction * float(max(peso, 0.0))

    def aplicar_decay(self, fator: float = 0.95) -> None:
        """Reduz gradualmente preferencias antigas para evitar perfis congelados no tempo."""
        for categoria in self.preferences:
            self.preferences[categoria] *= fator

    def pesos_normalizados(self, saturation: float = PREFERENCE_SATURATION) -> dict[str, float]:
        """Satura extremos para impedir que um tema domine sozinho o perfil."""
        saturation = max(saturation, 0.1)
        normalized = {
            categoria: 0.5 + (math.tanh(valor / saturation) / 2)
            for categoria, valor in self.preferences.items()
        }

        total = sum(normalized.values())
        if total == 0:
            return {}

        return {
            categoria: valor / total
            for categoria, valor in normalized.items()
        }

    def ranking(self, normalizado: bool = True) -> list[tuple[str, float]]:
        """Retorna as categorias ordenadas por forca atual no perfil."""
        scores = self.pesos_normalizados() if normalizado else self.preferences
        return sorted(scores.items(), key=lambda item: item[1], reverse=True)
