# Envio-automatico-de-email
O código deve receber os dados enviados de um formulário do Wordpress através de um webhook e fazer o envio automático de um e-mail para o lead.

Para o envio dos e-mails eu usei uma plataforma chamada Resend, vc consegue criar uma conta de graça por lá e gerar suas chaves para poder criar seu próprio projeto.

Como funciona:

1 - O usuário preenche o seu formulário no WordPress.
2 - O WordPress envia os dados para seu servidor via webhook.
3 - O Script processa os dados e dispara um e-mail de resposta automática.

No Wordpress, configure o webhook apontando para: https://seuservidor.com/webhook?secret=SEU_WEBHOOK_SECRET

OBSERVAÇÃO:

Nesse plano free da Resend podem ser enviados até 3000 E-mails por mês, mais do que isso será necessário o Upgrade do plano.
