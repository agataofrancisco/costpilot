# Spec Delta

## Purpose

Escolher para cada pedido o modelo com menor custo esperado por tarefa resolvida que cumpra as restrições de qualidade, latência e sensibilidade, e explicar porquê.

## ADDED Requirements

### Requirement: Decisão explicável sem execução
`POST /route` SHALL receber a tarefa (`task_type`, tamanho estimado, requisitos de JSON/ferramentas, SLA de latência, sensibilidade, tecto de custo) e devolver o modelo escolhido, os candidatos considerados, os excluídos com motivo e o custo esperado, sem chamar nenhum provider.

#### Scenario: Extracção JSON simples
- **WHEN** chega uma tarefa `json_extraction` curta com tecto de 0,002 USD
- **THEN** a resposta escolhe um modelo com suporte a JSON mode e explica os motivos de exclusão dos restantes (por exemplo `no_json_mode`, `over_cost_ceiling`)

#### Scenario: Nenhum modelo cumpre as restrições
- **WHEN** nenhum modelo do catálogo cumpre o SLA e o tecto de custo ao mesmo tempo
- **THEN** a resposta é `422` com `code: "no_eligible_model"` e as restrições em conflito

### Requirement: Restrições de sensibilidade
Pedidos marcados como sensíveis MUST ser encaminhados apenas para providers autorizados para dados sensíveis na política da equipa, independentemente do custo.

#### Scenario: Dados sensíveis
- **WHEN** um pedido traz `sensitivity: "high"`
- **THEN** só são considerados modelos de providers com `allow_sensitive: true`

### Requirement: Escalonamento com validação
`POST /execute` SHALL executar o modelo escolhido através do adaptador de provider configurado e, quando a validação programática da tarefa (schema, asserts) falhar e a política o permitir, MUST escalar para o próximo modelo mais forte. O custo de todas as tentativas MUST ser registado e contar para o orçamento.

#### Scenario: JSON inválido no modelo barato
- **WHEN** o modelo barato devolve JSON que não valida o schema
- **THEN** o pedido é repetido no modelo seguinte e o registo mostra as duas tentativas e o custo total

### Requirement: Contabilidade completa do custo
O custo de uma tarefa MUST incluir retries, escalonamentos, reasoning tokens quando reportados e o desconto de prompt caching quando reportado. Os valores ausentes MUST ser marcados como estimados.

#### Scenario: Reasoning tokens reportados
- **WHEN** o provider reporta reasoning tokens
- **THEN** são incluídos no custo da tarefa ao preço correspondente

### Requirement: Interruptor do autopilot
Um admin SHALL poder desligar o autopilot por equipa. Desligado, o routing usa o modelo fixo configurado para a equipa.

#### Scenario: Autopilot desligado
- **WHEN** um admin desliga o autopilot da equipa `marketing`
- **THEN** os pedidos seguintes dessa equipa usam o modelo fixo e o motivo registado é `autopilot_disabled`

### Requirement: Hard-limit de orçamento
Antes de cada tentativa (incluindo escalonamentos), o sistema MUST reservar atomicamente o custo máximo estimado contra o orçamento da equipa e recusar a tentativa se o exceder. Depois da resposta, a reserva SHALL ser reconciliada com o custo real.

#### Scenario: Escalonamento sem orçamento
- **WHEN** o modelo barato falha a validação e o orçamento restante não cobre o modelo seguinte
- **THEN** não há escalonamento e a resposta indica `budget_exceeded` com o custo já gasto

#### Scenario: Concorrência
- **WHEN** 100 pedidos simultâneos competem por um orçamento de 1 USD com preços fictícios
- **THEN** o gasto reconciliado final não excede 1 USD

### Requirement: Execução via ModelMesh opcional
Quando configurado, o sistema SHALL poder usar o ModelMesh como provider, enviando o modelo escolhido, e MUST continuar a contabilizar o custo do lado do CostPilot.

#### Scenario: ModelMesh indisponível
- **WHEN** o provider ModelMesh está configurado mas não responde
- **THEN** o pedido falha com `upstream_unavailable` (ou usa o provider de fallback configurado) e o custo não é contado
