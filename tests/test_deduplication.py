from api.deduplication import NewsDeduplicator, normalize_text


# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------

def test_normalize_text_remove_acentos():
    assert normalize_text("Nutrição") == "nutricao"


def test_normalize_text_remove_pontuacao():
    assert normalize_text("Sono, profundo!") == "sono  profundo"


def test_normalize_text_vazio():
    assert normalize_text("") == ""


def test_normalize_text_none():
    assert normalize_text(None) == ""


# ---------------------------------------------------------------------------
# normalize_url
# ---------------------------------------------------------------------------

def test_normalize_url_remove_utm():
    deduplicator = NewsDeduplicator()
    url = "https://site.com/noticia?id=10&utm_source=google&utm_medium=social"
    result = deduplicator.normalize_url(url)
    assert "utm_source" not in result
    assert "utm_medium" not in result
    assert "id=10" in result


def test_normalize_url_remove_tracking_params():
    deduplicator = NewsDeduplicator()
    url = "https://site.com/noticia?fbclid=abc123&q=saude"
    result = deduplicator.normalize_url(url)
    assert "fbclid" not in result
    assert "q=saude" in result


def test_normalize_url_remove_barra_final():
    deduplicator = NewsDeduplicator()
    url_com = "https://site.com/noticia/"
    url_sem = "https://site.com/noticia"
    assert deduplicator.normalize_url(url_com) == deduplicator.normalize_url(url_sem)


def test_normalize_url_vazio():
    deduplicator = NewsDeduplicator()
    assert deduplicator.normalize_url("") == ""


# ---------------------------------------------------------------------------
# title_similarity — agora recebe strings (correcao do bug de tipos mistos)
# ---------------------------------------------------------------------------

def test_title_similarity_titulos_identicos():
    deduplicator = NewsDeduplicator()
    titulo = "Estudo aponta beneficio do sono para o coracao"
    assert deduplicator.title_similarity(titulo, titulo) == 1.0


def test_title_similarity_titulos_muito_diferentes():
    deduplicator = NewsDeduplicator()
    score = deduplicator.title_similarity(
        "Sono melhora a saude mental",
        "Nutricao e exercicio fisico",
    )
    assert score < 0.3


def test_title_similarity_titulo_vazio():
    deduplicator = NewsDeduplicator()
    score = deduplicator.title_similarity("", "Qualquer titulo")
    assert score == 0.0


def test_title_similarity_com_acentos_diferentes():
    """Titulos com e sem acentos devem ter alta similaridade apos normalizacao."""
    deduplicator = NewsDeduplicator(title_similarity_threshold=0.8)
    score = deduplicator.title_similarity(
        "Estudo aponta benefício do sono profundo para o coração",
        "Estudo aponta beneficio do sono profundo para o coracao",
    )
    assert score >= 0.8


# ---------------------------------------------------------------------------
# deduplicate
# ---------------------------------------------------------------------------

def test_remove_urls_com_mesmo_conteudo_e_parametros_de_tracking():
    deduplicator = NewsDeduplicator()
    articles = [
        {"title": "Vacina reduz internacoes por gripe", "url": "https://site.com/noticia?id=10&utm_source=google"},
        {"title": "Vacina reduz internacoes por gripe", "url": "https://site.com/noticia?id=10&utm_medium=social"},
    ]
    unique_articles = deduplicator.deduplicate(articles)
    assert len(unique_articles) == 1


def test_remove_titulos_muito_parecidos_mesmo_com_urls_diferentes():
    deduplicator = NewsDeduplicator(title_similarity_threshold=0.8)
    articles = [
        {"title": "Estudo aponta beneficio do sono profundo para o coracao", "url": "https://site-a.com/1"},
        {"title": "Estudo aponta beneficios do sono profundo para o coracao", "url": "https://site-b.com/2"},
        {"title": "Treino de forca ajuda no controle glicemico", "url": "https://site-c.com/3"},
    ]
    unique_articles = deduplicator.deduplicate(articles)
    assert len(unique_articles) == 2


def test_artigos_completamente_diferentes_nao_sao_removidos():
    deduplicator = NewsDeduplicator()
    articles = [
        {"title": "Sono melhora a memoria", "url": "https://site-a.com/sono"},
        {"title": "Nutricao plant-based reduz colesterol", "url": "https://site-b.com/nutricao"},
        {"title": "Exercicio aerobico e saude cardiovascular", "url": "https://site-c.com/treino"},
    ]
    unique_articles = deduplicator.deduplicate(articles)
    assert len(unique_articles) == 3


def test_deduplicate_contra_artigos_conhecidos():
    deduplicator = NewsDeduplicator()
    known_articles = [
        {"url_hash": deduplicator.hash_url(deduplicator.normalize_url("https://site.com/noticia")), "title": "Artigo ja salvo"},
    ]
    new_articles = [
        {"title": "Artigo ja salvo", "url": "https://site.com/noticia"},
        {"title": "Artigo novo e diferente", "url": "https://outro.com/novo"},
    ]
    unique_articles = deduplicator.deduplicate(new_articles, known_articles)
    assert len(unique_articles) == 1
    assert unique_articles[0]["title"] == "Artigo novo e diferente"


def test_deduplicate_lista_vazia():
    deduplicator = NewsDeduplicator()
    assert deduplicator.deduplicate([]) == []


def test_deduplicate_sem_artigos_conhecidos():
    deduplicator = NewsDeduplicator()
    articles = [{"title": "Artigo unico", "url": "https://site.com/unico"}]
    result = deduplicator.deduplicate(articles)
    assert len(result) == 1
