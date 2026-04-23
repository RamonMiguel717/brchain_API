import hashlib
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from api.config import TITLE_SIMILARITY_THRESHOLD

TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "ref",
    "spm",
}


def normalize_text(text: str) -> str:
    """Remove acentos e pontuacao para comparacoes textuais mais estaveis."""
    normalized = unicodedata.normalize("NFKD", text or "")
    without_accents = "".join(
        char for char in normalized
        if not unicodedata.combining(char)
    )
    lowered = without_accents.lower()
    cleaned = re.sub(r"[^\w\s]", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


class NewsDeduplicator:
    """Executa deduplicacao por URL e por semelhanca textual de titulo."""

    def __init__(self, title_similarity_threshold: float = TITLE_SIMILARITY_THRESHOLD):
        self.title_similarity_threshold = title_similarity_threshold

    def normalize_url(self, url: str) -> str:
        """Padroniza a URL removendo rastreadores e pequenas variacoes irrelevantes."""
        if not url:
            return ""

        parsed = urlparse(url)
        filtered_query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
            and key.lower() not in TRACKING_PARAMS
        ]

        normalized = parsed._replace(
            scheme=(parsed.scheme or "https").lower(),
            netloc=parsed.netloc.lower(),
            path=parsed.path.rstrip("/") or "/",
            params="",
            query=urlencode(sorted(filtered_query)),
            fragment="",
        )
        return urlunparse(normalized)

    def hash_url(self, url: str) -> str:
        """Gera a assinatura usada como primeira camada de deduplicacao."""
        if not url:
            return ""
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def tokenize_title(self, title: str) -> set[str]:
        """Separa o titulo em tokens uteis para comparar sobreposicao semantica."""
        tokens = normalize_text(title or "").split()
        return {token for token in tokens if len(token) > 2}

    def title_similarity(self, title_a: str, title_b: str) -> float:
        """Combina Jaccard e similaridade textual para capturar quase-duplicatas.

        Ambos os argumentos devem ser strings brutas do titulo.
        A tokenizacao e normalizacao sao feitas internamente para garantir
        que o SequenceMatcher opere sobre texto real, nao sobre tokens ordenados.
        """
        normalized_a = normalize_text(title_a)
        normalized_b = normalize_text(title_b)

        tokens_a = self.tokenize_title(title_a)
        tokens_b = self.tokenize_title(title_b)

        if not tokens_a or not tokens_b:
            return 0.0

        union = tokens_a | tokens_b
        if not union:
            return 0.0

        jaccard = len(tokens_a & tokens_b) / len(union)
        textual_ratio = SequenceMatcher(None, normalized_a, normalized_b).ratio()
        return max(jaccard, textual_ratio)

    def enrich_article(self, article: dict) -> dict:
        """Anexa campos normalizados que serao reutilizados no pipeline."""
        normalized_url = self.normalize_url(article.get("url", ""))
        title_tokens = sorted(self.tokenize_title(article.get("title", "")))

        enriched = dict(article)
        enriched["url_normalized"] = normalized_url
        enriched["url_hash"] = self.hash_url(normalized_url)
        enriched["title_tokens"] = title_tokens
        return enriched

    def deduplicate(self, articles: list[dict], known_articles: list[dict] | None = None) -> list[dict]:
        """Filtra duplicatas novas contra o lote atual e contra artigos ja persistidos."""
        known_articles = known_articles or []

        seen_hashes: set[str] = {
            item.get("url_hash")
            for item in known_articles
            if item.get("url_hash")
        }

        # Armazena titulos brutos dos artigos conhecidos para comparacao correta.
        known_titles: list[str] = [
            item.get("title", "")
            for item in known_articles
            if item.get("title")
        ]

        unique_articles: list[dict] = []
        seen_titles: list[str] = list(known_titles)

        for article in articles:
            enriched = self.enrich_article(article)
            url_hash = enriched.get("url_hash", "")
            title = article.get("title", "")

            if url_hash and url_hash in seen_hashes:
                continue

            is_similar_title = any(
                self.title_similarity(title, existing_title) >= self.title_similarity_threshold
                for existing_title in seen_titles
                if existing_title
            )

            if is_similar_title:
                continue

            unique_articles.append(enriched)

            if url_hash:
                seen_hashes.add(url_hash)
            if title:
                seen_titles.append(title)

        return unique_articles
