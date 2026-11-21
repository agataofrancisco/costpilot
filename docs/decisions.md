# Decisões: o que já existe e o que este projecto acrescenta

## O que os projectos existentes já fazem

- **OpenRouter**: acesso unificado a vários modelos, preços por modelo e routing de fornecedores. Não mede o custo
  por tarefa resolvida nem valida a correcção da resposta.
- **LiteLLM**: proxy compatível com OpenAI, retries, fallback entre modelos e contabilidade de gastos por chave.
  O fallback dispara por erro de provider, não por validação da resposta.
- **ModelMesh** (projecto irmão): quotas, orçamentos, circuit breaker e failover entre providers. Integrado aqui como
  provider opcional, não reimplementado.

## O que este projecto acrescenta

1. **Política por custo esperado em cascata**: `E_k = c_k + (1 - p_k) * E_{k+1}`, com restrição de qualidade por tipo
   de tarefa, em vez de "modelo mais barato" ou "fallback por erro".
2. **Escalonamento por validação programática**: a cascata sobe quando a resposta falha um critério (schema, label,
   resposta final, citação), não quando o provider falha.
3. **Métrica de custo por tarefa resolvida** como critério de avaliação, com baselines `always_expensive`,
   `always_cheap` e a política híbrida sobre o mesmo dataset.
4. **Explicabilidade**: cada exclusão tem um motivo (`low_success_rate`, `pricing_missing`, `not_authorized_sensitive`, ...).
5. **Honestidade de medição**: relatórios marcados como simulados e métricas de portefólio por medir.

## Decisões técnicas e alternativas

| Decisão | Alternativa | Porquê |
|---|---|---|
| Função `decide` pura | Lógica dentro do executor | Mesma política em `/route`, `/execute` e contrafactual; testável sem I/O |
| Montantes em micro-USD inteiros | `Decimal` ou `float` | Lua trabalha com inteiros; soma exacta |
| Reserva pelo pior caso | Reserva pelo custo esperado | Garante o limite antes da chamada |
| Lua para o orçamento | `WATCH/MULTI` | Um script é uma operação atómica sem retries de contenção |
| Prior Beta com pseudo-contagem `k` | Frequência simples | Estável com poucas amostras |
| Validação programática | Juiz LLM | Determinística; juiz exige calibração antes de contar |
| Cache com tenant e equipa na chave | Verificação posterior | O isolamento é propriedade da chave |
| Equipa e tenant vêm da chave de API, nunca do corpo | Equipa no corpo (confiança no cliente) | Sem isto, qualquer cliente gasta o orçamento de outra equipa e lê/polui a cache de outro tenant. Corpo com `team`/`tenant_id` -> 422 (rejeitar, não ignorar: o erro fica visível para quem integra) |
| Chaves guardadas só como SHA-256 | Chave em claro no ficheiro | Se o ficheiro vazar, não há chaves utilizáveis. SHA-256 chega porque as chaves são aleatórias de alta entropia (não são palavras-passe; ver Q no 07) |
| Comparação de todos os digests em tempo constante | `dict` lookup direto | Não revela pela duração qual chave existe |
| Falhar fechado: sem ficheiro de clientes, o arranque falha; sem chave válida, 401 | Arrancar sem autenticação | Evita um serviço aberto por erro de configuração |
| Factory `create_app` | `app` global | Não constrói BD nem providers ao importar |
| Providers mock com seed | Chamadas reais no benchmark | Reproduzível e sem custo; resultado marcado simulado |

## Não está no âmbito

Routing semântico por embeddings, cache semântica, failover multi-provider avançado (papel do ModelMesh) e
classificador aprendido (RouteLLM-like). Ver `proposal.md`.
