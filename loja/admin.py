from django.contrib import admin

from .models import Avaliacao, Categoria, ItemPedido, Pedido, Produto


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    search_fields = ('nome',)


@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'categoria', 'preco', 'estoque', 'vendedor')
    list_filter = ('categoria',)
    search_fields = ('nome',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(vendedor=request.user)

    def get_exclude(self, request, obj=None):
        return None if request.user.is_superuser else ('vendedor',)

    def save_model(self, request, obj, form, change):
        if not change and not obj.vendedor_id:
            obj.vendedor = request.user
        super().save_model(request, obj, form, change)


class ItemPedidoInline(admin.TabularInline):
    model = ItemPedido
    extra = 0
    readonly_fields = ('preco_unitario',)


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ('id', 'comprador', 'status', 'criado_em')
    list_filter = ('status',)
    inlines = [ItemPedidoInline]

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if not request.user.is_superuser:
            return queryset.none()
        return queryset


@admin.register(Avaliacao)
class AvaliacaoAdmin(admin.ModelAdmin):
    list_display = ('produto', 'comprador', 'nota', 'criado_em')
    list_filter = ('nota',)
    search_fields = ('produto__nome', 'comprador__username')
    readonly_fields = ('produto', 'comprador', 'item_pedido', 'criado_em')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
