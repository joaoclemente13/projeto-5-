from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .admin import PedidoAdmin, ProdutoAdmin
from .models import Avaliacao, Categoria, ItemPedido, Pedido, Produto


class MarketplaceTestData(TestCase):
    def setUp(self):
        self.vendedor = User.objects.create_user(username='seller-one')
        self.vendedor_dois = User.objects.create_user(username='seller-two')
        self.comprador = User.objects.create_user(username='buyer')
        self.categoria = Categoria.objects.create(nome='Livros')
        self.produto = Produto.objects.create(
            vendedor=self.vendedor,
            categoria=self.categoria,
            nome='Livro um',
            descricao='Descrição de teste',
            preco=Decimal('12.50'),
            estoque=5,
        )
        self.produto_dois = Produto.objects.create(
            vendedor=self.vendedor_dois,
            categoria=self.categoria,
            nome='Livro dois',
            descricao='Outro produto',
            preco=Decimal('8.25'),
            estoque=4,
        )

    def definir_carrinho(self, itens):
        sessao = self.client.session
        sessao['carrinho'] = {
            str(produto_id): quantidade
            for produto_id, quantidade in itens.items()
        }
        sessao.save()
        self.client.cookies['sessionid'] = sessao.session_key


class AdminTest(MarketplaceTestData):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.produto_admin = ProdutoAdmin(Produto, admin.site)

    def test_vendedor_visualiza_somente_os_proprios_produtos(self):
        request = self.factory.get(reverse('admin:loja_produto_changelist'))
        request.user = self.vendedor

        produtos = self.produto_admin.get_queryset(request)

        self.assertEqual(list(produtos), [self.produto])
        request.user = SimpleNamespace(is_superuser=True)
        self.assertEqual(
            set(self.produto_admin.get_queryset(request)),
            {self.produto, self.produto_dois},
        )

    def test_vendedor_comum_e_associado_automaticamente_ao_produto(self):
        request = self.factory.post(reverse('admin:loja_produto_add'))
        request.user = self.vendedor
        produto = Produto(
            categoria=self.categoria,
            nome='Produto cadastrado no Admin',
            preco=Decimal('4.00'),
            estoque=1,
        )

        self.produto_admin.save_model(request, produto, form=None, change=False)

        produto.refresh_from_db()
        self.assertEqual(produto.vendedor, self.vendedor)

    def test_pedido_admin_nao_expoe_pedidos_a_vendedor(self):
        pedido_admin = PedidoAdmin(Pedido, admin.site)
        request = self.factory.get(reverse('admin:loja_pedido_changelist'))
        request.user = self.vendedor

        self.assertFalse(pedido_admin.has_module_permission(request))
        self.assertFalse(pedido_admin.has_view_permission(request))


class CarrinhoTest(MarketplaceTestData):
    def test_carrinho_anonimo_exibe_itens_e_calcula_total(self):
        self.definir_carrinho({self.produto.pk: 2, self.produto_dois.pk: 1})

        resposta = self.client.get(reverse('carrinho'))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context['total'], Decimal('33.25'))
        self.assertEqual(len(resposta.context['itens']), 2)

    def test_endpoint_adicionar_ao_carrinho_exige_post(self):
        url = reverse('adicionar_carrinho', args=[self.produto.pk])

        resposta = self.client.get(url)

        self.assertEqual(resposta.status_code, 405)
        self.assertNotIn('carrinho', self.client.session)

    def test_checkout_sem_login_redireciona_sem_criar_pedido(self):
        self.definir_carrinho({self.produto.pk: 1})

        resposta = self.client.post(reverse('checkout'))

        self.assertEqual(resposta.status_code, 302)
        self.assertIn('/api/auth/login/', resposta['Location'])
        self.assertEqual(Pedido.objects.count(), 0)


class CheckoutTest(MarketplaceTestData):
    def test_compra_valida_cria_pedido_reduz_estoque_e_limpa_carrinho(self):
        self.client.force_login(self.comprador)
        self.definir_carrinho({self.produto.pk: 2})

        resposta = self.client.post(reverse('checkout'))

        self.assertEqual(resposta.status_code, 302)
        pedido = Pedido.objects.get(comprador=self.comprador)
        item = ItemPedido.objects.get(pedido=pedido)
        self.assertEqual(item.quantidade, 2)
        self.assertEqual(Produto.objects.get(pk=self.produto.pk).estoque, 3)
        self.assertNotIn('carrinho', self.client.session)

    def test_estoque_insuficiente_preserva_carrinho_sem_pedido_parcial(self):
        self.client.force_login(self.comprador)
        carrinho = {self.produto.pk: 1, self.produto_dois.pk: 5}
        self.definir_carrinho(carrinho)

        resposta = self.client.post(reverse('checkout'))

        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(Pedido.objects.count(), 0)
        self.assertEqual(ItemPedido.objects.count(), 0)
        self.assertEqual(Produto.objects.get(pk=self.produto.pk).estoque, 5)
        self.assertEqual(Produto.objects.get(pk=self.produto_dois.pk).estoque, 4)
        self.assertEqual(
            self.client.session['carrinho'],
            {str(key): value for key, value in carrinho.items()},
        )

    def test_falha_no_segundo_item_reverte_toda_a_transacao(self):
        self.client.force_login(self.comprador)
        carrinho = {self.produto.pk: 2, self.produto_dois.pk: 3}
        self.definir_carrinho(carrinho)
        pedidos_antes = Pedido.objects.count()
        itens_antes = ItemPedido.objects.count()
        estoque_antes = {
            self.produto.pk: self.produto.estoque,
            self.produto_dois.pk: self.produto_dois.estoque,
        }
        criar_item_real = ItemPedido.objects.create
        chamadas = 0

        def falhar_no_segundo_item(**kwargs):
            nonlocal chamadas
            chamadas += 1
            if chamadas == 2:
                raise RuntimeError('Erro forçado para testar a transação')
            return criar_item_real(**kwargs)

        with patch(
            'loja.views.ItemPedido.objects.create',
            side_effect=falhar_no_segundo_item,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                'Erro forçado para testar a transação',
            ):
                self.client.post(reverse('checkout'))

        self.assertEqual(chamadas, 2)
        self.assertEqual(Pedido.objects.count(), pedidos_antes)
        self.assertEqual(ItemPedido.objects.count(), itens_antes)
        self.assertEqual(
            Produto.objects.get(pk=self.produto.pk).estoque,
            estoque_antes[self.produto.pk],
        )
        self.assertEqual(
            Produto.objects.get(pk=self.produto_dois.pk).estoque,
            estoque_antes[self.produto_dois.pk],
        )
        self.assertEqual(
            self.client.session['carrinho'],
            {str(key): value for key, value in carrinho.items()},
        )

    def test_alterar_preco_atual_nao_modifica_preco_historico(self):
        self.client.force_login(self.comprador)
        self.definir_carrinho({self.produto.pk: 1})
        self.client.post(reverse('checkout'))
        item = ItemPedido.objects.get(pedido__comprador=self.comprador)

        Produto.objects.filter(pk=self.produto.pk).update(
            preco=Decimal('99.99')
        )
        item.refresh_from_db()

        self.assertEqual(item.preco_unitario, Decimal('12.50'))


class APITest(MarketplaceTestData):
    def setUp(self):
        super().setUp()
        self.api = APIClient()

    def test_lista_de_produtos_e_publica(self):
        resposta = self.api.get(reverse('api-produtos'))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            {item['nome'] for item in resposta.data},
            {'Livro um', 'Livro dois'},
        )

    def test_criacao_de_produto_anonima_e_bloqueada(self):
        resposta = self.api.post(
            reverse('api-produtos'),
            {
                'nome': 'Tentativa anônima',
                'preco': '2.00',
                'estoque': 1,
                'categoria': self.categoria.pk,
            },
            format='json',
        )

        self.assertIn(resposta.status_code, (401, 403))
        self.assertFalse(Produto.objects.filter(nome='Tentativa anônima').exists())

    def test_vendedor_autenticado_e_associado_ao_novo_produto(self):
        self.api.force_authenticate(user=self.vendedor)

        resposta = self.api.post(
            reverse('api-produtos'),
            {
                'nome': 'Produto pela API',
                'preco': '5.75',
                'estoque': 2,
                'categoria': self.categoria.pk,
                'vendedor': self.vendedor_dois.pk,
            },
            format='json',
        )

        self.assertEqual(resposta.status_code, 201)
        produto = Produto.objects.get(nome='Produto pela API')
        self.assertEqual(produto.vendedor, self.vendedor)

    def test_api_de_pedidos_cria_itens_e_atualiza_estoque(self):
        self.api.force_authenticate(user=self.comprador)

        resposta = self.api.post(
            reverse('api-pedidos'),
            {
                'itens': [
                    {'produto': self.produto.pk, 'quantidade': 2},
                    {'produto': self.produto_dois.pk, 'quantidade': 1},
                ],
            },
            format='json',
        )

        self.assertEqual(resposta.status_code, 201)
        pedido = Pedido.objects.get(comprador=self.comprador)
        self.assertEqual(pedido.itens.count(), 2)
        self.assertEqual(Produto.objects.get(pk=self.produto.pk).estoque, 3)
        self.assertEqual(
            Produto.objects.get(pk=self.produto_dois.pk).estoque,
            3,
        )

    def test_api_rejeita_estoque_insuficiente_sem_criar_pedido(self):
        self.api.force_authenticate(user=self.comprador)

        resposta = self.api.post(
            reverse('api-pedidos'),
            {
                'itens': [
                    {'produto': self.produto.pk, 'quantidade': 1},
                    {'produto': self.produto_dois.pk, 'quantidade': 5},
                ],
            },
            format='json',
        )

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(Pedido.objects.count(), 0)
        self.assertEqual(ItemPedido.objects.count(), 0)
        self.assertEqual(Produto.objects.get(pk=self.produto.pk).estoque, 5)
        self.assertEqual(Produto.objects.get(pk=self.produto_dois.pk).estoque, 4)

    def test_api_rejeita_pedido_sem_itens(self):
        self.api.force_authenticate(user=self.comprador)

        resposta = self.api.post(
            reverse('api-pedidos'),
            {'itens': []},
            format='json',
        )

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(Pedido.objects.count(), 0)

    def test_catalogo_contem_fetch_da_api_e_contador_local(self):
        resposta = self.client.get(reverse('catalogo'))
        conteudo = resposta.content.decode()

        self.assertEqual(resposta.status_code, 200)
        self.assertIn('fetch(`/api/produtos/', conteudo)
        self.assertIn('new URLSearchParams(new FormData(filtros))', conteudo)
        self.assertIn("localStorage.setItem('cartCount'", conteudo)


class APIProdutoFiltroTest(MarketplaceTestData):
    def test_filtro_por_categoria_e_publico(self):
        resposta = APIClient().get(
            reverse('api-produtos'),
            {'categoria': self.categoria.pk},
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(len(resposta.data), 2)

    def test_filtros_de_preco_usam_limites_inclusivos(self):
        resposta = APIClient().get(
            reverse('api-produtos'),
            {'preco_min': '8.25', 'preco_max': '12.49'},
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            [item['nome'] for item in resposta.data],
            ['Livro dois'],
        )

    def test_preco_minimo_e_maximo_funcionam_separadamente(self):
        endpoint = reverse('api-produtos')
        minimo = APIClient().get(endpoint, {'preco_min': '10.00'})
        maximo = APIClient().get(endpoint, {'preco_max': '10.00'})

        self.assertEqual(minimo.status_code, 200)
        self.assertEqual(
            [item['nome'] for item in minimo.data],
            ['Livro um'],
        )
        self.assertEqual(maximo.status_code, 200)
        self.assertEqual(
            [item['nome'] for item in maximo.data],
            ['Livro dois'],
        )

    def test_filtros_rejeitam_valores_invalidos_e_intervalo_invertido(self):
        endpoint = reverse('api-produtos')

        invalido = APIClient().get(endpoint, {'preco_min': 'abc'})
        invertido = APIClient().get(
            endpoint,
            {'preco_min': '12.00', 'preco_max': '8.00'},
        )
        categoria_inesistente = APIClient().get(
            endpoint,
            {'categoria': 999999},
        )

        self.assertEqual(invalido.status_code, 400)
        self.assertEqual(invertido.status_code, 400)
        self.assertEqual(categoria_inesistente.status_code, 400)


class AvaliacoesTest(MarketplaceTestData):
    def setUp(self):
        super().setUp()
        self.pedido = Pedido.objects.create(comprador=self.comprador)
        self.item = ItemPedido.objects.create(
            pedido=self.pedido,
            produto=self.produto,
            quantidade=1,
            preco_unitario=Decimal('12.50'),
        )
        self.api = APIClient()

    def test_avaliacao_exige_autenticacao(self):
        resposta = self.api.post(
            reverse('api-avaliacoes'),
            {'item_pedido': self.item.pk, 'nota': 5},
            format='json',
        )

        self.assertIn(resposta.status_code, (401, 403))
        self.assertEqual(Avaliacao.objects.count(), 0)

    def test_avaliacao_rejeita_nota_invalida_e_compra_inexistente(self):
        self.api.force_authenticate(user=self.comprador)
        nota_invalida = self.api.post(
            reverse('api-avaliacoes'),
            {'item_pedido': self.item.pk, 'nota': 6},
            format='json',
        )
        compra_inexistente = self.api.post(
            reverse('api-avaliacoes'),
            {'item_pedido': 999999, 'nota': 5},
            format='json',
        )

        self.assertEqual(nota_invalida.status_code, 400)
        self.assertEqual(compra_inexistente.status_code, 400)
        self.assertEqual(Avaliacao.objects.count(), 0)

    def test_avaliacao_vincula_comprador_autenticado_e_exibe_media(self):
        self.api.force_authenticate(user=self.comprador)
        resposta = self.api.post(
            reverse('api-avaliacoes'),
            {
                'item_pedido': self.item.pk,
                'nota': 4,
                'comentario': 'Boa leitura',
                'comprador': self.vendedor.pk,
            },
            format='json',
        )

        self.assertEqual(resposta.status_code, 201)
        avaliacao = Avaliacao.objects.get(item_pedido=self.item)
        self.assertEqual(avaliacao.comprador, self.comprador)

        produtos = APIClient().get(reverse('api-produtos')).data
        produto = next(
            item for item in produtos if item['id'] == self.produto.pk
        )
        self.assertEqual(Decimal(produto['media_avaliacoes']), Decimal('4.00'))
        self.assertEqual(produto['quantidade_avaliacoes'], 1)
        self.assertEqual(produto['avaliacoes'][0]['nota'], 4)

        duplicada = self.api.post(
            reverse('api-avaliacoes'),
            {'item_pedido': self.item.pk, 'nota': 5},
            format='json',
        )
        self.assertEqual(duplicada.status_code, 400)

    def test_avaliacao_rejeita_compra_de_outro_usuario_e_cancelada(self):
        self.api.force_authenticate(user=self.vendedor)
        nao_comprada = self.api.post(
            reverse('api-avaliacoes'),
            {'item_pedido': self.item.pk, 'nota': 5},
            format='json',
        )
        self.assertEqual(nao_comprada.status_code, 400)

        self.pedido.status = 'CANCELADO'
        self.pedido.save(update_fields=['status'])
        self.api.force_authenticate(user=self.comprador)
        cancelada = self.api.post(
            reverse('api-avaliacoes'),
            {'item_pedido': self.item.pk, 'nota': 5},
            format='json',
        )
        self.assertEqual(cancelada.status_code, 400)


class PagamentoSimuladoTest(MarketplaceTestData):
    def test_pagamento_simulado_nao_marca_pedido_como_pago(self):
        pedido = Pedido.objects.create(comprador=self.comprador)
        api = APIClient()
        api.force_authenticate(user=self.comprador)

        with patch(
            'loja.api_views.simulated_payment_gateway.create_payment',
            return_value={
                'modo': 'SIMULACAO',
                'referencia': 'simulacao-pedido',
                'mensagem': 'Nenhuma cobrança realizada.',
            },
        ) as gateway:
            resposta = api.post(
                reverse('api-pagamento-simulado', args=[pedido.pk]),
                {},
                format='json',
            )

        self.assertEqual(resposta.status_code, 202)
        self.assertEqual(resposta.data['modo'], 'SIMULACAO')
        gateway.assert_called_once_with(pedido)
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, 'ABERTO')

    def test_pagamento_nao_expoe_pedido_de_outro_comprador(self):
        pedido = Pedido.objects.create(comprador=self.comprador)
        api = APIClient()
        api.force_authenticate(user=self.vendedor)

        resposta = api.post(
            reverse('api-pagamento-simulado', args=[pedido.pk]),
            {},
            format='json',
        )

        self.assertEqual(resposta.status_code, 404)


class PainelVendedorTest(MarketplaceTestData):
    def test_painel_isola_receita_e_conta_apenas_pedidos_nao_cancelados(self):
        pedido_pago = Pedido.objects.create(
            comprador=self.comprador,
            status='PAGO',
        )
        ItemPedido.objects.create(
            pedido=pedido_pago,
            produto=self.produto,
            quantidade=2,
            preco_unitario=Decimal('10.00'),
        )
        ItemPedido.objects.create(
            pedido=pedido_pago,
            produto=self.produto_dois,
            quantidade=1,
            preco_unitario=Decimal('8.25'),
        )
        pedido_cancelado = Pedido.objects.create(
            comprador=self.comprador,
            status='CANCELADO',
        )
        ItemPedido.objects.create(
            pedido=pedido_cancelado,
            produto=self.produto,
            quantidade=10,
            preco_unitario=Decimal('12.50'),
        )
        self.client.force_login(self.vendedor)

        resposta = self.client.get(reverse('painel-vendedor'))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            resposta.context['totais']['unidades_vendidas'],
            2,
        )
        self.assertEqual(
            resposta.context['totais']['receita'],
            Decimal('20.00'),
        )
        self.assertEqual(
            resposta.context['totais']['quantidade_pedidos'],
            1,
        )
        self.assertEqual(
            list(resposta.context['produtos'].values_list('nome', flat=True)),
            ['Livro um'],
        )
        self.assertEqual(
            resposta.context['categorias'][0]['receita'],
            Decimal('20.00'),
        )

    def test_painel_exige_autenticacao_e_apresenta_apenas_dados_do_vendedor(self):
        anonimo = self.client.get(reverse('painel-vendedor'))
        self.assertEqual(anonimo.status_code, 302)

        self.client.force_login(self.vendedor_dois)
        resposta = self.client.get(reverse('painel-vendedor'))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            list(resposta.context['produtos'].values_list('nome', flat=True)),
            ['Livro dois'],
        )
        self.assertEqual(resposta.context['totais']['receita'], Decimal('0.00'))


class LoginTest(MarketplaceTestData):
    def test_carrinho_anonimo_apresenta_link_de_login(self):
        self.definir_carrinho({self.produto.pk: 1})

        resposta = self.client.get(reverse('carrinho'))

        self.assertContains(resposta, '/api/auth/login/')
        self.assertContains(resposta, 'Entre para finalizar a compra.')

    def test_carrinho_permanece_na_sessao_apos_login(self):
        carrinho = {self.produto.pk: 2}
        self.definir_carrinho(carrinho)

        self.client.force_login(self.comprador)

        self.assertEqual(
            self.client.session['carrinho'],
            {str(key): value for key, value in carrinho.items()},
        )


class AdminFluxoTest(MarketplaceTestData):
    def test_vendedor_com_permissao_cria_e_visualiza_apenas_seus_produtos(self):
        self.vendedor.is_staff = True
        self.vendedor.save(update_fields=['is_staff'])
        content_type = ContentType.objects.get_for_model(Produto)
        self.vendedor.user_permissions.add(*Permission.objects.filter(
            content_type=content_type,
            codename__in=('add_produto', 'change_produto', 'view_produto'),
        ))
        self.client.force_login(self.vendedor)

        lista = self.client.get(reverse('admin:loja_produto_changelist'))
        criar = self.client.post(
            reverse('admin:loja_produto_add'),
            {
                'categoria': self.categoria.pk,
                'nome': 'Criado no Admin',
                'descricao': '',
                'preco': '6.50',
                'estoque': 2,
                '_save': 'Salvar',
            },
        )
        outro_produto = self.client.get(
            reverse(
                'admin:loja_produto_change',
                args=[self.produto_dois.pk],
            )
        )

        self.assertEqual(lista.status_code, 200)
        self.assertContains(lista, 'Livro um')
        self.assertNotContains(lista, 'Livro dois')
        self.assertEqual(criar.status_code, 302)
        criado = Produto.objects.get(nome='Criado no Admin')
        self.assertEqual(criado.vendedor, self.vendedor)
        self.assertEqual(outro_produto.status_code, 302)
        self.assertEqual(outro_produto['Location'], '/admin/')
