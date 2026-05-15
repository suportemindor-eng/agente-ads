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
NUMEROS_SEGUNDA   = ["5511937426646", "5511959267496", "5511997935582"]


def buscar_gasto_periodo(account_id, access_token, since, until):
    base = "https://graph.facebook.com/v19.0"
    resp = requests.get(f"{base}/{account_id}/insights", params={
        "fields": "spend",
        "time_range": json.dumps({"since": since, "until": until}),
        "access_token": access_token,
    }, timeout=15)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    return float(data[0].get("spend", 0)) if data else 0.0


def buscar_dados_meta(account_id, access_token):
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
    segunda_atual = hoje - timedelta(days=hoje.weekday())
    gasto_semana_atual = gasto(segunda_atual.strftime("%Y-%m-%d"), hoje.strftime("%Y-%m-%d"))
    segunda_passada = segunda_atual - timedelta(days=7)
    domingo_passado = segunda_atual - timedelta(days=1)
    gasto_semana_passada = gasto(segunda_passada.strftime("%Y-%m-%d"), domingo_passado.strftime("%Y-%m-%d"))
    return {
        "nome_conta": conta.get("name", "Conta sem nome"),
        "moeda": conta.get("currency", "BRL"),
        "saldo_disponivel": float(conta.get("balance", 0)) / 100,
        "gasto_mes": gasto_mes,
        "gasto_ontem": gasto_ontem,
        "data_ontem": ontem.strftime("%d/%m/%Y"),
        "gasto_semana_atual": gasto_semana_atual,
        "segunda_atual": segunda_atual.strftime("%d/%m"),
        "sexta_atual": (segunda_atual + timedelta(days=4)).strftime("%d/%m"),
        "gasto_semana_passada": gasto_semana_passada,
        "segunda_passada": segunda_passada.strftime("%d/%m"),
        "domingo_passado": domingo_passado.strftime("%d/%m"),
        "spend_cap": float(conta.get("spend_cap", 0)) / 100,
        "amount_spent": float(conta.get("amount_spent", 0)) / 100,
    }


def bloco_limite(dados, simbolo):
    spend_cap = dados["spend_cap"]
    amount_spent = dados["amount_spent"]
    if spend_cap <= 0:
        return ""
    falta = max(spend_cap - amount_spent, 0)
    pct = min(amount_spent / spend_cap * 100, 100)
    if falta == 0:
        status = "Limite atingido! Pagamento sera gerado."
    elif pct >= 80:
        status = str(round(pct)) + "% do limite atingido."
    else:
        status = str(round(pct)) + "% do limite utilizado."
    sc = "{:,.2f}".format(spend_cap)
    am = "{:,.2f}".format(amount_spent)
    fa = "{:,.2f}".format(falta)
    return "Limite: " + simbolo + " " + sc + "\nGasto ciclo: " + simbolo + " " + am + "\nFalta: " + simbolo + " " + fa + "\n" + status + "\n\n"


def formatar_relatorio(nome_cliente, dados, alerta_baixo):
    simbolo = "R$" if dados["moeda"] == "BRL" else dados["moeda"]
    saldo = dados["saldo_disponivel"]
    alerta = "SALDO BAIXO! " + simbolo + " " + "{:,.2f}".format(saldo) + "\n\n" if saldo < alerta_baixo else ""
    return (
        "Relatorio - " + nome_cliente + "\n"
        + dados["nome_conta"] + "\n"
        + datetime.now().strftime("%d/%m/%Y %H:%M") + "\n\n"
        + alerta
        + "Ontem: " + simbolo + " " + "{:,.2f}".format(dados["gasto_ontem"]) + "\n"
        + "Semana atual: " + simbolo + " " + "{:,.2f}".format(dados["gasto_semana_atual"]) + "\n"
        + "Semana passada: " + simbolo + " " + "{:,.2f}".format(dados["gasto_semana_passada"]) + "\n"
        + "Mes: " + simbolo + " " + "{:,.2f}".format(dados["gasto_mes"]) + "\n"
        + "Saldo: " + simbolo + " " + "{:,.2f}".format(dados["saldo_disponivel"]) + "\n\n"
        + bloco_limite(dados, simbolo)
    )


def formatar_alerta_urgente(nome_cliente, dados, alerta_baixo):
    s = "R$" if dados["moeda"] == "BRL" else dados["moeda"]
    return ("ALERTA SALDO CRITICO\nCliente: " + nome_cliente + "\nSaldo: " + s + " " + "{:,.2f}".format(dados["saldo_disponivel"]) + "\nLimite: " + s + " " + "{:,.2f}".format(alerta_baixo) + "\nRecarregue para evitar interrupcao.")


def formatar_resumo_semanal_sexta(clientes_dados):
    linhas = ["Resumo semanal " + datetime.now().strftime("%d/%m/%Y") + "\n"]
    semana = mes = disponivel = 0.0
    for item in clientes_dados:
        d = item["dados"]
        s = "R$" if d["moeda"] == "BRL" else d["moeda"]
        linhas.append("- " + item["nome"] + "\n  Semana: " + s + " " + "{:,.2f}".format(d["gasto_semana_atual"]) + "\n  Mes: " + s + " " + "{:,.2f}".format(d["gasto_mes"]) + "\n  Saldo: " + s + " " + "{:,.2f}".format(d["saldo_disponivel"]) + "\n")
        semana += d["gasto_semana_atual"]
        mes += d["gasto_mes"]
        disponivel += d["saldo_disponivel"]
    linhas.append("\nTOTAIS\nSemana: R$ " + "{:,.2f}".format(semana) + "\nMes: R$ " + "{:,.2f}".format(mes) + "\nDisponivel: R$ " + "{:,.2f}".format(disponivel))
    return "\n".join(linhas)


def formatar_resumo_segunda(clientes_dados):
    linhas = ["Resumo segunda " + datetime.now().strftime("%d/%m/%Y") + "\n"]
    geral = 0.0
    for item in clientes_dados:
        d = item["dados"]
        s = "R$" if d["moeda"] == "BRL" else d["moeda"]
        linhas.append("- " + item["nome"] + "\n  Semana passada: " + s + " " + "{:,.2f}".format(d["gasto_semana_passada"]) + "\n  Mes: " + s + " " + "{:,.2f}".format(d["gasto_mes"]) + "\n")
        geral += d["gasto_semana_passada"]
    linhas.append("\nTotal semana passada: R$ " + "{:,.2f}".format(geral))
    return "\n".join(linhas)


def enviar_whatsapp(numero_ou_grupo, mensagem):
    if not ZAPI_INSTANCE_ID or not ZAPI_CLIENT_TOKEN:
        log.error("ZAPI nao configurado.")
        return False
    url = "https://api.z-api.io/instances/" + ZAPI_INSTANCE_ID + "/token/" + ZAPI_CLIENT_TOKEN + "/send-text"
    payload = {"phone": numero_ou_grupo, "message": mensagem}
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        log.info("Enviado para " + str(numero_ou_grupo))
        return True
    except Exception as e:
        log.error("Falha: " + str(e))
        return False


def carregar_clientes():
    caminho = os.path.join(os.path.dirname(__file__), "clientes.json")
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def rodar_relatorios():
    log.info("Iniciando relatorios...")
    for cliente in carregar_clientes():
        nome = cliente["nome"]
        try:
            dados = buscar_dados_meta(cliente["meta_account_id"], cliente["meta_access_token"])
            msg = formatar_relatorio(nome, dados, cliente.get("alerta_saldo_baixo", 100))
            enviar_whatsapp(cliente["whatsapp_group_id"], msg)
            log.info("OK: " + nome)
        except Exception as e:
            log.error("Erro " + nome + ": " + str(e))
    log.info("Relatorios concluidos.")


alertas_enviados_hoje = set()
ultimo_reset_dia = date.today().day


def verificar_saldos_criticos():
    global alertas_enviados_hoje, ultimo_reset_dia
    hoje = date.today().day
    if hoje != ultimo_reset_dia:
        alertas_enviados_hoje.clear()
        ultimo_reset_dia = hoje
    for cliente in carregar_clientes():
        nome = cliente["nome"]
        if nome in alertas_enviados_hoje:
            continue
        try:
            dados = buscar_dados_meta(cliente["meta_account_id"], cliente["meta_access_token"])
            limite = cliente.get("alerta_saldo_baixo", 100)
            if dados["saldo_disponivel"] < limite:
                msg = formatar_alerta_urgente(nome, dados, limite)
                enviar_whatsapp(cliente["whatsapp_group_id"], msg)
                alertas_enviados_hoje.add(nome)
        except Exception as e:
            log.error("Erro saldo " + nome + ": " + str(e))


def rodar_resumo_semanal_sexta():
    if date.today().weekday() != 4:
        return
    log.info("Resumo sexta...")
    dados_list = []
    for cliente in carregar_clientes():
        try:
            d = buscar_dados_meta(cliente["meta_account_id"], cliente["meta_access_token"])
            dados_list.append({"nome": cliente["nome"], "dados": d})
        except Exception as e:
            log.error("Erro " + cliente["nome"] + ": " + str(e))
    if dados_list:
        msg = formatar_resumo_semanal_sexta(dados_list)
        for n in NUMEROS_SEGUNDA:
            enviar_whatsapp(n, msg)
    log.info("Resumo sexta concluido.")


def rodar_resumo_segunda():
    if date.today().weekday() != 0:
        return
    log.info("Resumo segunda...")
    dados_list = []
    for cliente in carregar_clientes():
        try:
            d = buscar_dados_meta(cliente["meta_account_id"], cliente["meta_access_token"])
            dados_list.append({"nome": cliente["nome"], "dados": d})
        except Exception as e:
            log.error("Erro " + cliente["nome"] + ": " + str(e))
    if dados_list:
        msg = formatar_resumo_segunda(dados_list)
        for n in NUMEROS_SEGUNDA:
            enviar_whatsapp(n, msg)
    log.info("Resumo segunda concluido.")


if __name__ == "__main__":
    log.info("Alfred iniciado.")
    if os.getenv("RODAR_AGORA", "false").lower() == "true":
        rodar_relatorios()
    schedule.every().day.at("09:00").do(rodar_relatorios)
    schedule.every().day.at("09:05").do(rodar_resumo_semanal_sexta)
    schedule.every().monday.at("08:30").do(rodar_resumo_segunda)
    schedule.every(2).hours.do(verificar_saldos_criticos)
    log.info("Agendado.")
    while True:
        schedule.run_pending()
        time.sleep(30)
