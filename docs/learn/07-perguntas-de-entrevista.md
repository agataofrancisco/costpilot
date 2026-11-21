# 07 — Perguntas de entrevista

Cada resposta aponta para o código ou o teste que a sustenta. Os números vêm dos testes ou de `reports/ablation.md`.

## Métricas e política

**1. Porque é que medes custo por tarefa resolvida e não custo por token?**
Porque o custo por token não vê retries nem respostas erradas. Um modelo barato com 40% de falhas pode custar mais por
resposta correcta. Ver `02-custo-por-tarefa-resolvida.md`. No benchmark, `always_cheap` tem custo total baixo (0.000910 USD simulados)
mas resolve 69% das tarefas.

**2. Como é calculado o custo esperado de um candidato?**
`E_k = c_k + (1 - p_k) * E_{k+1}`, calculado do mais caro para o mais barato entre os elegíveis (`routing/policy.py`,
`_autopilot_decision`). `c_k` é o custo de uma tentativa com o tamanho de entrada do pedido.

**3. Porque é que a qualidade é um filtro e não parte do custo?**
Para não haver um modelo barato escolhido só por ser barato. Primeiro garante-se `p >= alvo`; depois minimiza-se o custo.
`test_low_success_rate_excludes_model_below_quality_target`.

**4. O que acontece quando nenhum modelo cumpre tudo?**
`422 no_eligible_model` com a lista de conflitos. Não há substituição silenciosa. `test_route_returns_422_with_conflicts_when_nothing_fits`.

**5. Porque é que `decide` é uma função pura?**
Mesma decisão em `/route`, `/execute` e contrafactual; testável com factos sintéticos (`test_policy.py`).

**6. Qual é o papel de `k` (prior_strength) na prior Beta?**
É a pseudo-contagem: com `k=4` e prior 0.9, a prior vale como 4 amostras. Com poucos dados domina a prior; com muitos, o histórico.

**7. Porque é que o histórico usa a média posterior e não a frequência?**
Frequência com 3 de 3 sucessos dá 100% sem incerteza. A média posterior com prior mantém o valor perto da prior até haver dados.
`test_history.py::test_without_data_the_estimate_is_the_prior`.

**8. Qual é a limitação do histórico tal como está?**
Não há exploração: um modelo excluído nunca recebe tráfego, por isso não pode recuperar. Um bandit com uma fracção de exploração resolveria isso (`04-priors-beta-e-historico.md`).

## Cascata e validação

**9. Porque é que a cascata escala por validação e não por erro do provider?**
Um provider que responde com JSON errado não falhou tecnicamente; falhou a tarefa. Os dois casos têm tratamentos
diferentes: falha de provider passa ao seguinte sem validar; validação falhada escala com o custo registado.

**10. Como validas uma resposta sem juiz LLM?**
Por tipo: label exacto normalizado, schema tipado (JSON), `FINAL:` exacto e citação literal. `routing/validators.py`.
Um juiz exigiria calibração contra labels humanos antes de contar.

**11. O que acontece quando o validador recebe lixo?**
Nunca lança excepção: devolve falha. `test_validators.py::test_json_extraction_never_raises_on_hostile_or_malformed_output`.

**12. Porque é que um timeout cobra a reserva inteira?**
O provider pode ter processado e cobrado. Sobrestimar protege o orçamento; subestimar cria dívida invisível (`accounting_rules.py`).

**13. Porque é que a escalada respeita o tecto de custo pedido?**
`_over_request_ceiling` compara o gasto acumulado mais o pior caso da próxima tentativa com o tecto. Se exceder, para com `stop_reason: over_cost_ceiling`.

## Orçamento e concorrência

**14. Porque é que o orçamento usa Lua e não `GET` seguido de `INCRBY`?**
Entre o `GET` e o `INCRBY` outro cliente pode passar. O script Lua é executado sem intercalação no servidor (`budget/redis_store.py`).

**15. Porque é que a reserva é do pior caso?**
O limite tem de ser garantido antes da chamada. O custo esperado pode ser excedido por uma resposta longa.

**16. O que acontece se o processo morrer entre reservar e reconciliar?**
A reserva expira ao fim do TTL e é libertada na próxima operação. O risco é um custo real não reconciliado se o provider já tiver respondido. Documentado em `01-...`.

**17. Porque é que o TTL tem de exceder o timeout do provider?**
Senão uma reserva expira enquanto o pedido ainda está em curso e o orçamento sobre-compromete-se. `config.py` impede a configuração errada.

**18. Como testaste a concorrência?**
`test_hundred_concurrent_requests_never_exceed_one_dollar` (threads, store em memória e fakeredis) e
`test_concurrent_requests_never_overspend_the_team_budget` (100 pedidos HTTP no mesmo loop, com escalonamento).
Com Redis real: pendente (`test_budget_redis_real.py`, `-m redis`).

**19. Porque é que os montantes são inteiros?**
Floats acumulam erro e o Lua trabalha com doubles. Micro-USD inteiros dão soma exacta e o arredondamento para cima é conservador.

**20. Quem é o responsável por um custo que o provider reporta acima do pior caso?**
Hoje, o orçamento aceita o custo real e fica acima do limite nesse caso. É uma limitação documentada em `security-review.md`, achado 6.

## Cache

**21. Como garantes que duas equipas nunca partilham uma resposta?**
Tenant e equipa estão na chave (SHA-256). Não há verificação posterior. `test_cache_never_crosses_teams`.

**22. Porque é que a elegibilidade é verificada antes de ler a cache?**
Ler uma entrada que não devia ser lida já é um vazamento se a resposta for devolvida ou registada.

**23. Porque é que a chave inclui `max_tokens`?**
Uma resposta truncada não é igual a uma completa; incluí-lo evita servir uma resposta truncada a quem pediu mais.

**24. Porque é que a cache não guarda temperatura > 0?**
Não há determinismo: reutilizar uma resposta muda o comportamento esperado. `test_non_zero_temperature_is_never_cached`.

## Arquitectura e segurança

**25. Porque é que o ModelMesh é um provider e não uma dependência?**
Cada repositório tem de correr e ser avaliado sozinho. Com o ModelMesh configurado, o orçamento continua verificado aqui
(defesa dupla). `design.md`, D0.

**26. Quais são os maiores riscos de segurança?**
Ausência de autenticação de cliente (equipa e tenant vêm do pedido) e token de administração único. Ver `security-review.md`,
achados 1 e 2. Ambos são pendentes antes de exposição pública.

**27. Porque é que os segredos são `SecretStr`?**
Para não aparecerem em `repr`, logs ou erros de validação. `config.py`.

**28. Porque é que o painel não tem CORS?**
Em desenvolvimento o Vite faz proxy de `/admin`; em produção o painel deve ser servido na mesma origem. Achado 17.

## Honestidade de medição

**29. Porque é que o relatório diz que é simulado?**
Os providers são mock com preços e perfis fictícios. Publicar uma poupança seria afirmar algo sem logs reais. As métricas de
portefólio ficam `TODO: medir`. `reports/ablation.md`.

**30. Como sabes que o benchmark é reproduzível?**
O mock decide com `sha256(seed, modelo, task_id, tentativa, mensagens)`: a mesma entrada dá o mesmo resultado. Cada política
corre numa base de dados nova. `bench/costpilot/runner.py`.

**31. O que faltaria para uma poupança publicável?**
Logs de execução com modelos reais, tecto de gasto (`--max-usd`), várias seeds e intervalos de confiança.

**32. Porque é que não usaste um juiz LLM?**
Sem calibração contra labels humanos, um juiz não conta para as métricas principais. A correcção é programática: exacta ou F1 de campos.

## Engenharia

**33. Como lidas com dados vindos do provider?**
Como não confiáveis. `parsing.py` nunca lança excepção: um formato inesperado vira `invalid_response`. `test_providers.py`.

**34. Porque é que a configuração falha no arranque?**
Um erro na política ou no catálogo levaria a decisões erradas em silêncio. `ConfigError` com mensagem clara (`test_catalog.py`).

**35. Como testas um cliente Redis sem Redis?**
Com fakeredis, que executa o Lua via lupa. Tentei `fakeredis.TcpFakeServer` para o caminho de rede, mas não respondeu ao PING nesta
máquina; o teste foi removido em vez de ficar a bloquear. Isto fica registado como limitação.

**36. Porque é que a API é uma factory?**
Importar o módulo não deve criar a base de dados nem os providers. Os testes e as ferramentas importam sem efeitos colaterais (`main.py`).
