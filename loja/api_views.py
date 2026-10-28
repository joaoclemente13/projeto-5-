from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from django.db.models import Avg, Count, Prefetch
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Avaliacao, Categoria, ItemPedido, Pedido, Produto
from .payments import simulated_payment_gateway
from .serializers import (
    CriarAvaliacaoSerializer,
    ItemAvaliacaoPendenteSerializer,
    PedidoSerializer,
    ProdutoFiltroSerializer,
    ProdutoSerializer,
)


class ProdutoListCreateView(generics.ListCreateAPIView):
    serializer_class = ProdutoSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        filtros = ProdutoFiltroSerializer(data=self.request.query_params)
        filtros.is_valid(raise_exception=True)
        valores = filtros.validated_data
        queryset = (
            Produto.objects.select_related('categoria')
            .prefetch_related(
                Prefetch(
                    'avaliacoes',
                    queryset=Avaliacao.objects.order_by('-criado_em'),
                )
            )
            .annotate(
                media_avaliacoes=Avg('avaliacoes__nota'),
                quantidade_avaliacoes=Count('avaliacoes'),
            )
            .order_by('nome')
        )

        categoria_id = valores.get('categoria')
        if categoria_id is not None:
            if not Categoria.objects.filter(pk=categoria_id).exists():
                raise ValidationError(
                    {'categoria': 'A categoria informada não existe.'}
                )
            queryset = queryset.filter(categoria_id=categoria_id)
        if 'preco_min' in valores:
            queryset = queryset.filter(preco__gte=valores['preco_min'])
        if 'preco_max' in valores:
            queryset = queryset.filter(preco__lte=valores['preco_max'])
        return queryset

    def perform_create(self, serializer):
        serializer.save(vendedor=self.request.user)


class PedidoCreateView(generics.CreateAPIView):
    queryset = Pedido.objects.all()
    serializer_class = PedidoSerializer
    permission_classes = [IsAuthenticated]


class AvaliacaoListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            ItemPedido.objects.filter(
                pedido__comprador=self.request.user,
            )
            .exclude(pedido__status='CANCELADO')
            .filter(avaliacao__isnull=True)
            .select_related('produto', 'pedido')
            .order_by('-pedido__criado_em')
        )

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return CriarAvaliacaoSerializer
        return ItemAvaliacaoPendenteSerializer


class PagamentoSimuladoView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pedido_id):
        pedido = get_object_or_404(
            Pedido,
            pk=pedido_id,
            comprador=request.user,
        )
        if pedido.status != 'ABERTO':
            raise ValidationError(
                {'pedido': 'Somente pedidos abertos podem iniciar pagamento.'}
            )
        resultado = simulated_payment_gateway.create_payment(pedido)
        return Response(resultado, status=202)
