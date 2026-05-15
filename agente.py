import os

import json

import requests

from datetime import datetime, date, timedelta

import schedule

import time

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

log = logging.getLogger(__name__)

ZAPI_INSTANCE_ID  = os.getenv("ZAPI_INSTANCE_ID")

ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN")

GRUPO_MINDOR      = "120363424525025463@g.us"  # Mindor - Equipe Tráfego

# ── BUSCA DE DADOS ──────────────────────────────────────────────────────────

def buscar_gasto_periodo(account_id: str, access_token: str, since: str, until: str) -> float:

    base = "https://graph.facebook.com/v19.0"

    resp = requests.get(f"{base}/{account_id}/insights", params={

        "fields": "spend",

        "time_range": json.dumps({"since": since, "until": until}),

        "access_token": access_token,

    }, timeout=15)

    resp.raise_for_status()

    data = resp.json().get("data", [])

    return float(data[0].get("spend", 0)) if data else 0.0

def buscar_dados_meta(account_id: str, access_token: str) -> dict:

    base  = "https://graph.facebook.com/v19.0"

    hoje  = date.today()

    ontem = hoje - timedelta(days=1)

    resp_conta = requests.get(f"{base}/{account_id}", params={

        "fields": "balance,currency,name,spend_cap,amount_spent",

        "access_token": access_token,

    }, timeout=15)

    resp_conta.raise_for_status()

    conta = resp_conta.json()

    def gasto(since, until):

        return buscar_gasto_periodo(account_id, access_token, since, until)

    gasto_mes   = gasto(hoje.replace(day=1).strftime("%Y-%m-%d"), hoje.strftime("%Y-%m-%d"))

    gasto_ontem = gasto(ontem.strftime("%Y-%m-%d"), ontem.strftime("%Y-%m-%d"))

    # Semana atual: segunda até hoje

    segunda_atual = hoje - timedelta(days=hoje.weekday())

    gasto_semana_atual = gasto(segunda_atual.strftime("%Y-%m-%d"), hoje.strftime("%Y-%m-%d"))

    # Semana passada: segunda a domingo

    segunda_passada = segunda_atual - timedelta(days=7)

    domingo_passado = segunda_atual - timedelta(days=1)

    gasto_semana_passada = gasto(segunda_passada.strftime("%Y-%m-%d"), domingo_passado.strftime("%Y-%m-%d"))

    return {

        "nome_conta"         : conta.get("name", "Conta sem nome"),

        "moeda"              : conta.get("currency", "BRL"),

        "saldo_disponivel"   : float(conta.get("balance", 0)) / 100,

        "gasto_mes"          : gasto_mes,

        "gasto_ontem"        : gasto_ontem,

        "data_ontem"         : ontem.strftime("%d/%m/%Y"),

        "gasto_semana_atual" : gasto_semana_atual,

        "segunda_atual"      : segunda_atual.strftime("%d/%m"),

        "sexta_atual"        : (segunda_atual + timedelta(days=4)).strftime("%d/%m"),

        "gasto_semana_passada": gasto_semana_passada,

        "segunda_passada"    : segunda_passada.strftime("%d/%m"),

        "domingo_passado"    : domingo_passado.strftime("%d/%m"),

        "spend_cap"          : float(conta.get("spend_cap", 0)) / 100,

        "amount_spent"       : float(conta.get("amount_spent", 0)) / 100,

    }

# ── BLOCOS REUTILIZÁVEIS ────────────────────────────────────────────────────

def bloco_limite(dados: dict, simbolo: str) -> str:

    spend_cap    = dados["spend_cap"]

    amount_spent = dados["amount_spent"]

    if spend_cap <= 0:

        return ""

    falta = max(spend_cap - amount_spent, 0)

    pct   = min(amount_spent / spend_cap * 100, 100)

    if falta == 0:

        status = "🔴 Limite atingido! Pagamento será gerado em breve."

    elif pct >= 80:

        status = f"🟠 {pct:.0f}% do limite atingido — pagamento se aproxima."

    else:

        status = f"🟢 {pct:.0f}% do limite utilizado"

    return (

        f"💳 Limite de pagamento: {simbolo} {spend_cap:,.2f}\n"

        f"📤 Gasto no ciclo: {simbolo} {amount_spent:,.2f}\n"

        f"📌 Falta para bater o limite: {simbolo} {falta:,.2f}\n"

        f"{status}\n\n"

    )

# ── FORMATADORES ────────────────────────────────────────────────────────────

def formatar_relatorio(nome_cliente: str, dados: dict, alerta_baixo: float) -> str:

    simbolo = "R$" if dados["moeda"] == "BRL" else dados["moeda"]

    saldo   = dados["saldo_disponivel"]

    alerta_saldo = (

        f"⚠️ SALDO BAIXO! Apenas {simbolo} {saldo:,.2f} disponível.\n\n"

        if saldo < alerta_baixo else ""

    )

    return (

        f"📊 Relatório diário — {nome_cliente}\n"

        f"_{dados['nome_conta']}_\n"

        f"_{datetime.now().strftime('%d/%m/%Y às %H:%M')}_\n\n"

        f"{alerta_saldo}"

        f"📆 Gasto ontem ({dados['data_ontem']}): {simbolo} {dados['gasto_ontem']:,.2f}\n"

        f"📅 Gasto no mês: {simbolo} {dados['gasto_mes']:,.2f}\n"

        f"💰 Saldo disponível: {simbolo} {saldo:,.2f}\n\n"

        f"{bloco_limite(dados, simbolo)}"

        f"_Enviado automaticamente pelo Alfred_ 🤖"

    )

def formatar_resumo_semanal_sexta(nome_cliente: str, dados: dict) -> str:

    """Enviado no grupo do cliente toda sexta — gasto de seg a sex."""

    simbolo = "R$" if dados["moeda"] == "BRL" else dados["moeda"]

    return (

        f"📋 Resumo da semana — {nome_cliente}\n"

        f"_{dados['nome_conta']}_\n"

        f"_{dados['segunda_atual']} a {dados['sexta_atual']}_\n\n"

        f"💸 Total gasto na semana: {simbolo} {dados['gasto_semana_atual']:,.2f}\n"

        f"📅 Gasto no mês: {simbolo} {dados['gasto_mes']:,.2f}\n"

        f"💰 Saldo disponível: {simbolo} {dados['saldo_disponivel']:,.2f}\n\n"

        f"{bloco_limite(dados, simbolo)}"

        f"_Resumo semanal — Alfred_ 🤖"

    )

def formatar_alerta_urgente(nome_cliente: str, dados: dict, alerta_baixo: float) -> str:

    simbolo = "R$" if dados["moeda"] == "BRL" else dados["moeda"]

    saldo   = dados["saldo_disponivel"]

    if saldo <= 0:

        corpo = (

            f"🔴 SALDO ZERADO!\n\n"

            f"Os anúncios podem ter parado agora.\n\n"

            f"💰 Saldo atual: {simbolo} 0,00\n"

        )

    else:

        corpo = (

            f"⚠️ SALDO CRÍTICO!\n\n"

            f"O saldo está abaixo do limite de alerta.\n\n"

            f"💰 Saldo atual: {simbolo} {saldo:,.2f}\n"

            f"⚠️ Limite de alerta: {simbolo} {alerta_baixo:,.2f}\n"

        )

    return (

        f"🚨 ALERTA — {nome_cliente}\n\n"

        f"{corpo}"

        f"\n*Recarregue o saldo para evitar que os anúncios parem.*\n\n"

        f"_{datetime.now().strftime('%d/%m/%Y às %H:%M')}_"

    )

def formatar_resumo_segunda(clientes_dados: list) -> str:

    """Mensagem consolidada enviada para o seu número toda segunda às 8:30."""

    hoje           = date.today()

    segunda_passada = hoje - timedelta(days=hoje.weekday() + 7)

    domingo_passado = hoje - timedelta(days=hoje.weekday() + 1)

    linhas = []

    total_geral = 0.0

    for item in clientes_dados:

        nome   = item["nome"]

        dados  = item["dados"]

        simbolo = "R$" if dados["moeda"] == "BRL" else dados["moeda"]

        gasto  = dados["gasto_semana_passada"]

        saldo  = dados["saldo_disponivel"]

        total_geral += gasto

        alerta = " ⚠️" if saldo <= 0 else (" 🔴" if saldo < item["alerta_baixo"] else "")

        linhas.append(f"• {nome}: {simbolo} {gasto:,.2f}{alerta}")

    corpo = "\n".join(linhas)

    return (

        f"📊 Resumo semanal — todos os clientes\n"

        f"_{segunda_passada.strftime('%d/%m')} a {domingo_passado.strftime('%d/%m/%Y')}_\n\n"

        f"{corpo}\n\n"

        f"💸 Total geral: R$ {total_geral:,.2f}\n\n"

        f"_⚠️ = saldo baixo  |  🔴 = saldo zerado_\n"

        f"_Gerado automaticamente pelo Alfred_ 🤖"

    )

# ── ENVIO ───────────────────────────────────────────────────────────────────

def enviar_whatsapp(number: str, mensagem: str) -> bool:

    try:

        resp = requests.post(

            f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_CLIENT_TOKEN}/send-text",

            headers={"Content-Type": "application/json", "client-token": ZAPI_CLIENT_TOKEN},

            json={"phone": number, "message": mensagem},

            timeout=15,

        )

        resp.raise_for_status()

        log.info(f"✅ Mensagem enviada para {number}")

        return True

    except Exception as e:

        log.error(f"❌ Erro ao enviar para {number}: {e}")

        return False

def carregar_clientes() -> list:

    with open("clientes.json", "r", encoding="utf-8") as f:

        return json.load(f)

# ── JOB 1: relatório diário às 9h ──────────────────────────────────────────

def rodar_relatorios():

    log.info("🚀 Iniciando relatórios diários...")

    try:

        clientes = carregar_clientes()

    except Exception as e:

        log.error(f"Erro ao ler clientes.json: {e}"); return

    for cliente in clientes:

        nome = cliente["nome"]

        log.info(f"Relatório: {nome}")

        try:

            dados = buscar_dados_meta(cliente["meta_account_id"], cliente["meta_access_token"])

            enviar_whatsapp(cliente["whatsapp_group_id"],

                            formatar_relatorio(nome, dados, cliente.get("alerta_saldo_baixo", 500)))

        except Exception as e:

            log.error(f"Erro em {nome}: {e}")

    log.info("✅ Relatórios concluídos.")

# ── JOB 2: alerta de saldo a cada 2h ───────────────────────────────────────

alertasenviados_hoje: set = set()

ultimoreset_dia: int = -1

def verificar_saldos_criticos():

    global alertasenviados_hoje, ultimoreset_dia

    hoje_dia = date.today().day

    if hoje_dia != ultimoreset_dia:

        alertasenviados_hoje = set()

        ultimoreset_dia = hoje_dia

    log.info("🔍 Verificando saldos críticos...")

    try:

        clientes = carregar_clientes()

    except Exception as e:

        log.error(f"Erro ao ler clientes.json: {e}"); return

    for cliente in clientes:

        nome         = cliente["nome"]

        alerta_baixo = cliente.get("alerta_saldo_baixo", 500)

        if nome in alertasenviados_hoje:

            continue

        try:

            dados = buscar_dados_meta(cliente["meta_account_id"], cliente["meta_access_token"])

            saldo = dados["saldo_disponivel"]

            # Dispara alerta se saldo zerou OU está abaixo do limite

            if saldo <= 0 or saldo < alerta_baixo:

                log.warning(f"🚨 Saldo crítico: {nome} — R$ {saldo:.2f}")

                mensagem = formatar_alerta_urgente(nome, dados, alerta_baixo)

                if enviar_whatsapp(cliente["whatsapp_group_id"], mensagem):

                    alertasenviados_hoje.add(nome)

        except Exception as e:

            log.error(f"Erro ao verificar {nome}: {e}")

    log.info("✅ Verificação concluída.")

# ── JOB 3: resumo semanal no grupo do cliente — toda sexta às 9h ───────────

def rodar_resumo_semanal_sexta():

    if date.today().weekday() != 4:  # 4 = sexta

        return

    log.info("📋 Iniciando resumos semanais (sexta)...")

    try:

        clientes = carregar_clientes()

    except Exception as e:

        log.error(f"Erro ao ler clientes.json: {e}"); return

    for cliente in clientes:

        nome = cliente["nome"]

        log.info(f"Resumo semanal: {nome}")

        try:

            dados = buscar_dados_meta(cliente["meta_account_id"], cliente["meta_access_token"])

            enviar_whatsapp(cliente["whatsapp_group_id"],

                            formatar_resumo_semanal_sexta(nome, dados))

        except Exception as e:

            log.error(f"Erro em {nome}: {e}")

    log.info("✅ Resumos semanais concluídos.")

# ── JOB 4: resumo consolidado para você — toda segunda às 8:30 ─────────────

def rodar_resumo_segunda():

    if date.today().weekday() != 0:  # 0 = segunda

        return

    log.info("📊 Gerando resumo consolidado da semana passada...")

    try:

        clientes = carregar_clientes()

    except Exception as e:

        log.error(f"Erro ao ler clientes.json: {e}"); return

    clientes_dados = []

    for cliente in clientes:

        nome = cliente["nome"]

        log.info(f"Buscando dados: {nome}")

        try:

            dados = buscar_dados_meta(cliente["meta_account_id"], cliente["meta_access_token"])

            clientes_dados.append({

                "nome"        : nome,

                "dados"       : dados,

                "alerta_baixo": cliente.get("alerta_saldo_baixo", 500),

            })

        except Exception as e:

            log.error(f"Erro em {nome}: {e}")

    if clientes_dados:

        mensagem = formatar_resumo_segunda(clientes_dados)

        enviar_whatsapp(GRUPO_MINDOR, mensagem)

    log.info("✅ Resumo de segunda concluído.")

# ── AGENDAMENTO ─────────────────────────────────────────────────────────────

if __name__ == "__main__":

    log.info("Alfred iniciado.")

    if os.getenv("RODAR_AGORA", "false").lower() == "true":

        rodar_relatorios()

    schedule.every().day.at("09:00").do(rodar_relatorios)

    schedule.every().day.at("09:05").do(rodar_resumo_semanal_sexta)

    schedule.every().monday.at("08:30").do(rodar_resumo_segunda)

    schedule.every(2).hours.do(verificar_saldos_criticos)

    log.info("⏰ Jobs: relatório 09h | resumo sexta 09h | resumo segunda 08:30 | verificação saldo 2h")

    while True:

        schedule.run_pending()

        time.sleep(30)
