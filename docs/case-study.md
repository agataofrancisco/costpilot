# Estudo de caso — CostPilot

## Problema

Usar sempre o modelo caro desperdiça dinheiro; usar sempre o barato degrada a qualidade e pode custar mais por
resposta correcta, por causa de retries e falhas. O CostPilot escolhe, por pedido, o modelo mais barato que
cumpre a qualidade exigida, e mede o custo por tarefa resolvida.

## Abordagem

- Política determinística e explicável (custo esperado em cascata com restrição de qualidade).
- Validação programática que decide o escalonamento.
- Orçamento atómico por equipa, com reserva antes de cada tentativa.
- Benchmark com as mesmas 100 tarefas sintéticas para três políticas.

## Resultados medidos (mock, simulados)

Fonte: `reports/ablation.md`, run de 2026-11-21, seed 7, commit `d397900` (com alterações não commitadas no momento do run).

| Política | Tarefas resolvidas | Custo total (sim.) USD | Escalonamentos |
|---|---|---|---|
| always_expensive | 97/100 | 0.027750 | 0 |
| always_cheap | 69/100 | 0.000910 | 0 |
| hybrid | 97/100 | 0.013924 | 7 |

Leitura com cautela: os perfis de qualidade e os preços são fictícios. Estes números mostram que a mecânica
funciona (a cascata escala onde o barato falha e o orçamento regista o custo de todas as tentativas). Não mostram
o comportamento de modelos reais.

Verificações que suportam a mecânica (todas em testes automáticos, 150 a passar):

- escalonamento após JSON inválido com custo das duas tentativas registado;
- recusa de escalonamento por orçamento, com o custo já gasto indicado;
- 100 pedidos concorrentes contra um orçamento limitado nunca excedem o limite (store em memória e fakeredis);
- cache nunca cruza equipas nem tenants.

Em 2026-11-24, a prova isolada com Redis real 7.4.11 passou (`pytest -m redis`:
`1 passed, 174 deselected`). Dos 100 pedidos concorrentes de 0,02 USD, exatamente 50 foram
aceites; o gasto final foi 1 USD e não ficaram reservas pendentes. Esta prova cobre o orçamento,
não a cache nem o caminho HTTP completo.

## Limitações assumidas

- Cache Redis e caminho HTTP completo ainda não verificados com Redis real.
- Sem providers reais: nenhuma chave foi usada.
- Painel sem verificação visual no browser.
- Sem autenticação de cliente (ver `security-review.md`).

## Métricas de portefólio (por medir)

- Redução de custo por tarefa resolvida face a `always_expensive` com modelos reais: TODO: medir
- Latência p95 com providers reais: TODO: medir
- Custo real de uma execução com `--max-usd`: TODO: medir

## O que faria a seguir

1. Executar o benchmark com modelos reais e um tecto de gasto explícito, guardando os logs.
2. Calibrar o juiz (se for usado) contra uma amostra com labels humanos.
3. Medir a taxa de falsos negativos da validação em respostas abertas.
4. Explorar uma fracção pequena de pedidos em candidatos excluídos (bandit) para evitar o efeito de exclusão permanente.
