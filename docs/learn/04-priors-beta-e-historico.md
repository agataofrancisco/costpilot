# 04 — Priors Beta e histórico

## O problema

A política precisa de uma probabilidade de sucesso `p` por (modelo, tipo de tarefa). Com zero dados não
há base para `p`. Com três amostras, a frequência observada (3/3 = 100%) é pouco fiável. O sistema tem de
começar com uma crença razoável e corrigi-la à medida que chegam dados, sem nunca confiar cegamente
numa amostra pequena.

## O que entra e o que sai

Entra a prior do catálogo (`prior_success` em `config/models.yaml`), a pseudo-contagem `k` (`prior_strength`
em `config/policy.yaml`) e o histórico de tentativas julgadas (`usage_records`). Sai `p` (média posterior)
e o p95 de latência observada.

Exemplos reais dos testes (`backend/tests/test_history.py`):

```text
sem dados:            p = prior = 0.9
10 falhas (k=4):      alpha = 4*0.9 = 3.6 ; beta = 4*0.1 + 10 = 10.4 ; p = 3.6/14 = 0.257
6 ok + 4 falhas (BD): alpha = 3.6 + 6 = 9.6 ; beta = 0.4 + 4 = 4.4 ; p = 9.6/14 = 0.686
```

## Como funciona por dentro

- `beta_posterior` (`backend/app/catalog/history.py:41`) calcula `alpha = k*prior + sucessos` e `beta = k*(1-prior) + falhas`.
- `build_stats` (`history.py:71`) junta contagens e latências. Usa o p95 observado só com `min_latency_samples`
  amostras; antes disso usa `typical_latency_ms` do catálogo.
- `p95_nearest_rank` ignora valores não numéricos vindos da BD (dados não confiáveis).
- O histórico vem de `UsageRepository.judged_samples` (`backend/app/accounting/repository.py`): só tentativas com
  resposta do provider (`ok` ou `validation_failed`). Erros de provider não são julgamento de qualidade.

## Porquê esta escolha

- **Beta é conjugada de Bernoulli**: a actualização é soma de contagens. Sem estado extra e reprodutível a partir do registo.
- **`k` como pseudo-contagem** torna explícito quanto pesa a prior: com `k=4`, equivale a 4 amostras.
- **Média posterior** (`alpha/(alpha+beta)`) é o valor usado na comparação com o alvo de qualidade.
- A latência usa p95 por ser a métrica do SLA; a média esconde a cauda.

## Alternativas

- **Frequência simples (`sucessos/total`)**: instável com poucas amostras.
- **Limite inferior de confiança (ex.: Wilson)**: mais conservador; boa extensão, não implementada.
- **Bandit (Thompson sampling)**: resolve explorar vs aproveitar de forma formal. A política actual nunca explora
  modelos excluídos, por isso um modelo mal avaliado pela prior nunca recebe dados. Limitação conhecida.

## Como falha

- **Prior errada e sem dados**: o modelo fica excluído para sempre, porque nunca é tentado. Mitigação: as priors
  vêm do benchmark, não de intuição, e o admin pode reavaliar (`POST /admin/probes` cobre só capacidades).
- **Janela**: `history_window` limita as tentativas consideradas, para o histórico acompanhar mudanças de modelo.
- Testes: `test_history.py` (prior sem dados, degradação abaixo do alvo, actualização a partir da BD, p95 com entradas
  inválidas, parâmetros inválidos rejeitados).

## Perguntas de entrevista

**Porque Beta e não só a média dos sucessos?**
Com 3 de 3 sucessos a média dá 100%, mas a incerteza é enorme. Beta com prior mantém o valor perto da prior até
haver dados suficientes, e a conta é a mesma soma de contagens.

**O que é o problema de exploração vs aproveitamento aqui?**
Só se aproveita. Um modelo excluído não é testado, por isso o sistema não aprende que ele melhorou. Num sistema
de produção, uma pequena fracção de pedidos devia ser roteada para candidatos excluídos, com um orçamento de
exploração separado. Não está implementado.

**Porque é que o histórico não tem uma tabela própria de agregados?**
Para não haver duas fontes de verdade. O registo de uso é a única fonte; os agregados são calculados sobre ele.
O custo é uma consulta por candidato por pedido, aceitável neste volume; com volume maior, seria um agregado materializado.
