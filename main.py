import uvicorn

from api.config import API_HOST, API_PORT, API_RELOAD


def main():
    """Sobe a API principal usando as configuracoes do ambiente."""
    uvicorn.run(
        "api.app:app",
        host=API_HOST,
        port=API_PORT,
        reload=API_RELOAD,
    )


if __name__ == "__main__":
    main()
