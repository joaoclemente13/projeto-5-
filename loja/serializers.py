from django.db import IntegrityError, transaction
from django.db.models import F
from rest_framework import serializers

from .models import Avaliacao, Categoria, ItemPedido, Pedido, Produto


class ProdutoFiltroSerializer(serializers.Serializer):
    categoria = serializers.IntegerField(min_value=1, required=False)
    preco_min = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        required=False,
    )
    preco_max = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        required=False,
    )

    def validate(self, attrs):
        minimo = attrs.get('preco_min')
        maximo = attrs.get('preco_max')
        if minimo is not None and maximo is not None and minimo > maximo:
            raise serializers.ValidationError(
                'preco_min não pode ser maior que preco_max.'
            )
        return attrs


class AvaliacaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Avaliacao
        fields = ('nota', 'comentario', 'criado_em')
        read_only_fields = ('criado_em',)


class ItemAvaliacaoPendenteSerializer(serializers.ModelSerializer):
    produto_nome = serializers.CharField(source='produto.nome', read_only=True)
    pedido_id = serializers.IntegerField(
        source='pedido_id',
        read_only=True,
    )
    criado_em = serializers.DateTimeField(
        source='pedido.criado_em',
        read_only=True,
    )

    class Meta:
        model = ItemPedido
        fields = ('id', 'produto_nome', 'pedido_id', 'criado_em')


class ProdutoSerializer(serializers.ModelSerializer):
    categoria_nome = serializers.CharField(
        source='categoria.nome',
        read_only=True,
    )
    vendedor = serializers.PrimaryKeyRelatedField(read_only=True)
    media_avaliacoes = serializers.DecimalField(
        max_digits=4,
        decimal_places=2,
        read_only=True,
        allow_null=True,
    )
    quantidade_avaliacoes = serializers.IntegerField(read_only=True)
    avaliacoes = AvaliacaoSerializer(many=True, read_only=True)

    class Meta:
        model = Produto
        fields = (
            'id',
            'nome',
            'descricao',
            'preco',
            'estoque',
            'categoria',
            'categoria_nome',
            'vendedor',
            'media_avaliacoes',
            'quantidade_avaliacoes',
            'avaliacoes',
        )


class CriarAvaliacaoSerializer(serializers.ModelSerializer):
    nota = serializers.IntegerField(min_value=1, max_value=5)
    item_pedido = serializers.PrimaryKeyRelatedField(
        queryset=ItemPedido.objects.select_related('pedido', 'produto'),
    )

    class Meta:
        model = Avaliacao
        fields = ('item_pedido', 'nota', 'comentario')

    def validate_item_pedido(self, item_pedido):
        request = self.context['request']
        if item_pedido.pedido.comprador_id != request.user.pk:
            raise serializers.ValidationError(
                'A compra informada não pertence ao usuário autenticado.'
            )
        if item_pedido.pedido.status == 'CANCELADO':
            raise serializers.ValidationError(
                'Pedidos cancelados não podem ser avaliados.'
            )
        if Avaliacao.objects.filter(item_pedido=item_pedido).exists():
            raise serializers.ValidationError(
                'Este item da compra já foi avaliado.'
            )
        return item_pedido

    def create(self, validated_data):
        item_pedido = validated_data['item_pedido']
        try:
            with transaction.atomic():
                return Avaliacao.objects.create(
                    **validated_data,
                    comprador=self.context['request'].user,
                    produto=item_pedido.produto,
                )
        except IntegrityError:
            raise serializers.ValidationError(
                {'item_pedido': 'Este item da compra já foi avaliado.'}
            ) from None


class ItemPedidoSerializer(serializers.ModelSerializer):
    preco_unitario = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = ItemPedido
        fields = ('produto', 'quantidade', 'preco_unitario')


class PedidoSerializer(serializers.ModelSerializer):
    itens = ItemPedidoSerializer(many=True)

    class Meta:
        model = Pedido
        fields = ('id', 'status', 'criado_em', 'itens')
        read_only_fields = ('status', 'criado_em')

    def validate_itens(self, itens):
        if not itens:
            raise serializers.ValidationError(
                'O pedido deve conter pelo menos um item.'
            )

        produto_ids = [item['produto'].pk for item in itens]
        if len(produto_ids) != len(set(produto_ids)):
            raise serializers.ValidationError(
                'Cada produto deve aparecer apenas uma vez no pedido.'
            )
        if any(item['quantidade'] < 1 for item in itens):
            raise serializers.ValidationError(
                'A quantidade de cada item deve ser pelo menos 1.'
            )
        return itens

    def create(self, validated_data):
        itens_validados = validated_data.pop('itens')
        request = self.context['request']

        with transaction.atomic():
            produto_ids = [item['produto'].pk for item in itens_validados]
            produtos = {
                produto.pk: produto
                for produto in Produto.objects.select_for_update()
                .filter(pk__in=produto_ids)
                .order_by('pk')
            }

            if len(produtos) != len(produto_ids):
                raise serializers.ValidationError(
                    {'itens': 'Um ou mais produtos não estão disponíveis.'}
                )

            for item in itens_validados:
                produto = produtos[item['produto'].pk]
                if produto.estoque < item['quantidade']:
                    raise serializers.ValidationError({
                        'itens': (
                            f'Estoque insuficiente para {produto.nome}.'
                        )
                    })

            pedido = Pedido.objects.create(comprador=request.user)
            for item in itens_validados:
                produto = produtos[item['produto'].pk]
                quantidade = item['quantidade']
                estoque_atualizado = Produto.objects.filter(
                    pk=produto.pk,
                    estoque__gte=quantidade,
                ).update(estoque=F('estoque') - quantidade)
                if estoque_atualizado != 1:
                    raise serializers.ValidationError({
                        'itens': (
                            f'Estoque insuficiente para {produto.nome}.'
                        )
                    })

                ItemPedido.objects.create(
                    pedido=pedido,
                    produto=produto,
                    quantidade=quantidade,
                    preco_unitario=produto.preco,
                )

        return pedido
