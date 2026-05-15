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
NUMEROS_SEGUNDA   = ["5511937426646", "5511959267496", "5511997935582"]  # Sulivan, Leonardo, você


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
        base = "https://graph.facebook.com/v19.0"
        hoje = date.today()
        ontem = hoje - timedelta(days=1)

    resp_conta = requests.get(f"{base}/{account_id}", params={
                "fields": "balance,currency,name,spend_cap,amount_spent",
                "access_token": access_token,
    }, timeout=15)
    resp_conta.raise_for_status()
    conta = resp_conta.json()

    def gasto(since, until):
                return buscar_gasto_periodo(account_id, access_token, since, until)

    gasto_mes = gasto(hoje.replace(day=1).strftime("%Y-%m-%d"), hoje.strftime("%Y-%m-%d"))
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
        spend_cap = dados["spend_cap"]
        amount_spent = dados["amount_spent"]
        if spend_cap <= 0:
                    return ""
                falta = max(spend_cap - amount_spent, 0)
    pct = min(amount_spent / spend_cap * 100, 100)
    if falta == 0:
                status = "🔴 Limite atingido! Pagamento será gerado em breve."
elif pct >= 80:
        status = f"🟠 {pct:.0f}% do limite atingido — pagamento se aproxima."
else:
        status = f"🟢 {pct:.0f}% do limite utilizado"
    spend_cap_fmt = f"{spend_cap:,.2f}"
    amount_spent_fmt = f"{amount_spent:,.2f}"
    falta_fmt = f"{falta:,.2f}"
    return (
                f"💳 Limite de pagamento: {simbolo} {spend_cap_fmt}\n"
                f"📤 Gasto no ciclo: {simbolo} {amount_spent_fmt}\n"
                f"📌 Falta para bater o limite: {simbolo} {falta_fmt}\n"
                f"{status}\n\n"
    )

# ── FORMATADORES ────────────────────────────────────────────────────────────

def formatar_relatorio(nome_cliente: str, dados: dict, alerta_baixo: float) -> str:
        simbolo = "R$" if dados["moeda"] == "BRL" else dados["moeda"]
    saldo = dados["saldo_disponivel"]
    saldo_fmt = f"{saldo:,.2f}"
    alerta_saldo = (
                f"⚠️ SALDO BAIXO! Apenas {simbolo} {saldo_fmt} disponível.\n\n"
                if saldo < alerta_baixo else ""
    )
    gasto_ontem_fmt = f"{dados['gasto_ontem']:,.2f}"
    gasto_semana_atual_fmt = f"{dados['gasto_semana_atual']:,.2f}"
    gasto_semana_passada_fmt = f"{dados['gasto_semana_passada']:,.2f}"
    gasto_mes_fmt = f"{dados['gasto_mes']:,.2f}"
    saldo_disponivel_fmt = f"{dados['saldo_disponivel']:,.2f}"
    return (
                f"📊 Relatório diário — {nome_cliente}\n"
                f"_{dados['nome_conta']}_\n"
                f"_{datetime.now().strftime('%d/%m/%Y às %H:%M')}_\n\n"
                f"{alerta_saldo}"
                f"📆 Gasto ontem ({dados['data_ontem']}): {simbolo} {gasto_ontem_fmt}\n"
                f"📅 Semana atual ({dados['segunda_atual']}–{dados['sexta_atual']}): {simbolo} {gasto_semana_atual_fmt}\n"
                f"📅 Semana passada ({dados['segunda_passada']}–{dados['domingo_passado']}): {simbolo} {gasto_semana_passada_fmt}\n"
                f"📈 Gasto no mês: {simbolo} {gasto_mes_fmt}\n"
                f"💰 Saldo disponível: {simbolo} {saldo_disponivel_fmt}\n\n"
                f"{bloco_limite(dados, simbolo)}"
    )


def formatar_resumo_semanal_sexta(clientes_dados: list) -> str:
        hoje = datetime.now().strftime("%d/%m/%Y")
    linhas = [f"📋 *Resumo semanal — {hoje}*\n"]
    semana = 0.0
    mes = 0.0
    disponivel = 0.0
    for item in clientes_dados:
                nome = item["nome"]
                d = item["dados"]
                simbolo = "R$" if d["moeda"] == "BRL" else d["moeda"]
                semana_fmt = f"{d['gasto_semana_atual']:,.2f}"
                mes_fmt = f"{d['gasto_mes']:,.2f}"
                saldo_fmt = f"{d['saldo_disponivel']:,.2f}"
                linhas.append(
                    f"• *{nome}*\n"
                    f"  Semana: {simbolo} {semana_fmt}\n"
                    f"  Mês: {simbolo} {mes_fmt}\n"
                    f"  Saldo: {simbolo} {saldo_fmt}\n"
                )
                semana += d["gasto_semana_atual"]
                mes += d["gasto_mes"]
                disponivel += d["saldo_disponivel"]
            semana_total_fmt = f"{semana:,.2f}"
    mes_total_fmt = f"{mes:,.2f}"
    disponivel_total_fmt = f"{disponivel:,.2f}"
    linhas.append(
                f"\n*TOTAIS*\n"
                f"Semana: R$ {semana_total_fmt}\n"
                f"Mês: R$ {mes_total_fmt}\n"
                f"Disponível: R$ {disponivel_total_fmt}"
    )
    return "\n".join(linhas)


def formatar_alerta_urgente(nome_cliente: str, dados: dict, alerta_baixo: float) -> str:
        simbolo = "R$" if dados["moeda"] == "BRL" else dados["moeda"]
    saldo = dados["saldo_disponivel"]
    saldo_fmt = f"{saldo:,.2f}"
    atual = f"💰 Saldo atual: {simbolo} {saldo_fmt}"
    corpo = (
                f"🚨 *ALERTA DE SALDO CRÍTICO*\n"
                f"Cliente: *{nome_cliente}*\n"
                f"{atual}\n"
                f"⚠️ Saldo abaixo do limite de alerta ({simbolo} {alerta_baixo:,.2f})!\n"
                f"Recarregue a conta para evitar interrupção dos anúncios."
    )
    return corpo


def formatar_resumo_segunda(clientes_dados: list) -> str:
        hoje = datetime.now().strftime("%d/%m/%Y")
    linhas = [f"📋 *Resumo semanal — {hoje}*\n"]
    geral = 0.0
    _ = 0.0
    for item in clientes_dados:
                nome = item["nome"]
                d = item["dados"]
                simbolo = "R$" if d["moeda"] == "BRL" else d["moeda"]
                semana_passada_fmt = f"{d['gasto_semana_passada']:,.2f}"
                mes_fmt = f"{d['gasto_mes']:,.2f}"
                linhas.append(
                    f"• *{nome}*\n"
                    f"  Semana passada: {simbolo} {semana_passada_fmt}\n"
                    f"  Mês: {simbolo} {mes_fmt}\n"
                )
                geral += d["gasto_semana_passada"]
            geral_fmt = f"{geral:,.2f}"
    linhas.append(f"\n*Total geral semana passada: R$ {geral_fmt}*")
    return "\n".join(linhas)


# ── ENVIO WHATSAPP ──────────────────────────────────────────────────────────

def enviar_whatsapp(numero_ou_grupo: str, mensagem: str) -> bool:
        if not ZAPI_INSTANCE_ID or not ZAPI_CLIENT_TOKEN:
                    log.error("ZAPI_INSTANCE_ID ou ZAPI_CLIENT_TOKEN não configurados.")
                    return False
                url = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_CLIENT_TOKEN}/send-text"
    payload = {"phone": numero_ou_grupo, "message": mensagem}
    try:
                resp = requests.post(url, json=payload, timeout=15)
                resp.raise_for_status()
                log.info(f"✅ Mensagem enviada para {numero_ou_grupo}")
                return True
except Exception as e:
        log.error(f"❌ Falha ao enviar para {numero_ou_grupo}: {e}")
        return False


# ── CLIENTES ────────────────────────────────────────────────────────────────

def carregar_clientes() -> list:
        caminho = os.path.join(os.path.dirname(__file__), "clientes.json")
    with open(caminho, encoding="utf-8") as f:
                return json.load(f)


# ── ROTINAS ─────────────────────────────────────────────────────────────────

def rodar_relatorios():
        log.info("🚀 Iniciando relatórios diários...")
    clientes = carregar_clientes()
    for cliente in clientes:
                nome = cliente["nome"]
                try:
                                dados = buscar_dados_meta(cliente["meta_account_id"], cliente["meta_access_token"])
                                mensagem = formatar_relatorio(nome, dados, cliente.get("alerta_saldo_baixo", 100))
                                enviar_whatsapp(cliente["whatsapp_group_id"], mensagem)
                                log.info(f"Processando: {nome}")
except Exception as e:
            log.error(f"Erro no cliente {nome}: {e}")
    log.info("✅ Relatórios concluídos.")


alertas_enviados_hoje: set = set()
ultimo_reset_dia: int = date.today().day


def verificar_saldos_criticos():
        global alertas_enviados_hoje, ultimo_reset_dia
    hoje = date.today().day
    if hoje != ultimo_reset_dia:
                alertas_enviados_hoje.clear()
                ultimo_reset_dia = hoje
            clientes = carregar_clientes()
    for cliente in clientes:
                nome = cliente["nome"]
                if nome in alertas_enviados_hoje:
                                continue
                            try:
                                            dados = buscar_dados_meta(cliente["meta_account_id"], cliente["meta_access_token"])
                                            limite = cliente.get("alerta_saldo_baixo", 100)
                                            if dados["saldo_disponivel"] < limite:
                                                                mensagem = formatar_alerta_urgente(nome, dados, limite)
                                                                enviar_whatsapp(cliente["whatsapp_group_id"], mensagem)
                                                                alertas_enviados_hoje.add(nome)
                            except Exception as e:
            log.error(f"Erro ao verificar saldo de {nome}: {e}")


def rodar_resumo_semanal_sexta():
        if date.today().weekday() != 4:
                    return
                log.info("📋 Iniciando resumo semanal de sexta...")
    clientes = carregar_clientes()
    clientes_dados = []
    for cliente in clientes:
                nome = cliente["nome"]
        try:
                        dados = buscar_dados_meta(cliente["meta_account_id"], cliente["meta_access_token"])
                        clientes_dados.append({"nome": nome, "dados": dados})
except Exception as e:
            log.error(f"Erro em {nome}: {e}")
    if clientes_dados:
                mensagem = formatar_resumo_semanal_sexta(clientes_dados)
        for numero in NUMEROS_SEGUNDA:
                        enviar_whatsapp(numero, mensagem)
                log.info("✅ Resumo de sexta concluído.")


def rodar_resumo_segunda():
        if date.today().weekday() != 0:
                    return
                log.info("📋 Iniciando resumo de segunda...")
    clientes = carregar_clientes()
    clientes_dados = []
    for cliente in clientes:
                nome = cliente["nome"]
        try:
                        dados = buscar_dados_meta(cliente["meta_account_id"], cliente["meta_access_token"])
                        clientes_dados.append({"nome": nome, "dados": dados})
except Exception as e:
            log.error(f"Erro em {nome}: {e}")
    if clientes_dados:
                mensagem = formatar_resumo_segunda(clientes_dados)
        for numero in NUMEROS_SEGUNDA:
                        enviar_whatsapp(numero, mensagem)
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
