from fastapi import FastAPI, Request
import httpx
import os
from datetime import datetime

app = FastAPI()

# ─── Webhook URLs do Discord (configuradas no Railway como variáveis) ───
DISCORD_ACOES  = os.environ.get("DISCORD_WEBHOOK_ACOES")
DISCORD_CRIPTO = os.environ.get("DISCORD_WEBHOOK_CRIPTO")

# Sufixos que identificam cripto
SUFIXOS_CRIPTO = ["BTC", "ETH", "USDT", "BNB", "SOL", "XRP", "DOGE", "ADA", "MATIC"]

def detectar_canal(ticker: str) -> str:
    ticker_upper = ticker.upper()
    for sufixo in SUFIXOS_CRIPTO:
        if sufixo in ticker_upper:
            return DISCORD_CRIPTO
    return DISCORD_ACOES  # padrão: ações B3


def montar_embed(ticker, acao, preco, rsi, volume, mensagem):
    """Monta o embed rico do Discord com cor e formatação."""
    eh_compra = acao.upper() == "BUY"
    cor       = 0x2ECC71 if eh_compra else 0xE74C3C   # verde ou vermelho
    emoji     = "🟢" if eh_compra else "🔴"
    hora      = datetime.now().strftime("%d/%m/%Y às %H:%M")

    return {
        "embeds": [{
            "title": f"{emoji}  {acao.upper()} — {ticker}",
            "color": cor,
            "fields": [
                {"name": "💰 Preço",   "value": f"`R$ {preco}`", "inline": True},
                {"name": "📈 RSI",     "value": f"`{rsi}`",      "inline": True},
                {"name": "📦 Volume",  "value": f"`{volume}`",   "inline": True},
                {"name": "📝 Sinal",   "value": mensagem,        "inline": False},
            ],
            "footer": {"text": f"🕐 {hora}  |  TradingView Alert Bot"}
        }]
    }


# ─── Rota principal: recebe alertas do TradingView ───
@app.post("/webhook")
async def receber_alerta(request: Request):
    try:
        data = await request.json()
    except Exception:
        return {"erro": "Payload inválido — esperado JSON"}

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

    return {
        "status": "enviado" if resp.status_code == 204 else "erro",
        "ticker": ticker,
        "canal":  "cripto" if canal_url == DISCORD_CRIPTO else "acoes",
        "discord_status": resp.status_code
    }


# ─── Health check (Railway usa para saber que o servidor está vivo) ───
@app.get("/")
async def health():
    return {"status": "online", "servico": "TradingView Alert Bot — Discord Edition"}
