import httpx

from api.config import (
    API_KEY,
    BASE_URL,
    DEFAULT_COUNTRY,
    DEFAULT_ENDPOINT,
    DEFAULT_LANGUAGE,
    DEFAULT_MAX_RESULTS,
)


class GNewsClient:
    """Cliente async para consultar noticias da GNews com os parametros padrao do projeto."""

    def __init__(self, endpoint=DEFAULT_ENDPOINT, timeout=10.0):
        self.endpoint = endpoint
        self.timeout = timeout

    async def get_news(
        self,
        query: str,
        lang: str = DEFAULT_LANGUAGE,
        country: str = DEFAULT_COUNTRY,
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> list[dict]:
        """Executa uma busca na GNews e retorna apenas a lista de artigos."""
        if not API_KEY:
            raise ValueError("A variavel GNEWS_API_KEY nao esta configurada.")

        url = f"{BASE_URL}/{self.endpoint}"
        params = {
            "q": query,
            "lang": lang,
            "country": country,
            "max": max_results,
            "apikey": API_KEY,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Erro ao consultar a GNews: {exc}") from exc

        payload = response.json()
        return payload.get("articles", [])
