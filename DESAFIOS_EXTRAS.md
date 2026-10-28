# Desafios extras — Marketplace Simplificado

## Funcionalidades

### Avaliações

- `Avaliacao` registra produto, comprador, item de pedido, nota de 1 a 5, comentário opcional e data.
- O endpoint autenticado `GET /api/avaliacoes/` lista somente itens comprados pelo usuário que ainda podem ser avaliados.
- `POST /api/avaliacoes/` recebe `item_pedido`, `nota` e, opcionalmente, `comentario`. O comprador é sempre o usuário autenticado. Itens de outro comprador, pedidos cancelados, notas inválidas e avaliações repetidas são rejeitados.
- `GET /api/produtos/` inclui média, quantidade e avaliações; o catálogo as apresenta nos cards.
- O Admin permite consultar avaliações, sem criá-las ou editá-las por ali.

Exemplo de POST autenticado:

```json
{
  "item_pedido": 12,
  "nota": 5,
  "comentario": "Boa leitura"
}
```

### Pagamento

Não foram encontradas variáveis de ambiente de sandbox Stripe ou Mercado Pago. Foi adicionada uma interface desacoplada de **simulação local**, sem SDK, chamadas externas, armazenamento de credenciais, cobrança ou alteração do status do pedido.

`POST /api/pedidos/<id>/pagamento/` exige autenticação e propriedade do pedido. Responde `202` com uma referência identificada como `SIMULACAO`; não marca o pedido como pago. Não existe callback de sucesso nem integração real. Uma futura integração de sandbox deverá verificar o resultado no provedor e validar a assinatura do webhook antes de alterar o estado do pedido.

### Filtros e catálogo

`GET /api/produtos/` aceita `categoria`, `preco_min` e `preco_max`. Parâmetros inválidos, categoria inexistente ou limites invertidos retornam erro de validação. Os preços são interpretados como `Decimal`. O catálogo permite selecionar categoria e faixa de preço e refaz a consulta à API.

### Painel do vendedor

`/painel/vendedor/` exige login e mostra somente os produtos, vendas e receita do usuário autenticado. As agregações usam o preço histórico dos itens e ignoram pedidos cancelados. Pedidos abertos não cancelados são contabilizados conforme o critério solicitado; o painel não os apresenta como pagos.

## Como testar

Use o ambiente virtual local:

```powershell
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\venv\Scripts\python.exe manage.py test
```

Os testes utilizam a base isolada do Django. As rotas novas para testes manuais são:

- `GET /api/produtos/?categoria=1&preco_min=10&preco_max=100`
- `GET /api/avaliacoes/` e `POST /api/avaliacoes/` (autenticados)
- `POST /api/pedidos/<id>/pagamento/` (autenticado, apenas simulação)
- `/painel/vendedor/` (autenticado)

Para testar vendas, crie produtos e pedidos pela aplicação ou Admin com contas locais já configuradas. Nenhuma conta ou senha foi criada nesta implementação.

## Limitações e decisões

- Não há processamento de pagamentos nem credenciais disponíveis para sandbox; a simulação não confirma pagamentos.
- A avaliação é associada a um item de pedido e aceita pedidos em qualquer status exceto `CANCELADO`, em coerência com o fluxo atual de pedidos.
- O painel conta todos os pedidos não cancelados, inclusive `ABERTO`; eles são contagens de pedidos e receita registrada, não confirmação de recebimento.
- `select_for_update()` não garante bloqueio de linha no SQLite. O checkout e a criação de pedidos pela API mantêm atualizações condicionais de estoque e transações atômicas.
- Vendedores não superusuários não veem nem administram pedidos no Django Admin, evitando exposição de pedidos de outros clientes. A administração de pedidos fica reservada aos superusuários.
- Nenhum framework de frontend ou integração externa foi adicionado.

## Arquivos

- `loja/models.py` e `loja/migrations/0002_avaliacao.py`: modelo e restrição de nota.
- `loja/serializers.py`, `loja/api_views.py`, `loja/urls.py`: avaliações, filtros e simulação.
- `loja/payments.py`: interface de pagamento simulada.
- `loja/views.py` e `loja/templates/loja/painel_vendedor.html`: painel isolado por vendedor.
- `loja/admin.py`: consulta somente leitura de avaliações e pedidos restritos a superusuários.
- `loja/templates/loja/base.html` e `loja/templates/loja/catalogo.html`: apresentação responsiva e filtros.
- `loja/tests.py`: testes automatizados dos desafios, preservando a suíte anterior.
