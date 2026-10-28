from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Categoria(models.Model):
    nome = models.CharField(max_length=80, unique=True)

    def __str__(self):
        return self.nome


class Produto(models.Model):
    vendedor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='produtos',
    )
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        related_name='produtos',
    )
    nome = models.CharField(max_length=150)
    descricao = models.TextField(blank=True)
    preco = models.DecimalField(max_digits=10, decimal_places=2)
    estoque = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.nome


class Pedido(models.Model):
    STATUS_CHOICES = [
        ('ABERTO', 'Aberto'),
        ('PAGO', 'Pago'),
        ('ENVIADO', 'Enviado'),
        ('CANCELADO', 'Cancelado'),
    ]

    comprador = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pedidos',
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='ABERTO',
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    @property
    def total(self):
        return sum(item.subtotal for item in self.itens.all())

    def __str__(self):
        return f'Pedido #{self.pk} de {self.comprador}'


class ItemPedido(models.Model):
    pedido = models.ForeignKey(
        Pedido,
        on_delete=models.CASCADE,
        related_name='itens',
    )
    produto = models.ForeignKey(
        Produto,
        on_delete=models.PROTECT,
    )
    quantidade = models.PositiveIntegerField()
    preco_unitario = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    @property
    def subtotal(self):
        return self.quantidade * self.preco_unitario

    def __str__(self):
        return f'{self.quantidade}x {self.produto}'


class Avaliacao(models.Model):
    produto = models.ForeignKey(
        Produto,
        on_delete=models.CASCADE,
        related_name='avaliacoes',
    )
    comprador = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='avaliacoes',
    )
    item_pedido = models.OneToOneField(
        ItemPedido,
        on_delete=models.CASCADE,
        related_name='avaliacao',
    )
    nota = models.PositiveSmallIntegerField()
    comentario = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(nota__gte=1) & Q(nota__lte=5),
                name='loja_avaliacao_nota_1_a_5',
            ),
        ]
        ordering = ('-criado_em',)

    def clean(self):
        if self.nota is not None and not 1 <= self.nota <= 5:
            raise ValidationError({'nota': 'A nota deve estar entre 1 e 5.'})
        if self.item_pedido_id:
            item = self.item_pedido
            if item.produto_id != self.produto_id:
                raise ValidationError(
                    {'produto': 'O produto não corresponde ao item comprado.'}
                )
            if item.pedido.comprador_id != self.comprador_id:
                raise ValidationError(
                    {'comprador': 'A compra não pertence a este comprador.'}
                )
            if item.pedido.status == 'CANCELADO':
                raise ValidationError(
                    {'item_pedido': 'Pedidos cancelados não podem ser avaliados.'}
                )

    def __str__(self):
        return f'{self.nota}/5 - {self.produto}'
