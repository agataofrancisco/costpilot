# Revisão de segurança — CostPilot

Âmbito: orçamento, cache entre tenants, chaves e entradas da API. Atualizada após a autenticação por chave
(achado 1). Revisão feita sobre o código de
`backend/app` na versão do commit `f11ea61` e posteriores. Revisão de código e testes; não houve teste de penetração.

## Achados

| # | Área | Achado | Severidade | Estado |
|---|---|---|---|---|
| 1 | Autenticação | Antes, `team` e `tenant_id` vinham do corpo: qualquer cliente gastava o orçamento de outra equipa e lia/poluía a cache de outro tenant. | Alta | **Resolvido** para o modelo de demo. `Authorization: Bearer <chave>` -> SHA-256 -> principal fixo (tenant, equipa) em `config/clients.yaml`. Chave em falta/inválida: `401`. Testes em `backend/tests/test_auth.py`: a chave da equipa A não gasta o orçamento da B; a cache não cruza chaves de equipas ou tenants diferentes mesmo com o corpo a afirmar outra equipa. **Pendente para produção**: gestão e rotação de chaves, expiração, revogação e chaves de longa duração fora do repositório. |
| 1b | Autenticação | As chaves de demonstração estão no repositório (só o digest). A chave em claro `cp-demo-<equipa>-2026` está documentada como demo. | Média | **Aceite para demo**. Produção: `COSTPILOT_CLIENTS_FILE` aponta para um ficheiro fora do repositório com digests novos. Um teste garante que as linhas de dados de `clients.yaml` não contêm a chave em claro. |
| 1c | Autenticação | Chave sem entropia suficiente faria o SHA-256 ser inútil contra força bruta offline. | Média | **Documentado**: o SHA-256 só é adequado a chaves aleatórias de alta entropia (ex.: `secrets.token_urlsafe(32)`). Não usar palavras-passe como chaves de API. |
| 1d | Autenticação | Não há limite de tentativas de autenticação. | Média | **Pendente**: limite de taxa por IP/chave no proxy (TODO). |
| 2 | Admin | Token único e partilhado; comparação em tempo constante (`hmac.compare_digest`). Endpoints desactivados sem token (503). | Média | **Resolvido** para o modelo de demo. Sem RBAC: pendente. |
| 3 | Segredos | `COSTPILOT_ADMIN_TOKEN`, chave OpenAI e chave ModelMesh tipados como `SecretStr` (não aparecem em `repr`). | Média | **Resolvido**. |
| 4 | Segredos no repositório | Nenhum `.env` nem chave versionados. `.gitignore` exclui `.env` e `.env.*`. `.env.example` **não foi escrito** (escrita bloqueada por regra de permissões). | Baixa | **Parcial**: documentado em `README.md`. |
| 5 | Orçamento | Reserva atómica (Lua) com TTL. Reserva expira antes da reconciliação só se o TTL for menor que o timeout do provider; a configuração impede-o (`reservation_ttl >= timeout + 5`). | Alta se errado | **Resolvido** e testado (store em memória, fakeredis e Redis real 7.4.11 em 2026-11-24). |
| 6 | Orçamento | Provider que reporta mais tokens do que o máximo pedido pode gastar acima da reserva. Não há corte. | Média | **Documentado**. Mitigação: `max_tokens` do provider. |
| 7 | Orçamento | Orçamento cumulativo, sem reposição. | Baixa | **Documentado** (TODO). |
| 8 | Cache | Chave SHA-256 com tenant, equipa, modelo, parâmetros e mensagens; separador fora do JSON canónico. Elegibilidade estrita antes de ler. | Alta se errado | **Resolvido** e testado (`test_cache.py`, `test_integration.py`). |
| 9 | Cache | Respostas de pedidos com `sensitivity=high` nunca são guardadas. | Alta | **Resolvido** e testado. |
| 10 | Entrada | Pydantic com `extra="forbid"` nos pedidos. `team` e `tenant_id` **não são aceites no corpo** (422): a identidade vem só da chave. Padrões para `task_id` e modelo. Limites de tamanho por mensagem e de número de mensagens. | Média | **Resolvido**. Falta limite de tamanho total do corpo (TODO, configurar no proxy). |
| 11 | Injecção | Acesso à BD só por SQLAlchemy ORM. Chaves Redis com padrão validado (`[a-z0-9_-]`), sem entrada livre. | Alta se errado | **Resolvido**. |
| 12 | Dados de utilizador | `usage_records` guarda ids, modelos, tokens e custos; **não guarda prompts nem respostas**. | Média | **Resolvido**. |
| 13 | Erros | Erros de provider são mensagens fixas (`HTTP 429`, `timeout`, ...) sem corpo do upstream. | Média | **Resolvido**. |
| 14 | Política de override | `policy_override` (baselines) só com `COSTPILOT_ALLOW_POLICY_OVERRIDE=true`, desligado por omissão. Permite forçar um modelo. | Média | **Resolvido** por omissão; ligar em produção é risco. |
| 15 | Dependências | Versões exactas em `pyproject.toml` e `package-lock.json`. | Baixa | **Resolvido**. Sem auditoria de CVE automática (TODO no CI). |
| 16 | Painel | Token de administração guardado em `sessionStorage` (um separador). Sem CSP definida. | Média | **Parcial**: sem CSP explícita; o build é estático. |
| 17 | CORS | Não há CORS: o painel usa o proxy do Vite em dev. Em produção é preciso servir o painel na mesma origem. | Baixa | **Documentado**. |

## Acções pendentes antes de qualquer exposição pública

1. Gestão de chaves de produção: emissão, rotação, revogação e armazenamento fora do repositório (o registo por chave já existe).
   Limite de tentativas de autenticação.
2. RBAC para os endpoints `/admin`.
3. Limite de tamanho do corpo HTTP e limite de taxa por equipa.
4. CSP e política de cookies/armazenamento para o painel.
