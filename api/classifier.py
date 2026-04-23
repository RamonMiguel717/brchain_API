from api.deduplication import normalize_text


class NewsClassifier:
    """Classificador simples por regras baseado em palavras-chave e sinonimos."""

    def __init__(self, categorias):
        self.categorias = categorias

    def classificar(self, noticia):
        """Calcula scores por categoria a partir do titulo e da descricao da noticia."""
        texto = (
            (noticia.get("title") or "") + " " +
            (noticia.get("description") or "")
        )
        texto_normalizado = normalize_text(texto)
        tokens = set(texto_normalizado.split())

        scores = {}

        for categoria in self.categorias:
            if not categoria["ativa"]:
                continue

            score = 0.0
            palavras = categoria["keywords"] + categoria["sinonimos"]

            for palavra in palavras:
                termo = normalize_text(palavra)
                if not termo:
                    continue

                if " " in termo:
                    if termo in texto_normalizado:
                        score += 1
                elif termo in tokens:
                    score += 1

            if score > 0:
                scores[categoria["nome"]] = score * categoria["peso_global"]

        return scores

    def normalizar_scores(self, scores):
        """Transforma scores absolutos em proporcoes para comparacao entre categorias."""
        positivos = {
            categoria: float(valor)
            for categoria, valor in scores.items()
            if valor > 0
        }

        total = sum(positivos.values())
        if total == 0:
            return {}

        return {
            categoria: valor / total
            for categoria, valor in positivos.items()
        }

    def categoria_principal_por_scores(self, scores):
        """Escolhe a categoria dominante quando precisamos resumir a noticia em um tema."""
        if not scores:
            return "Geral"

        return max(scores.items(), key=lambda item: item[1])[0]
