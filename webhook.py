import os
import json
import requests
from flask import Flask, request, jsonify
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

ZAPI_INSTANCE_ID  = os.getenv("ZAPI_INSTANCE_ID")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN")
ASAAS_API_KEY     = os.getenv("ASAAS_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GRUPO_NOVOS_CLIENTES = os.getenv("GRUPO_NOVOS_CLIENTES")  # ID do grupo Mindor - Novos Clientes

# ── INTERPRETAR MENSAGEM COM CLAUDE ────────────────────────────────────────

def interpretar_mensagem(texto: str) -> dict:
    """Usa Claude para extrair os dados do template da mensagem."""
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
                "content": f"""Extraia os dados do cliente abaixo e retorne APENAS um JSON valido, sem nenhum texto antes ou depois.

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
- valor_total deve ser numero float sem R$ ou pontos (ex: 1500.00)
- primeira_cobranca no formato YYYY-MM-DD
- parcelamento: se 2x quinzenal = "quinzenal", se mensal = "mensal", se a vista = "avista"
- ciclo: extraia apenas os numeros (ex: "5/20")
- Se algum campo nao existir, deixe string vazia ou 0.0"""
            }]
        },
        timeout=30,
    )
    resp.raise_for_status()
    conteudo = resp.json()["content"][0]["text"].strip()
    return json.loads(conteudo)

# ── CADASTRAR CLIENTE NO ASAAS ──────────────────────────────────────────────

def cadastrar_cliente_asaas(dados: dict) -> str:
    """Cadastra o cliente no Asaas e retorna o ID do cliente criado."""
    headers = {
        "access_token": ASAAS_API_KEY,
        "Content-Type": "application/json",
    }

    endereco_completo = dados.get("endereco", "")
    cep = dados.get("cep", "").replace("-", "").strip()

    payload_cliente = {
        "name"         : dados["nome"],
        "cpfCnpj"      : dados["cpf_cnpj"].replace(".", "").replace("-", "").replace("/", ""),
        "mobilePhone"  : dados["telefone"],
        "email"        : dados.get("email", ""),
        "postalCode"   : cep,
        "address"      : endereco_completo,
        "observations" : dados.get("obs", ""),
    }

    resp = requests.post(
        "https://api.asaas.com/v3/customers",
        headers=headers,
        json=payload_cliente,
        timeout=15,
    )
    resp.raise_for_status()
    cliente_id = resp.json()["id"]
    log.info(f"Cliente criado no Asaas: {cliente_id}")
    return cliente_id

def criar_cobrancas_asaas(cliente_id: str, dados: dict) -> list:
    """Cria as cobrancas no Asaas conforme o parcelamento."""
    headers = {
        "access_token": ASAAS_API_KEY,
        "Content-Type": "application/json",
    }

    valor_total      = float(dados["valor_total"])
    parcelamento     = dados["parcelamento"]
    primeira_cobranca = dados["primeira_cobranca"]
    cobracas_criadas = []

    if parcelamento == "avista":
        payload = {
            "customer"   : cliente_id,
            "billingType": "BOLETO",
            "value"      : valor_total,
            "dueDate"    : primeira_cobranca,
            "description": f"Servico Mindor - pagamento unico",
        }
        resp = requests.post("https://api.asaas.com/v3/payments", headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        cobracas_criadas.append(resp.json()["id"])

    elif parcelamento == "mensal":
        ciclo = dados.get("ciclo", "")
        dia_vencimento = int(ciclo.split("/")[0]) if "/" in ciclo else 10

        payload = {
            "customer"       : cliente_id,
            "billingType"    : "BOLETO",
            "value"          : valor_total,
            "nextDueDate"    : primeira_cobranca,
            "cycle"          : "MONTHLY",
            "description"    : "Servico Mindor - mensalidade",
        }
        resp = requests.post("https://api.asaas.com/v3/subscriptions", headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        cobracas_criadas.append(resp.json()["id"])

    elif parcelamento == "quinzenal":
        from datetime import datetime, timedelta

        valor_parcela = round(valor_total / 2, 2)
        primeira = datetime.strptime(primeira_cobranca, "%Y-%m-%d")
        ciclo = dados.get("ciclo", "15/30")
        partes = ciclo.split("/")

        dia1 = int(partes[0])
        dia2 = int(partes[1])

        if primeira.month == 12:
            mes2 = primeira.replace(year=primeira.year + 1, month=1, day=dia2)
        else:
            try:
                mes2 = primeira.replace(month=primeira.month, day=dia2)
            except:
                mes2 = primeira + timedelta(days=15)

        for i, (data, descricao) in enumerate([
            (primeira.strftime("%Y-%m-%d"), "Servico Mindor - parcela 1/2"),
            (mes2.strftime("%Y-%m-%d"),     "Servico Mindor - parcela 2/2"),
        ]):
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

# ── ENVIO DE CONFIRMACAO VIA WHATSAPP ──────────────────────────────────────

def enviar_whatsapp(number: str, mensagem: str):
    requests.post(
        f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_CLIENT_TOKEN}/send-text",
        headers={"Content-Type": "application/json", "client-token": ZAPI_CLIENT_TOKEN},
        json={"phone": number, "message": mensagem},
        timeout=15,
    )

# ── WEBHOOK ─────────────────────────────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        body = request.get_json(force=True)
        log.info(f"Webhook recebido: {json.dumps(body)[:300]}")

        if body.get("fromMe"):
            return jsonify({"ok": True})

        chat_id = body.get("chatId", "") or body.get("from", "")
        if GRUPO_NOVOS_CLIENTES and GRUPO_NOVOS_CLIENTES not in chat_id:
            return jsonify({"ok": True})

        texto = (
            body.get("text", {}).get("message", "")
            or body.get("body", "")
            or ""
        ).strip()

        if "NOVO CLIENTE" not in texto:
            return jsonify({"ok": True})

        log.info("Template de novo cliente detectado!")
        group_id = chat_id

        enviar_whatsapp(group_id,
            "Alfred aqui!\nRecebi os dados do novo cliente. Estou cadastrando no Asaas agora...")

        dados = interpretar_mensagem(texto)
        log.info(f"Dados extraidos: {dados}")

        cliente_id    = cadastrar_cliente_asaas(dados)
        cobracas      = criar_cobrancas_asaas(cliente_id, dados)

        parcelamento_label = {
            "quinzenal": "2x quinzenal",
            "mensal"   : "mensal recorrente",
            "avista"   : "a vista",
        }.get(dados["parcelamento"], dados["parcelamento"])

        confirmacao = (
            f"Cliente cadastrado com sucesso!\n\n"
            f"Nome: {dados['nome']}\n"
            f"CPF/CNPJ: {dados['cpf_cnpj']}\n"
            f"Valor: R$ {dados['valor_total']:,.2f} ({parcelamento_label})\n"
            f"Primeira cobranca: {dados['primeira_cobranca']}\n\n"
            f"ID Asaas: {cliente_id}\n"
            f"{len(cobracas)} cobranca(s) criada(s)"
        )

        enviar_whatsapp(group_id, confirmacao)
        log.info(f"Cliente {dados['nome']} cadastrado com sucesso!")

    except Exception as e:
        log.error(f"Erro no webhook: {e}", exc_info=True)
        try:
            enviar_whatsapp(group_id,
                f"Erro ao cadastrar cliente\n\n{str(e)}\n\nVerifique os dados e tente novamente.")
        except:
            pass

    return jsonify({"ok": True})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "Alfred online"})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    log.info(f"Webhook Alfred iniciado na porta {port}")
    app.run(host="0.0.0.0", port=port)
