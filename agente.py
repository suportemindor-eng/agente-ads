import os
import json
import requests
from datetime import datetime, date
import schedule
import time
import pytz

# Configurações
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "")
FUSO = pytz.timezone("America/Sao_Paulo")

def get_account_balance(account_id, access_token):
    url = f"https://graph.facebook.com/v19.0/{account_id}"
    params = {"fields": "balance,currency", "access_token": access_token}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return int(data.get("balance", 0)) / 100.0

def get_monthly_spend(account_id, access_token):
    hoje = date.today()
    primeiro_dia = hoje.replace(day=1).strftime("%Y-%m-%d")
    hoje_str = hoje.strftime("%Y-%m-%d")
    url = f"https://graph.facebook.com/v19.0/{account_id}/insights"
    params = {
        "level": "account",
        "fields": "spend",
        "time_range": json.dumps({"since": primeiro_dia, "until": hoje_str}),
        "access_token": access_token,
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    try:
        return float(data["data"][0]["spend"])
    except (KeyError, IndexError, ValueError):
        return 0.0

def get_account_name(account_id, access_token):
    url = f"https://graph.facebook.com/v19.0/{account_id}"
    params = {"fields": "name", "access_token": access_token}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("name", account_id)

def send_whatsapp_message(group_id, message):
    url = f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}"
    headers = {"Content-Type": "application/json", "apikey": EVOLUTION_API_KEY}
    payload = {"number": group_id, "text": message}
    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    resp.raise_for_status()

def dias_restantes_no_mes():
    hoje = date.today()
    if hoje.month == 12:
        proximo = date(hoje.year + 1, 1, 1)
    else:
        proximo = date(hoje.year, hoje.month + 1, 1)
    return (proximo - hoje).days

def formatar_brl(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def build_report(cliente):
    account_id = cliente["meta_account_id"]
    token = cliente["meta_access_token"]
    meta_mensal = float(cliente["meta_mensal"])
    alerta_limite = float(cliente["alerta_saldo_baixo"])

    nome_conta = get_account_name(account_id, token)
    saldo = get_account_balance(account_id, token)
    gasto_mes = get_monthly_spend(account_id, token)

    progresso = (gasto_mes / meta_mensal * 100) if meta_mensal > 0 else 0
    falta_meta = max(meta_mensal - gasto_mes, 0)
    dias_rest = dias_restantes_no_mes()
    gasto_diario_ideal = falta_meta / dias_rest if dias_rest > 0 else 0
    agora = datetime.now(FUSO).strftime("%d/%m/%Y às %H:%M")

    linhas = [
        f"Relatório diário — {cliente['nome']}",
        f"_{nome_conta}_",
        f"_{agora}_",
        "",
    ]
    if saldo < alerta_limite:
        linhas.append(f"SALDO BAIXO! Menos de {formatar_brl(saldo)} disponível.")
        linhas.append("")
    linhas += [
        f"Saldo disponível: {formatar_brl(saldo)}",
        f"Gasto no mês: {formatar_brl(gasto_mes)}",
        f"Meta mensal: {formatar_brl(meta_mensal)}",
        f"Progresso: {progresso:.1f}%",
        "",
        f"Faltam para a meta: {formatar_brl(falta_meta)}",
        f"Dias restantes no mês: {dias_rest}",
        f"Gasto diário ideal: {formatar_brl(gasto_diario_ideal)}",
        "",
        "_Enviado automaticamente pelo Agente de Ads_",
    ]
    return "\n".join(linhas)

def carregar_clientes(path="clientes.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def job():
    print(f"[{datetime.now(FUSO).strftime('%Y-%m-%d %H:%M:%S')}] Iniciando envio de relatórios...")
    clientes = carregar_clientes()
    for cliente in clientes:
        try:
            print(f"  Processando: {cliente['nome']}")
            relatorio = build_report(cliente)
            send_whatsapp_message(cliente["whatsapp_group_id"], relatorio)
            print(f"  OK: {cliente['nome']}")
        except Exception as e:
            print(f"  ERRO em {cliente['nome']}: {e}")
    print("Envios concluídos.")

if __name__ == "__main__":
    if os.getenv("RODAR_AGORA", "").lower() == "true":
        print("Modo RODAR_AGORA ativado.")
        job()
    else:
        schedule.every().day.at("09:00").do(job)
        print("Agente iniciado. Aguardando 09:00 (Brasília)...")
        while True:
            schedule.run_pending()
            time.sleep(30)
