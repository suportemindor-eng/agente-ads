import os
import json
import requests
from flask import Flask, request, jsonify
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

ZAPI_INSTANCE_ID     = os.getenv("ZAPI_INSTANCE_ID")
ZAPI_CLIENT_TOKEN    = os.getenv("ZAPI_CLIENT_TOKEN")
ASAAS_API_KEY        = os.getenv("ASAAS_API_KEY")
ANTHROPIC_API_KEY    = os.getenv("ANTHROPIC_API_KEY")
GRUPO_NOVOS_CLIENTES = os.getenv("GRUPO_NOVOS_CLIENTES", "").replace("@g.us", "").replace("-group", "")

def interpretar_mensagem(texto: str) -> dict:
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1000,
            "messages": [{
                "role": "user",
                "content": f"""Extraia os dados do cliente abaixo e retorne APENAS um JSON válido, sem nenhum texto antes ou depois.

Mensagem:
{texto}

Retorne exatamente neste formato:
{{
  "nome": "",
  "cpf_cnpj": "",
  "telefone": "",
  "email": "",
  "cep": "",
  "endereco": "",
  "valor_total": 0.0,
  "parcelamento": "quinzenal|mensal|avista",
  "primeira_cobranca": "YYYY-MM-DD",
  "ciclo": "5/20|10/25|15/30",
  "obs": ""
}}

Regras:
- valor_total deve ser número float sem R$ ou pontos (ex: 1500.00)
- primeira_cobranca no formato YYYY-MM-DD
- parcelamento: se 2x quinzenal = "quinzenal", se mensal = "mensal", se à vista = "avista"
- ciclo: extraia apenas os números (ex: "15/30")
- Se algum campo não existir, deixe string vazia ou 0.0"""
            }]
        },
        timeout=30,
    )
    resp.raise_for_status()
    conteudo = resp.json()["content"][0]["text"].strip()
    # Remove possíveis backticks
    conteudo = conteudo.replace("```json", "").replace("```", "").strip()
    return json.loads(conteudo)

def cadastrar_cliente_asaas(dados: dict) -> str:
    headers = {
        "access_token": ASAAS_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "name"        : dados["nome"],
        "cpfCnpj"     : dados["cpf_cnpj"].replace(".", "").replace("-", "").replace("/", ""),
        "mobilePhone" : dados.get("telefone", ""),
        "email"       : dados.get("email", ""),
        "postalCode"  : dados.get("cep", "").replace("-", "").strip(),
        "address"     : dados.get("endereco", ""),
        "observations": dados.get("obs", ""),
    }
    resp = requests.post("https://api.asaas.com/v3/customers", headers=headers, json=payload, timeout=15)
    resp.raise_for_status()
    cliente_id = resp.json()["id"]
    log.info(f"✅ Cliente criado no Asaas: {cliente_id}")
    return cliente_id

def criar_cobrancas_asaas(cliente_id: str, dados: dict) -> list:
    from datetime import datetime, timedelta

    headers = {
        "access_token": ASAAS_API_KEY,
        "Content-Type": "application/json",
    }

    valor_total       = float(dados["valor_total"])
    parcelamento      = dados["parcelamento"]
    primeira_cobranca = dados["primeira_cobranca"]
    cobracas_criadas  = []

    if parcelamento == "avista":
        payload = {
            "customer"   : cliente_id,
            "billingType": "BOLETO",
            "value"      : valor_total,
            "dueDate"    : primeira_cobranca,
            "description": "Serviço Mindor — pagamento único",
        }
        resp = requests.post("https://api.asaas.com/v3/payments", headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        cobracas_criadas.append(resp.json()["id"])

    elif parcelamento == "mensal":
        payload = {
            "customer"   : cliente_id,
            "billingType": "BOLETO",
            "value"      : valor_total,
            "nextDueDate": primeira_cobranca,
            "cycle"      : "MONTHLY",
            "description": "Serviço Mindor — mensalidade",
        }
        resp = requests.post("https://api.asaas.com/v3/subscriptions", headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        cobracas_criadas.append(resp.json()["id"])

    elif parcelamento == "quinzenal":
        valor_parcela = round(valor_total / 2, 2)
        primeira      = datetime.strptime(primeira_cobranca, "%Y-%m-%d")
        segunda       = primeira + timedelta(days=15)

        for data, descricao in [
            (primeira.strftime("%Y-%m-%d"), "Serviço Mindor — parcela 1/2"),
            (segunda.strftime("%Y-%m-%d"),  "Serviço Mindor — parcela 2/2"),
        ]:
            payload = {
                "customer"   : cliente_id,
                "billingType": "BOLETO",
                "value"      : valor_parcela,
                "dueDate"    : data,
                "description": descricao,
            }
            resp = requests.post("https://api.asaas.com/v3/payments", headers=headers, json=payload, timeout=15)
            resp.raise_for_status()
            cobracas_criadas.append(resp.json()["id"])

    return cobracas_criadas

def enviar_whatsapp(phone: str, mensagem: str):
    # Normaliza o phone — remove @g.us e -group, Z-API aceita só os números
    phone = phone.replace("@g.us", "").replace("-group", "")
    try:
        resp = requests.post(
            f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_CLIENT_TOKEN}/send-text",
            headers={"Content-Type": "application/json", "client-token": ZAPI_CLIENT_TOKEN},
            json={"phone": phone, "message": mensagem},
            timeout=15,
        )
        resp.raise_for_status()
        log.info(f"✅ Mensagem enviada para {phone}")
    except Exception as e:
        log.error(f"❌ Erro ao enviar WhatsApp: {e}")

@app.route("/webhook", methods=["POST"])
def webhook():
    group_id = None
    try:
        body = request.get_json(force=True, silent=True) or {}
        log.info(f"Webhook recebido do grupo: {body.get('phone', 'desconhecido')}")

        # Ignora mensagens enviadas pelo próprio bot
        if body.get("fromMe"):
            return jsonify({"ok": True})

        # Pega o phone/chatId
        phone = body.get("phone", "") or body.get("chatId", "") or body.get("from", "")

        # Normaliza para comparar com GRUPO_NOVOS_CLIENTES
        phone_norm = phone.replace("@g.us", "").replace("-group", "")

        # Verifica se veio do grupo correto
        if GRUPO_NOVOS_CLIENTES and GRUPO_NOVOS_CLIENTES not in phone_norm:
            log.info(f"Mensagem ignorada — não é do grupo Novos Clientes ({phone_norm})")
            return jsonify({"ok": True})

        group_id = phone

        # Extrai o texto da mensagem
        texto = (
            body.get("text", {}).get("message", "") if isinstance(body.get("text"), dict)
            else body.get("text", "")
            or body.get("body", "")
            or body.get("caption", "")
            or ""
        ).strip()

        log.info(f"Texto recebido: {texto[:100]}")

        if "NOVO CLIENTE" not in texto:
            return jsonify({"ok": True})

        log.info("📋 Template de novo cliente detectado!")

        # Confirma recebimento
        enviar_whatsapp(group_id,
            "🤖 Alfred aqui!\nRecebi os dados do novo cliente. Estou cadastrando no Asaas agora...")

        # Interpreta com Claude
        dados = interpretar_mensagem(texto)
        log.info(f"Dados extraídos: {dados}")

        # Cadastra no Asaas
        cliente_id = cadastrar_cliente_asaas(dados)
        cobracas   = criar_cobrancas_asaas(cliente_id, dados)

        parcelamento_label = {
            "quinzenal": "2x quinzenal",
            "mensal"   : "mensal recorrente",
            "avista"   : "à vista",
        }.get(dados["parcelamento"], dados["parcelamento"])

        confirmacao = (
            f"✅ Cliente cadastrado com sucesso!\n\n"
            f"👤 {dados['nome']}\n"
            f"📄 CPF/CNPJ: {dados['cpf_cnpj']}\n"
            f"💰 Valor: R$ {float(dados['valor_total']):,.2f} ({parcelamento_label})\n"
            f"📅 Primeira cobrança: {dados['primeira_cobranca']}\n\n"
            f"🔗 ID Asaas: {cliente_id}\n"
            f"📨 {len(cobracas)} cobrança(s) criada(s)\n\n"
            f"_Alfred — Mordomo da Mindor_ 🎩"
        )

        enviar_whatsapp(group_id, confirmacao)
        log.info(f"✅ Cliente {dados['nome']} cadastrado com sucesso!")

    except Exception as e:
        log.error(f"❌ Erro no webhook: {e}", exc_info=True)
        if group_id:
            enviar_whatsapp(group_id,
                f"❌ Erro ao cadastrar cliente\n\{str(e)}\n\nVerifique os dados e tente novamente.")

    return jsonify({"ok": True})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "Alfred online 🎩"})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    log.info(f"Webhook Alfred iniciado na porta {port}")
    app.run(host="0.0.0.0", port=port)
