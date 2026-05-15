import os
import json
import requests
from datetime import datetime, date
import schedule
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────
# CONFIGURAÇÃO DO WHATSAPP (Z-API)
# ──────────────────────────────────────────

ZAPI_INSTANCE_ID  = os.getenv("ZAPI_INSTANCE_ID")   # ex: 3F3255AAC50962FAEA378295E5A4DFF2
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN")  # ex: F40153BEB48635FC1AE40EAC

# ──────────────────────────────────────────
# META ADS — busca dados da conta
# ──────────────────────────────────────────

def buscar_dados_meta(account_id: str, access_token: str) -> dict:
    """Busca saldo disponível, gasto do mês e limite diário via Graph API."""
    base = "https://graph.facebook.com/v19.0"

    # Dados da conta (saldo, limite, status)
    url_conta = f"{base}/{account_id}"
    params_conta = {
        "fields": "balance,amount_spent,spend_cap,daily_budget,currency,name",
        "access_token": access_token,
    }
    resp_conta = requests.get(url_conta, params=params_conta, timeout=15)
    resp_conta.raise_for_status()
    conta = resp_conta.json()

    # Gasto do mês corrente
    hoje = date.today()
    inicio_mes = hoje.replace(day=1).strftime("%Y-%m-%d")
    fim_mes = hoje.strftime("%Y-%m-%d")

    url_insights = f"{base}/{account_id}/insights"
    params_insights = {
        "fields": "spend",
        "time_range": json.dumps({"since": inicio_mes, "until": fim_mes}),
        "access_token": access_token,
    }
    resp_insights = requests.get(url_insights, params=params_insights, timeout=15)
    resp_insights.raise_for_status()
    insights = resp_insights.json()

    gasto_mes = 0.0
    if insights.get("data"):
        gasto_mes = float(insights["data"][0].get("spend", 0))

    # Converte centavos → reais (Meta retorna em centavos de moeda local)
    saldo = float(conta.get("balance", 0)) / 100
    spend_cap = float(conta.get("spend_cap", 0)) / 100

    return {
        "nome_conta": conta.get("name", "Conta sem nome"),
        "moeda": conta.get("currency", "BRL"),
        "saldo_disponivel": saldo,
        "gasto_mes": gasto_mes,
        "limite_total": spend_cap,
    }

# ──────────────────────────────────────────
# CÁLCULOS E ALERTAS
# ──────────────────────────────────────────

def calcular_status(dados_meta: dict, config_cliente: dict) -> dict:
    saldo = dados_meta["saldo_disponivel"]
    gasto_mes = dados_meta["gasto_mes"]
    meta_mensal = config_cliente.get("meta_mensal", 0)
    alerta_baixo = config_cliente.get("alerta_saldo_baixo", 500)

    faltante_meta = max(meta_mensal - gasto_mes, 0)

    hoje = date.today()
    if hoje.month < 12:
        dias_no_mes = (date(hoje.year, hoje.month + 1, 1) - date(hoje.year, hoje.month, 1)).days
    else:
        dias_no_mes = (date(hoje.year + 1, 1, 1) - date(hoje.year, 12, 1)).days

    dias_restantes = dias_no_mes - hoje.day + 1
    gasto_diario_ideal = faltante_meta / dias_restantes if dias_restantes > 0 else 0

    saldo_proximo_acabar = saldo < alerta_baixo
    bateu_meta = gasto_mes >= meta_mensal
    percentual_meta = (gasto_mes / meta_mensal * 100) if meta_mensal > 0 else 0

    return {
        "saldo": saldo,
        "gasto_mes": gasto_mes,
        "meta_mensal": meta_mensal,
        "faltante_meta": faltante_meta,
        "percentual_meta": percentual_meta,
        "saldo_proximo_acabar": saldo_proximo_acabar,
        "bateu_meta": bateu_meta,
        "dias_restantes": dias_restantes,
        "gasto_diario_ideal": gasto_diario_ideal,
    }

# ──────────────────────────────────────────
# FORMATA A MENSAGEM
# ──────────────────────────────────────────

def formatar_mensagem(nome_cliente: str, nome_conta: str, status: dict, moeda: str) -> str:
    s = status
    simbolo = "R$" if moeda == "BRL" else moeda

    alertas = []
    if s["saldo_proximo_acabar"]:
        alertas.append(f"⚠️ SALDO BAIXO! Menos de {simbolo} {s['saldo']:.2f} disponível.")
    if s["bateu_meta"]:
        alertas.append("✅ Meta mensal atingida!")
    elif s["percentual_meta"] >= 80:
        alertas.append(f"🔥 {s['percentual_meta']:.0f}% da meta atingida — últimos dias para fechar!")

    alerta_bloco = "\n".join(alertas) + "\n\n" if alertas else ""

    msg = (
        f"📊 Relatório diário — {nome_cliente}\n"
        f"_{nome_conta}_\n"
        f"_{datetime.now().strftime('%d/%m/%Y às %H:%M')}_\n\n"
        f"{alerta_bloco}"
        f"💰 Saldo disponível: {simbolo} {s['saldo']:,.2f}\n"
        f"📅 Gasto no mês: {simbolo} {s['gasto_mes']:,.2f}\n"
        f"🎯 Meta mensal: {simbolo} {s['meta_mensal']:,.2f}\n"
        f"📈 Progresso: {s['percentual_meta']:.1f}%\n\n"
        f"📌 Faltam para a meta: {simbolo} {s['faltante_meta']:,.2f}\n"
        f"📆 Dias restantes no mês: {s['dias_restantes']}\n"
        f"💡 Gasto diário ideal: {simbolo} {s['gasto_diario_ideal']:,.2f}\n\n"
        f"_Enviado automaticamente pelo Agente de Ads_ 🤖"
    )
    return msg

# ──────────────────────────────────────────
# ENVIO VIA Z-API (WhatsApp)
# ──────────────────────────────────────────

def enviar_whatsapp(group_id: str, mensagem: str) -> bool:
    """Envia mensagem no grupo usando Z-API."""
    url = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_CLIENT_TOKEN}/send-text"
    headers = {
        "Content-Type": "application/json",
        "client-token": ZAPI_CLIENT_TOKEN,
    }
    payload = {
        "phone": group_id,
        "message": mensagem,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        log.info(f"✅ Mensagem enviada para {group_id}")
        return True
    except Exception as e:
        log.error(f"❌ Erro ao enviar para {group_id}: {e}")
        return False

# ──────────────────────────────────────────
# JOB PRINCIPAL
# ──────────────────────────────────────────

def rodar_relatorios():
    log.info("🚀 Iniciando relatórios diários...")
    try:
        with open("clientes.json", "r", encoding="utf-8") as f:
            clientes = json.load(f)
    except Exception as e:
        log.error(f"Erro ao ler clientes.json: {e}")
        return

    for cliente in clientes:
        nome = cliente["nome"]
        log.info(f"Processando: {nome}")
        try:
            dados_meta = buscar_dados_meta(
                cliente["meta_account_id"],
                cliente["meta_access_token"],
            )
            status = calcular_status(dados_meta, cliente)
            mensagem = formatar_mensagem(
                nome,
                dados_meta["nome_conta"],
                status,
                dados_meta["moeda"],
            )
            enviar_whatsapp(cliente["whatsapp_group_id"], mensagem)
        except Exception as e:
            log.error(f"Erro no cliente {nome}: {e}")

    log.info("✅ Relatórios concluídos.")

# ──────────────────────────────────────────
# AGENDAMENTO
# ──────────────────────────────────────────

if __name__ == "__main__":
    log.info("Agente de Ads iniciado. Aguardando 09:00...")

    # Roda imediatamente se RODAR_AGORA=true (útil para testar)
    if os.getenv("RODAR_AGORA", "false").lower() == "true":
        rodar_relatorios()

    schedule.every().day.at("09:00").do(rodar_relatorios)

    while True:
        schedule.run_pending()
        time.sleep(30)
