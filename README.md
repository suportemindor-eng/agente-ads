# Agente de Relatórios de Ads

Envia automaticamente às 9h para o grupo WhatsApp de cada cliente:

- Saldo disponível na conta
- Alerta se saldo estiver próximo de acabar
- Quanto falta para bater a meta mensal

## Estrutura de arquivos

```
agente-ads/
├── agente.py          ← script principal
├── clientes.json      ← configuração de cada cliente
├── requirements.txt
└── .env.example       ← variáveis de ambiente (não suba com dados reais)
```

## Passo 1 — Meta for Developers

1. Acesse https://developers.facebook.com e crie um app do tipo "Business"
2. Adicione o produto "Marketing API"
3. Em "Tools > Graph API Explorer", selecione seu app
4. Gere um token com as permissões: `ads_read` e `read_insights`

**Token permanente:** Business Manager → Configurações → Usuários do Sistema → Criar usuário → Gere token (não expira)

**account_id:** Acesse https://business.facebook.com/adsmanager — o ID aparece na URL: `act_XXXXXXXXXX`

## Passo 2 — Evolution API (WhatsApp)

1. Acesse https://evolution-api.com e crie uma conta (plano gratuito disponível)
2. Crie uma instância (ex: `meu-zap`)
3. Conecte seu WhatsApp escaneando o QR Code
4. Copie a URL da API e a apikey

**ID do grupo:** Envie uma mensagem no grupo, depois vá em "Chats" no painel da Evolution API e copie o ID (termina em `@g.us`)

## Passo 3 — clientes.json

```json
[
  {
    "nome": "Nome do cliente",
    "meta_account_id": "act_XXXXXXXXXX",
    "meta_access_token": "EAAxxxxxxxxxx",
    "whatsapp_group_id": "120363XXXXXXXXXX@g.us",
    "meta_mensal": 5000.00,
    "alerta_saldo_baixo": 500.00
  }
]
```

## Passo 4 — Deploy no Railway

1. Crie conta em https://railway.app → novo projeto → "Deploy from GitHub repo"
2. Em "Variables" adicione:

```
EVOLUTION_API_URL=https://sua-evolution-api.com
EVOLUTION_API_KEY=sua_chave
EVOLUTION_INSTANCE=nome-da-instancia
```

3. Em "Settings > Start Command": `python agente.py`

## Testar localmente

```bash
pip install -r requirements.txt
RODAR_AGORA=true python agente.py
```

## Adicionar mais clientes

Basta adicionar mais objetos no `clientes.json`. Cada cliente tem seu próprio token Meta, grupo WhatsApp e meta mensal.
