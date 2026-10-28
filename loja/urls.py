from django.urls import path

from . import api_views, views


urlpatterns = [
    path('', views.catalogo, name='catalogo'),
    path('carrinho/', views.ver_carrinho, name='carrinho'),
    path(
        'carrinho/adicionar/<int:produto_id>/',
        views.adicionar_ao_carrinho,
        name='adicionar_carrinho',
    ),
    path('checkout/', views.finalizar_compra, name='checkout'),
    path(
        'api/produtos/',
        api_views.ProdutoListCreateView.as_view(),
        name='api-produtos',
    ),
    path(
        'api/pedidos/',
        api_views.PedidoCreateView.as_view(),
        name='api-pedidos',
    ),
    path(
        'api/avaliacoes/',
        api_views.AvaliacaoListCreateView.as_view(),
        name='api-avaliacoes',
    ),
    path(
        'api/pedidos/<int:pedido_id>/pagamento/',
        api_views.PagamentoSimuladoView.as_view(),
        name='api-pagamento-simulado',
    ),
    path(
        'painel/vendedor/',
        views.painel_vendedor,
        name='painel-vendedor',
    ),
]
