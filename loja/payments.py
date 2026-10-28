class SimulatedPaymentGateway:
    """Desenvolvimento apenas: não contata provedor nem processa cobranças."""

    def create_payment(self, pedido):
        return {
            'modo': 'SIMULACAO',
            'referencia': f'simulacao-pedido-{pedido.pk}',
            'mensagem': (
                'Pagamento simulado; nenhuma cobrança foi realizada '
                'e o pedido continua aguardando pagamento.'
            ),
        }


simulated_payment_gateway = SimulatedPaymentGateway()
