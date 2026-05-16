from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DISCORD_ACOES  = os.environ.get("DISCORD_WEBHOOK_ACOES")
DISCORD_CRIPTO = os.environ.get("DISCORD_WEBHOOK_CRIPTO")
DISCORD_DIARIO = os.environ.get("DISCORD_WEBHOOK_DIARIO")

SUFIXOS_CRIPTO = ["BTC","ETH","USDT","BNB","SOL","XRP","DOGE","ADA","MATIC"]

def detectar_canal(ticker: str) -> str:
    for sufixo in SUFIXOS_CRIPTO:
        if sufixo in ticker.upper():
            return DISCORD_CRIPTO
    return DISCORD_ACOES

def montar_embed(ticker, acao, preco, rsi, volume, mensagem):
    eh_compra = acao.upper() == "BUY"
    cor   = 0x2ECC71 if eh_compra else 0xE74C3C
    emoji = "🟢" if eh_compra else "🔴"
    hora  = datetime.now().strftime("%d/%m/%Y às %H:%M")
    return {
        "embeds": [{
            "title": f"{emoji}  {acao.upper()} — {ticker}",
            "color": cor,
            "fields": [
                {"name": "💰 Preço",  "value": f"`R$ {preco}`", "inline": True},
                {"name": "📈 RSI",    "value": f"`{rsi}`",      "inline": True},
                {"name": "📦 Volume", "value": f"`{volume}`",   "inline": True},
                {"name": "📝 Sinal",  "value": mensagem,        "inline": False},
            ],
            "footer": {"text": f"🕐 {hora}  |  TradingView Alert Bot"}
        }]
    }

@app.post("/webhook")
async def receber_alerta(request: Request):
    try:
        data = await request.json()
    except:
        return {"erro": "Payload inválido"}
    ticker   = data.get("ticker",   "???")
    acao     = data.get("acao",     "???")
    preco    = data.get("preco",    "???")
    rsi      = data.get("rsi",      "???")
    volume   = data.get("volume",   "???")
    mensagem = data.get("mensagem", "")
    canal_url = detectar_canal(ticker)
    embed     = montar_embed(ticker, acao, preco, rsi, volume, mensagem)
    async with httpx.AsyncClient() as client:
        resp = await client.post(canal_url, json=embed)
    return {"status": "enviado" if resp.status_code == 204 else "erro", "ticker": ticker}

@app.post("/trade")
async def registrar_trade(request: Request):
    try:
        d = await request.json()
    except:
        return {"erro": "Payload inválido"}

    ticker  = d.get("ticker", "???").upper()
    direcao = d.get("direcao", "???").upper()
    entrada = float(d.get("entrada", 0))
    stop    = float(d.get("stop", 0))
    alvo    = float(d.get("alvo", 0))
    setup   = d.get("setup", "")
    hora    = datetime.now().strftime("%d/%m/%Y às %H:%M")

    risco    = abs(entrada - stop)
    ganho    = abs(alvo - entrada)
    rr       = round(ganho / risco, 2) if risco > 0 else 0
    eh_compra = direcao == "BUY"
    cor      = 0x2ECC71 if eh_compra else 0xE74C3C
    emoji    = "🟢" if eh_compra else "🔴"
    rr_emoji = "✅" if rr >= 2 else "⚠️" if rr >= 1 else "❌"

    embed = {
        "embeds": [{
            "title": f"📋  TRADE REGISTRADO — {ticker}",
            "color": cor,
            "fields": [
                {"name": "⚡ Direção",      "value": f"`{emoji} {direcao}`", "inline": True},
                {"name": "💰 Entrada",      "value": f"`{entrada}`",         "inline": True},
                {"name": "🛑 Stop",         "value": f"`{stop}`",            "inline": True},
                {"name": "🎯 Alvo",         "value": f"`{alvo}`",            "inline": True},
                {"name": f"{rr_emoji} R:R", "value": f"`1 : {rr}`",         "inline": True},
                {"name": "📝 Setup",        "value": setup or "—",           "inline": False},
            ],
            "footer": {"text": f"🕐 {hora}  |  Diário de Trades"}
        }]
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(DISCORD_DIARIO, json=embed)
    return {"status": "registrado", "ticker": ticker, "rr": rr}

@app.get("/")
async def health():
    return {"status": "online", "servico": "TradingView Alert Bot – Discord Edition"}

@app.get("/myip")
async def myip():
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://api.ipify.org")
        return {"outbound_ip": resp.text}
