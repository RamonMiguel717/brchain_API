# BRChain

Sistema em Python para ingestão, deduplicação, classificação e recomendação de notícias de saúde com persistência em MongoDB.

## Status

MVP completo com:

- ingestão via GNews (cliente async com `httpx.AsyncClient`)
- persistência de artigos e perfis no MongoDB
- deduplicação por URL normalizada e similaridade de título
- ranking com normalização de preferências e penalização de repetição de tema
- cold-start automático para usuários novos sem histórico
- decay de preferências para evitar perfis congelados no tempo
- API FastAPI totalmente async com CORS habilitado
- scheduler opcional para ingestão automática
- suíte de testes cobrindo todos os módulos principais

## Arquitetura

```text
GNews (async)
  -> deduplicação
  -> classificação por categorias
  -> persistência MongoDB
  -> ranking personalizado
  -> FastAPI (async) / scheduler
```

## Estrutura

```text
brchain/
|- api/
|  |- app.py            # FastAPI, endpoints, CORS, lifespan
|  |- classifier.py     # classificação por keywords
|  |- config.py         # variáveis de ambiente
|  |- deduplication.py  # hash de URL + similaridade de título
|  |- gnews_client.py   # cliente async GNews
|  |- mongo_repository.py
|  |- recommender.py    # ingestão, ranking, feedback
|  |- schemas.py        # modelos Pydantic v2
|  |- service.py        # orquestrador principal
|  `- user_profile.py   # perfil e preferências do usuário
|- scheduler.py
|- tests/
|  |- test_app.py
|  |- test_deduplication.py
|  `- test_recommender.py
|- Tags.json
|- .env.example
|- .gitignore
|- main.py
|- pytest.ini
`- requirements.txt
```

## Principais Componentes

### Artigos

Cada notícia armazenada em `articles` possui:

```json
{
  "title": "Novo estudo relaciona sono e memória",
  "url": "https://site.com/noticia",
  "url_hash": "sha256...",
  "categories": ["Sono", "Pesquisa"],
  "dominant_category": "Sono",
  "normalized_category_scores": { "Sono": 0.7, "Pesquisa": 0.3 },
  "click_count": 3,
  "impression_count": 12,
  "published_at": "2026-04-22T20:00:00Z"
}
```

### Usuários

Perfis em `user_profiles`:

```json
{
  "user_id": "demo-user",
  "preferences": { "Nutrição": 1.8, "Sono": 0.4, "Treino": -0.2 },
  "created_at": "2026-04-22T20:00:00Z",
  "updated_at": "2026-04-22T20:15:00Z"
}
```

Interações em `user_events`:

```json
{
  "user_id": "demo-user",
  "action": "gostei",
  "article_id": "6807...",
  "article_title": "Sono melhora a saúde mental",
  "dominant_category": "Sono",
  "created_at": "2026-04-22T20:16:00Z"
}
```

## Configuração

### 1. Instalar dependências

```bash
pip install -r requirements.txt
```

### 2. Criar o arquivo `.env`

```bash
cp .env.example .env
```

Campos importantes:

| Variável | Descrição |
|---|---|
| `GNEWS_API_KEY` | Chave da API GNews (obrigatória para ingestão) |
| `MONGODB_URI` | URI de conexão com o MongoDB |
| `MONGODB_DB_NAME` | Nome do banco |
| `USE_MOCK_DB` | `true` para rodar sem MongoDB local (desenvolvimento) |
| `DEFAULT_USER_ID` | Usuário padrão usado na ingestão manual e no scheduler |
| `ENABLE_SCHEDULER` | Ativa ingestão periódica junto da API |
| `AUTO_INGEST_ON_STARTUP` | Faz uma ingestão ao subir a aplicação |

### 3. Subir o MongoDB (opcional se usar `USE_MOCK_DB=true`)

```bash
docker run -d -p 27017:27017 --name mongo mongo:7
```

## Como Rodar

### API

```bash
python main.py
```

A API sobe em `http://127.0.0.1:8000`. Documentação interativa disponível em `http://127.0.0.1:8000/docs`.

### Scheduler standalone

```bash
python scheduler.py
```

### Testes

```bash
python -m pytest tests -v
```

## Endpoints

### `GET /health`

Verifica se a API e o MongoDB estão acessíveis.

**Resposta:**
```json
{
  "status": "ok",
  "mongodb": "connected",
  "checked_at": "2026-04-22T20:00:00Z",
  "collections": { "articles": 120, "user_profiles": 3, "user_events": 45 }
}
```

### `GET /feed/{user_id}`

Retorna o feed personalizado e ranqueado.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `limit` | int | 20 | Quantidade máxima de itens (máx. 100) |
| `refresh` | bool | false | Se `true`, executa ingestão antes de gerar o feed |

**Exemplo:**
```
GET /feed/user123?limit=20&refresh=true
```

### `POST /feed/{user_id}/feedback`

Registra feedback explícito e atualiza o perfil do usuário.

```json
{ "article_id": "6807d55b9e9d0d4d6d4d9abc", "action": "gostei" }
```

Aceita `gostei` e `nao_gostei`.

### `POST /feed/{user_id}/click`

Atalho para registrar clique como feedback positivo.

```json
{ "article_id": "6807d55b9e9d0d4d6d4d9abc" }
```

### `GET /articles`

Lista artigos recentes com filtros opcionais.

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `limit` | int | Quantidade (máx. 100) |
| `category` | string | Filtra por categoria (ex: `Sono`) |
| `source_name` | string | Filtra por nome da fonte |

### `GET /profiles/{user_id}`

Retorna o perfil atual com preferências normalizadas e histórico recente.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `events_limit` | int | 10 | Quantidade de eventos recentes |

### `POST /ingest`

Executa ingestão manual.

```
POST /ingest?user_id=demo-user
```

## Lógica de Ranking

O score final combina quatro sinais:

| Sinal | Peso | Descrição |
|---|---|---|
| Afinidade com o perfil | 50% | Produto entre scores do artigo e pesos normalizados do usuário |
| Força do classificador | 20% | Quão fortemente o artigo foi classificado |
| Recência | 20% | Decaimento exponencial com meia-vida configurável |
| Engajamento | 10% | CTR e volume de cliques |

Após o score base, o feed aplica uma penalização de repetição de tema para garantir diversidade de assuntos.

O perfil de preferências usa `tanh` para saturar extremos — um tema muito curtido não domina sozinho o feed. A cada feedback, um decay suave de 0.98 é aplicado para que preferências antigas percam peso gradualmente.

## Deduplicação

Duas camadas de verificação:

1. Hash SHA-256 da URL normalizada (remoção de parâmetros de tracking como `utm_*`, `fbclid`)
2. Similaridade textual de título (Jaccard + SequenceMatcher) para capturar notícias quase iguais publicadas em fontes diferentes

## CORS

A API está configurada com CORS aberto (`allow_origins=["*"]`) para facilitar o desenvolvimento. Em produção, restrinja o valor no `api/app.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://seu-frontend.com"],
    ...
)
```

---

## Integração com Frontend

A API expõe JSON puro e pode ser consumida por qualquer frontend — React, Vue, Svelte, aplicativos mobile ou ferramentas no-code como n8n.

### Configuração inicial

A API roda localmente em `http://127.0.0.1:8000`. Para desenvolvimento, use essa URL diretamente. Para produção, substitua pelo endereço do servidor.

Todas as requisições retornam JSON com `Content-Type: application/json`.

---

### Buscar o feed de um usuário

```javascript
// Exemplo em JavaScript / TypeScript (fetch nativo)
async function getFeed(userId, options = {}) {
  const params = new URLSearchParams({
    limit: options.limit ?? 20,
    refresh: options.refresh ?? false,
  });

  const response = await fetch(
    `http://127.0.0.1:8000/feed/${userId}?${params}`
  );

  if (!response.ok) throw new Error(`Erro ${response.status}`);
  return response.json();
}

// Uso
const feed = await getFeed("demo-user", { limit: 10, refresh: true });

feed.items.forEach(article => {
  console.log(article.title);          // título do artigo
  console.log(article.url);            // link para a notícia
  console.log(article.dominant_category); // categoria principal
  console.log(article.score);          // score final do ranking (0 a 1)
  console.log(article.published_at);   // data ISO 8601
});
```

**Estrutura de cada item do feed:**

```typescript
interface Article {
  id: string;
  title: string | null;
  description: string | null;
  url: string | null;
  source_name: string | null;
  published_at: string | null;          // ISO 8601
  categories: string[];
  dominant_category: string;
  score: number | null;                 // score com diversidade
  raw_score: number | null;             // score antes da penalização
  click_count: number;
  impression_count: number;
  normalized_category_scores: Record<string, number>;
}
```

---

### Registrar clique em um artigo

Chame este endpoint sempre que o usuário clicar em uma notícia. Isso atualiza o perfil automaticamente.

```javascript
async function registerClick(userId, articleId) {
  const response = await fetch(
    `http://127.0.0.1:8000/feed/${userId}/click`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ article_id: articleId }),
    }
  );

  return response.json();
}

// Uso — ao clicar em um card de notícia
await registerClick("demo-user", article.id);
```

---

### Registrar feedback explícito (gostei / não gostei)

```javascript
async function sendFeedback(userId, articleId, action) {
  // action: "gostei" | "nao_gostei"
  const response = await fetch(
    `http://127.0.0.1:8000/feed/${userId}/feedback`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ article_id: articleId, action }),
    }
  );

  if (!response.ok) throw new Error(`Erro ${response.status}`);
  const result = await response.json();

  // result.ranking traz as top categorias do perfil após o feedback
  console.log("Preferências atualizadas:", result.ranking);
  return result;
}

// Uso
await sendFeedback("demo-user", article.id, "gostei");
await sendFeedback("demo-user", article.id, "nao_gostei");
```

---

### Buscar o perfil do usuário

Use para exibir as preferências do usuário ou construir uma tela de "meus interesses".

```javascript
async function getProfile(userId) {
  const response = await fetch(`http://127.0.0.1:8000/profiles/${userId}`);
  return response.json();
}

const profile = await getProfile("demo-user");

// profile.preferences — scores brutos por categoria (podem ser negativos)
// profile.normalized_preferences — scores normalizados entre 0 e 1, soma 1
// profile.recent_events — lista de interações recentes

Object.entries(profile.normalized_preferences)
  .sort(([, a], [, b]) => b - a)
  .slice(0, 5)
  .forEach(([category, score]) => {
    console.log(`${category}: ${(score * 100).toFixed(1)}%`);
  });
```

---

### Exemplo completo com React

```jsx
import { useState, useEffect } from "react";

const API_URL = "http://127.0.0.1:8000";
const USER_ID = "demo-user";

function NewsFeed() {
  const [articles, setArticles] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_URL}/feed/${USER_ID}?limit=20`)
      .then(res => res.json())
      .then(data => setArticles(data.items))
      .finally(() => setLoading(false));
  }, []);

  const handleClick = async (article) => {
    // Abre o artigo e registra o interesse
    window.open(article.url, "_blank");
    await fetch(`${API_URL}/feed/${USER_ID}/click`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ article_id: article.id }),
    });
  };

  const handleFeedback = async (article, action) => {
    await fetch(`${API_URL}/feed/${USER_ID}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ article_id: article.id, action }),
    });
  };

  if (loading) return <p>Carregando feed...</p>;

  return (
    <ul>
      {articles.map(article => (
        <li key={article.id}>
          <h2 onClick={() => handleClick(article)} style={{ cursor: "pointer" }}>
            {article.title}
          </h2>
          <p>{article.description}</p>
          <small>
            {article.dominant_category} · {article.source_name}
          </small>
          <div>
            <button onClick={() => handleFeedback(article, "gostei")}>👍</button>
            <button onClick={() => handleFeedback(article, "nao_gostei")}>👎</button>
          </div>
        </li>
      ))}
    </ul>
  );
}

export default NewsFeed;
```

---

### Variáveis de ambiente no frontend

Nunca exponha a `GNEWS_API_KEY` no frontend — ela fica exclusivamente no servidor. O frontend só precisa conhecer a URL base da API:

```env
# .env no projeto React/Vue/etc
VITE_API_URL=http://127.0.0.1:8000
```

```javascript
const API_URL = import.meta.env.VITE_API_URL;
```

---

### Testando os endpoints via curl

```bash
# Healthcheck
curl http://127.0.0.1:8000/health

# Feed do usuário
curl "http://127.0.0.1:8000/feed/demo-user?limit=5&refresh=true"

# Ingestão manual
curl -X POST "http://127.0.0.1:8000/ingest?user_id=demo-user"

# Registrar clique
curl -X POST http://127.0.0.1:8000/feed/demo-user/click \
  -H "Content-Type: application/json" \
  -d '{"article_id": "SEU_ARTICLE_ID"}'

# Feedback positivo
curl -X POST http://127.0.0.1:8000/feed/demo-user/feedback \
  -H "Content-Type: application/json" \
  -d '{"article_id": "SEU_ARTICLE_ID", "action": "gostei"}'

# Perfil do usuário
curl http://127.0.0.1:8000/profiles/demo-user

# Documentação interativa (abrir no navegador)
open http://127.0.0.1:8000/docs
```

---

## Próximas Melhorias

- autenticação real de usuários (JWT ou OAuth2)
- dashboard administrativo para gerenciar categorias do Tags.json
- filtros avançados no feed (por data, fonte, categoria)
- resumo automático de notícias
- observabilidade com structlog e métricas Prometheus
- deploy com Docker Compose (API + MongoDB + scheduler)
