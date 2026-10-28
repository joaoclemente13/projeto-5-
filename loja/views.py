from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, DecimalField, F, Q, Sum, Value
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.db.models.functions import Coalesce
from django.views.decorators.http import require_POST

from .models import Categoria, ItemPedido, Pedido, Produto


class ErroCheckout(Exception):
    pass


def _ler_carrinho(request):
    carrinho = request.session.get('carrinho', {})
    if not isinstance(carrinho, dict):
        raise ValueError('O carrinho da sessão está em formato inválido.')

    itens = {}
    for produto_id, quantidade in carrinho.items():
        try:
            produto_id = int(produto_id)
            quantidade = int(quantidade)
        except (TypeError, ValueError):
            raise ValueError('O carrinho contém um item inválido.') from None
        if produto_id <= 0 or quantidade <= 0:
            raise ValueError('O carrinho contém um item inválido.')
        itens[str(produto_id)] = quantidade
    return itens


def _quantidade_total(carrinho):
    return sum(carrinho.values())


def catalogo(request):
    try:
        cart_count = _quantidade_total(_ler_carrinho(request))
    except ValueError:
        cart_count = 0
    return render(
        request,
        'loja/catalogo.html',
        {
            'cart_count': cart_count,
            'categorias': Categoria.objects.order_by('nome'),
        },
    )


@require_POST
def adicionar_ao_carrinho(request, produto_id):
    try:
        produto = Produto.objects.get(pk=produto_id)
    except Produto.DoesNotExist:
        return JsonResponse(
            {'erro': 'Produto não encontrado.'},
            status=404,
        )

    try:
        carrinho = _ler_carrinho(request)
    except ValueError as exc:
        return JsonResponse({'erro': str(exc)}, status=400)

    chave = str(produto_id)
    quantidade = carrinho.get(chave, 0)
    if quantidade + 1 > produto.estoque:
        return JsonResponse(
            {'erro': 'Estoque insuficiente para adicionar este produto.'},
            status=409,
        )

    carrinho[chave] = quantidade + 1
    request.session['carrinho'] = carrinho
    request.session.modified = True
    return JsonResponse({'total_itens': _quantidade_total(carrinho)})


def _montar_carrinho(request):
    try:
        carrinho = _ler_carrinho(request)
    except ValueError:
        carrinho = {}

    produtos = Produto.objects.in_bulk(
        int(produto_id) for produto_id in carrinho
    )
    itens = []
    total = Decimal('0.00')
    for produto_id, quantidade in carrinho.items():
        produto = produtos.get(int(produto_id))
        subtotal = (
            produto.preco * quantidade
            if produto is not None
            else Decimal('0.00')
        )
        itens.append({
            'produto': produto,
            'quantidade': quantidade,
            'subtotal': subtotal,
        })
        total += subtotal
    return itens, total


def ver_carrinho(request):
    itens, total = _montar_carrinho(request)
    try:
        cart_count = _quantidade_total(_ler_carrinho(request))
    except ValueError:
        cart_count = 0
    return render(
        request,
        'loja/carrinho.html',
        {
            'itens': itens,
            'total': total,
            'cart_count': cart_count,
        },
    )


@login_required
def painel_vendedor(request):
    vendas_validas = ~Q(itempedido__pedido__status='CANCELADO')
    receita_item = F('itempedido__quantidade') * F(
        'itempedido__preco_unitario'
    )
    valor_zero = Value(
        Decimal('0.00'),
        output_field=DecimalField(max_digits=20, decimal_places=2),
    )
    produtos = (
        Produto.objects.filter(vendedor=request.user)
        .select_related('categoria')
        .annotate(
            unidades_vendidas=Coalesce(
                Sum(
                    'itempedido__quantidade',
                    filter=vendas_validas,
                ),
                Value(0),
            ),
            receita=Coalesce(
                Sum(receita_item, filter=vendas_validas),
                valor_zero,
            ),
            quantidade_pedidos=Count(
                'itempedido__pedido',
                filter=vendas_validas,
                distinct=True,
            ),
        )
        .order_by('nome')
    )
    itens_vendidos = ItemPedido.objects.filter(
        produto__vendedor=request.user
    ).exclude(pedido__status='CANCELADO')
    totais = itens_vendidos.aggregate(
        unidades_vendidas=Coalesce(
            Sum('quantidade'),
            Value(0),
        ),
        receita=Coalesce(
            Sum(
                F('quantidade') * F('preco_unitario'),
                output_field=DecimalField(
                    max_digits=20,
                    decimal_places=2,
                ),
            ),
            valor_zero,
        ),
        quantidade_pedidos=Count('pedido', distinct=True),
    )
    categorias = (
        itens_vendidos.values('produto__categoria__nome')
        .annotate(
            unidades_vendidas=Sum('quantidade'),
            receita=Sum(
                F('quantidade') * F('preco_unitario'),
                output_field=DecimalField(
                    max_digits=20,
                    decimal_places=2,
                ),
            ),
        )
        .order_by('produto__categoria__nome')
    )
    return render(
        request,
        'loja/painel_vendedor.html',
        {
            'produtos': produtos,
            'categorias': categorias,
            'totais': totais,
            'cart_count': 0,
        },
    )


@login_required
@require_POST
def finalizar_compra(request):
    try:
        carrinho = _ler_carrinho(request)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('/carrinho/')

    if not carrinho:
        messages.warning(request, 'Seu carrinho está vazio.')
        return redirect('/carrinho/')

    try:
        with transaction.atomic():
            produtos = {
                produto.pk: produto
                for produto in Produto.objects.select_for_update()
                .filter(pk__in=[int(produto_id) for produto_id in carrinho])
                .order_by('pk')
            }

            if len(produtos) != len(carrinho):
                raise ErroCheckout(
                    'Um ou mais produtos do carrinho não estão mais disponíveis.'
                )

            for produto_id, quantidade in carrinho.items():
                if produtos[int(produto_id)].estoque < quantidade:
                    raise ErroCheckout(
                        f'Estoque insuficiente para {produtos[int(produto_id)].nome}.'
                    )

            pedido = Pedido.objects.create(comprador=request.user)
            for produto_id, quantidade in sorted(
                carrinho.items(),
                key=lambda item: int(item[0]),
            ):
                produto = produtos[int(produto_id)]
                estoque_atualizado = Produto.objects.filter(
                    pk=produto.pk,
                    estoque__gte=quantidade,
                ).update(estoque=F('estoque') - quantidade)
                if estoque_atualizado != 1:
                    raise ErroCheckout(
                        f'Estoque insuficiente para {produto.nome}.'
                    )

                ItemPedido.objects.create(
                    pedido=pedido,
                    produto=produto,
                    quantidade=quantidade,
                    preco_unitario=produto.preco,
                )
    except ErroCheckout as exc:
        messages.error(request, str(exc))
        return redirect('/carrinho/')

    request.session.pop('carrinho', None)
    request.session.modified = True
    messages.success(request, 'Compra finalizada com sucesso.')
    return redirect('/')
