from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
import asyncio
from datetime import datetime
import yfinance as yf

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Discord webhooks
DISCORD_ACOES  = os.environ.get("DISCORD_WEBHOOK_ACOES")
DISCORD_CRIPTO = os.environ.get("DISCORD_WEBHOOK_CRIPTO")
DISCORD_DIARIO = os.environ.get("DISCORD_WEBHOOK_DIARIO")

# ── Alpaca
ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY")
ALPACA_BASE_URL   = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

# ── Binance
BINANCE_API_KEY    = os.environ.get("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.environ.get("BINANCE_SECRET_KEY")

# ── Store em memória: { "BTCUSDT": { payload completo }, "AAPL": { ... } }
ticker_store: dict = {}

# ── Helpers
def canal_por_broker(broker: str) -> str:
    return DISCORD_CRIPTO if broker == "binance" else DISCORD_ACOES

def montar_embed_setup(data: dict) -> dict:
    ticker    = data.get("ticker", "???")
    score     = data.get("score", 0)
    status    = data.get("status", "???")
    preco     = data.get("preco", "???")
    exchange  = data.get("exchange", "")
    asset     = data.get("asset_type", "")
    broker    = data.get("broker", "")
    hora      = datetime.now().strftime("%d/%m/%Y às %H:%M")

    c = {k: ("✅" if v else "❌") for k, v in {
        "c1": data.get("c1", False), "c2": data.get("c2", False),
        "c3": data.get("c3", False), "c4": data.get("c4", False),
        "c5": data.get("c5", False), "c6": data.get("c6", False),
        "c7": data.get("c7", False), "c8": data.get("c8", False),
    }.items()}

    criterios_txt = (
        f"{c['c1']} EMAs 50/100 1D  {c['c2']} EMA200 bull\n"
        f"{c['c3']} RSI > 50 1D     {c['c4']} EMA50 4H\n"
        f"{c['c5']} MACD hist 4H    {c['c6']} Vol > média 4H\n"
        f"{c['c7']} EMA50 1H        {c['c8']} RSI > 50 1H"
    )

    cor   = 0x2ECC71 if score >= 7 else 0xF39C12 if score >= 4 else 0xE74C3C
    emoji = "🟢" if score >= 7 else "🟡" if score >= 4 else "🔴"
    rsi_1d = data.get("rsi_1d", "—")
    rsi_4h = data.get("rsi_4h", "—")
    rsi_1h = data.get("rsi_1h", "—")

    return {
        "embeds": [{
            "title": f"{emoji}  SETUP {score}/8 — {ticker}",
            "color": cor,
            "fields": [
                {"name": "💰 Preço",    "value": f"`{preco}`",                               "inline": True},
                {"name": "🏦 Exchange", "value": f"`{exchange}`",                            "inline": True},
                {"name": "🔑 Broker",   "value": f"`{broker.upper()}`",                     "inline": True},
                {"name": "📊 RSI",      "value": f"`1D:{rsi_1d}  4H:{rsi_4h}  1H:{rsi_1h}`","inline": False},
                {"name": "🎯 Critérios","value": f"```\n{criterios_txt}\n```",               "inline": False},
            ],
            "footer": {"text": f"🕐 {hora}  |  Juanzito Trader · {asset.upper()}"}
        }]
    }

# ── Endpoints

@app.get("/")
async def health():
    return {"status": "online", "servico": "Juanzito Trader — Multi-Broker v1.2"}

@app.get("/myip")
async def myip():
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://api.ipify.org")
        return {"outbound_ip": resp.text}

@app.get("/data")
async def get_data():
    return {"tickers": ticker_store, "total": len(ticker_store)}

@app.get("/data/{ticker}")
async def get_data_ticker(ticker: str):
    t = ticker.upper()
    if t not in ticker_store:
        return {"erro": f"Ticker {t} não encontrado"}
    return ticker_store[t]

def is_br_ticker(sym: str) -> bool:
    if sym.endswith("11"):
        return True
    if len(sym) <= 6 and sym[-1] in ("3","4","5","6","8"):
        return True
    return False

async def fetch_br_bars(sym: str) -> dict:
    ticker_yf = sym + ".SA"
    try:
        t = yf.Ticker(ticker_yf)
        df_1d = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: t.history(period="2y", interval="1d", auto_adjust=True)
        )
        df_1h = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: t.history(period="60d", interval="1h", auto_adjust=True)
        )

        if df_1d.empty:
            return {"erro": f"{sym} não encontrado na B3"}

        price     = float(df_1d["Close"].iloc[-1])
        prev      = float(df_1d["Close"].iloc[-2]) if len(df_1d) > 1 else price
        chg24     = round((price - prev) / prev * 100, 4) if prev else 0
        vol_brl   = float(df_1d["Volume"].iloc[-1]) * price

        def df_to_bars(df):
            bars = []
            df = df.dropna()
            for idx, row in df.iterrows():
                bars.append({
                    "t": idx.isoformat(),
                    "o": float(row["Open"]),
                    "h": float(row["High"]),
                    "l": float(row["Low"]),
                    "c": float(row["Close"]),
                    "v": float(row["Volume"]),
                })
            return bars

        bars_1d = df_to_bars(df_1d)
        bars_1h = df_to_bars(df_1h)

        bars_4h = []
        if not df_1h.empty:
            df_4h = df_1h.resample("4h").agg({
                "Open":  "first",
                "High":  "max",
                "Low":   "min",
                "Close": "last",
                "Volume":"sum"
            }).dropna()
            bars_4h = df_to_bars(df_4h)

        return {
            "source":    "yfinance_b3",
            "price":     str(round(price, 2)),
            "chg24":     str(chg24),
            "vol24_usd": str(round(vol_brl, 2)),
            "bars_1d":   bars_1d,
            "bars_4h":   bars_4h,
            "bars_1h":   bars_1h,
        }
    except Exception as e:
        return {"erro": f"Erro B3 ({sym}): {str(e)}"}

# ── /bars — fallback de candles para o painel (Binance=cripto, Alpaca=ações)
@app.get("/bars/{symbol}")
async def get_bars(symbol: str):
    sym = symbol.upper()
    is_crypto = sym.endswith("USDT") or sym.endswith("BTC") or sym.endswith("ETH")

    if is_br_ticker(sym):
        return await fetch_br_bars(sym)

    if is_crypto:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                tk, kl1d, kl4h, kl1h = await asyncio.gather(
                    client.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={sym}"),
                    client.get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=1d&limit=300"),
                    client.get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=4h&limit=200"),
                    client.get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=1h&limit=200"),
                )
                t = tk.json()
                if t.get("code"):
                    return {"erro": f"{sym} não encontrado na Binance"}
                return {
                    "source":    "binance",
                    "price":     t["lastPrice"],
                    "chg24":     t["priceChangePercent"],
                    "vol24_usd": t["quoteVolume"],
                    "klines_1d": kl1d.json(),
                    "klines_4h": kl4h.json(),
                    "klines_1h": kl1h.json(),
                }
        except Exception as e:
            return {"erro": str(e)}
    else:
        headers = {
            "APCA-API-KEY-ID":     ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                snap, b1d, b4h, b1h = await asyncio.gather(
                    client.get(f"https://data.alpaca.markets/v2/stocks/{sym}/snapshot", headers=headers),
                    client.get(f"https://data.alpaca.markets/v2/stocks/{sym}/bars?timeframe=1Day&limit=300&adjustment=raw&feed=iex", headers=headers),
                    client.get(f"https://data.alpaca.markets/v2/stocks/{sym}/bars?timeframe=4Hour&limit=200&adjustment=raw&feed=iex", headers=headers),
                    client.get(f"https://data.alpaca.markets/v2/stocks/{sym}/bars?timeframe=1Hour&limit=200&adjustment=raw&feed=iex", headers=headers),
                )
                s      = snap.json()
                price  = s.get("latestTrade", {}).get("p", 0)
                prev   = s.get("prevDailyBar", {}).get("c", price)
                chg24  = round((price - prev) / prev * 100, 4) if prev else 0
                vol_usd= s.get("dailyBar", {}).get("v", 0) * price
                return {
                    "source":    "alpaca",
                    "price":     str(price),
                    "chg24":     str(chg24),
                    "vol24_usd": str(vol_usd),
                    "bars_1d":   b1d.json().get("bars", []),
                    "bars_4h":   b4h.json().get("bars", []),
                    "bars_1h":   b1h.json().get("bars", []),
                }
        except Exception as e:
            return {"erro": str(e)}

@app.post("/webhook")
async def receber_alerta(request: Request):
    content_type = request.headers.get("content-type", "")

    # ── Texto simples: "Setup detectado em TICKER" / "Setup IDEAL em TICKER"
    if "application/json" not in content_type:
        body = (await request.body()).decode("utf-8").strip()
        import re
        m = re.search(r"Setup\s+(IDEAL|detectado)\s+em\s+(\w+)", body, re.IGNORECASE)
        if not m:
            return {"erro": "Formato de texto não reconhecido"}

        tipo   = m.group(1).upper()
        ticker = m.group(2).upper()
        hora   = datetime.now().strftime("%d/%m/%Y às %H:%M")

        if ticker in ticker_store:
            data      = ticker_store[ticker]
            broker    = data.get("broker", "")
            canal_url = canal_por_broker(broker)
            embed     = montar_embed_setup(data)
        else:
            canal_url = DISCORD_ACOES or DISCORD_CRIPTO
            embed = {
                "embeds": [{
                    "title": f"📡  SETUP {tipo} — {ticker}",
                    "color": 0x3498DB,
                    "description": f"Alerta recebido via texto.\nTicker `{ticker}` ainda não está no store.",
                    "footer": {"text": f"🕐 {hora}  |  Juanzito Trader"}
                }]
            }

        async with httpx.AsyncClient() as client:
            await client.post(canal_url, json=embed)
        return {"status": "texto_notificado", "ticker": ticker, "tipo": tipo, "discord": "enviado"}

    # ── JSON padrão
    try:
        data = await request.json()
    except:
        return {"erro": "Payload inválido"}

    ticker     = data.get("ticker", "???").upper()
    novo_setup = data.get("novo_setup", False)
    broker     = data.get("broker", "")
    score      = data.get("score", 0)
    status     = data.get("status", "SEM_SETUP")

    data["ticker"]    = ticker
    data["updatedAt"] = datetime.now().isoformat()
    ticker_store[ticker] = data

    if novo_setup:
        canal_url = canal_por_broker(broker)
        embed     = montar_embed_setup(data)
        async with httpx.AsyncClient() as client:
            await client.post(canal_url, json=embed)
        return {"status": "setup_notificado", "ticker": ticker, "score": score, "broker": broker, "discord": "enviado"}

    return {"status": "store_atualizado", "ticker": ticker, "score": score, "status_sinal": status}

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

    risco     = abs(entrada - stop)
    ganho     = abs(alvo - entrada)
    rr        = round(ganho / risco, 2) if risco > 0 else 0
    eh_compra = direcao == "BUY"
    cor       = 0x2ECC71 if eh_compra else 0xE74C3C
    emoji     = "🟢" if eh_compra else "🔴"
    rr_emoji  = "✅" if rr >= 2 else "⚠️" if rr >= 1 else "❌"

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
        await client.post(DISCORD_DIARIO, json=embed)
    return {"status": "registrado", "ticker": ticker, "rr": rr}

async def fetch_focus_bcb() -> list:
    ano = str(datetime.now().year)
    base = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata"

    async def _call_olinda(path, params, label):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(f"{base}/{path}", params=params)
                items = r.json().get("value", [])
                if items and items[0].get("Mediana") is not None:
                    return {"label": label, "value": f"{items[0]['Mediana']}%"}
        except Exception as e:
            print(f"[FOCUS_BCB] ERRO: {type(e).__name__}: {e}")
        return None

    async def _fetch_brasilapi_ipca():
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get("https://brasilapi.com.br/api/ipca/v1")
                items = r.json()
                if items:
                    valor = items[-1].get("valor")
                    if valor is not None:
                        anualizado = ((1 + valor / 100) ** 12 - 1) * 100
                        return {"label": "IPCA 12m esperado", "value": f"{anualizado:.2f}%"}
        except Exception as e:
            print(f"[FOCUS_BCB][BRASILAPI_IPCA] ERRO: {type(e).__name__}: {e}")
        return None

    async def _fetch_brasilapi_selic():
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get("https://brasilapi.com.br/api/taxa/v1")
                items = r.json()
                for item in items:
                    if item.get("tipo", "").lower() == "selic":
                        return {"label": "Selic esperada", "value": f"{item['valor']}%"}
        except Exception as e:
            print(f"[FOCUS_BCB][BRASILAPI_SELIC] ERRO: {type(e).__name__}: {e}")
        return None

    async def _fetch_sgs_ipca():
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    "https://api.bcb.gov.br/dados/serie/bcdata.sgs.13522/dados/ultimos/1",
                    params={"formato": "json"},
                )
                items = r.json()
                if items:
                    return {"label": "IPCA 12m esperado", "value": f"{items[0]['valor']}%"}
        except Exception as e:
            print(f"[FOCUS_BCB][SGS] ERRO: {type(e).__name__}: {e}")
        return None

    try:
        ipca, selic, pib = await asyncio.gather(
            _call_olinda(
                "ExpectativasMercadoSuavizadas12Meses",
                {"$filter": "Indicador eq 'IPCA' and Suavizado eq 'S'",
                 "$orderby": "Data desc", "$top": "1", "$format": "json",
                 "$select": "Indicador,Data,Mediana"},
                "IPCA 12m esperado",
            ),
            _call_olinda(
                "ExpectativasMercadoAnuais",
                {"$filter": f"Indicador eq 'Selic' and Ano eq '{ano}' and baseCalculo eq '0'",
                 "$orderby": "Data desc", "$top": "1", "$format": "json",
                 "$select": "Indicador,Ano,Data,Mediana"},
                "Selic esperada",
            ),
            _call_olinda(
                "ExpectativasMercadoAnuais",
                {"$filter": f"Indicador eq 'PIB Total' and Ano eq '{ano}'",
                 "$orderby": "Data desc", "$top": "1", "$format": "json",
                 "$select": "Indicador,Ano,Data,Mediana"},
                "PIB esperado",
            ),
        )
    except Exception as e:
        print(f"[FOCUS_BCB] gather ERRO: {type(e).__name__}: {e}")
        ipca, selic, pib = None, None, None

    if ipca is None:
        ipca = await _fetch_brasilapi_ipca()
    if selic is None:
        selic = await _fetch_brasilapi_selic()
    if ipca is None:
        ipca = await _fetch_sgs_ipca()

    return [
        ipca or {"label": "IPCA 12m esperado", "value": None},
        selic or {"label": "Selic esperada", "value": None},
        pib or {"label": "PIB esperado", "value": None},
    ]


async def fetch_anbima_ntnb():
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://api.anbima.com.br/feed/precos-indices/v1/titulos-publicos/mercado-secundario-tpf",
                params={"codigoTitulo": "NTN-B"},
            )
            if r.status_code == 200:
                data = r.json()
                items = data if isinstance(data, list) else data.get("items", [])
                for item in items:
                    vencimento = str(item.get("dataVencimento", ""))
                    if "2029" in vencimento:
                        taxa = item.get("taxaCompra") or item.get("taxaVenda") or item.get("taxa")
                        if taxa is not None:
                            return {"label": "Inflação implícita NTN-B", "value": f"{round(float(taxa), 2)}%"}
    except Exception:
        pass
    return None


async def fetch_di_curve() -> list:
    tickers = [
        ("DI1F26.SA", "DI Jan/2026"),
        ("DI1F28.SA", "DI Jan/2028"),
        ("DI1F33.SA", "DI Jan/2033"),
    ]
    results = []
    for ticker_sym, label in tickers:
        try:
            df = await asyncio.get_event_loop().run_in_executor(
                None, lambda s=ticker_sym: yf.Ticker(s).history(period="5d", interval="1d", auto_adjust=True)
            )
            if not df.empty:
                val = float(df["Close"].iloc[-1])
                results.append({"label": label, "value": f"{round(val, 3)}%"})
        except Exception:
            pass
    return results


@app.get("/macro")
async def get_macro():
    async def fetch_yf(sym: str, period: str = "5d", interval: str = "1d") -> dict:
        try:
            t = yf.Ticker(sym)
            df = await asyncio.get_event_loop().run_in_executor(
                None, lambda: t.history(period=period, interval=interval, auto_adjust=True)
            )
            if df.empty:
                return {"value": None, "chg24": None}
            price = float(df["Close"].iloc[-1])
            prev  = float(df["Close"].iloc[-2]) if len(df) > 1 else price
            chg24 = round((price - prev) / prev * 100, 4) if prev else 0
            return {"value": round(price, 4), "chg24": chg24}
        except Exception as e:
            return {"value": None, "chg24": None, "error": str(e)}

    async def fetch_fear_greed() -> dict:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get("https://api.alternative.me/fng/?limit=1")
                d = r.json()["data"][0]
                return {"value": int(d["value"]), "classification": d["value_classification"]}
        except Exception as e:
            return {"value": None, "classification": None, "error": str(e)}

    async def fetch_btc_dom() -> dict:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get("https://api.coingecko.com/api/v3/global")
                pct = r.json()["data"]["market_cap_percentage"]["btc"]
                return {"value": round(pct, 2)}
        except Exception as e:
            return {"value": None, "error": str(e)}

    dxy, vix, us10y, us30y, move, gold, oil, sp500, usm2, fear_greed, btc_dom, focus_bcb, anbima_ntnb, di_curve = await asyncio.gather(
        fetch_yf("DX-Y.NYB"),
        fetch_yf("^VIX"),
        fetch_yf("^TNX"),
        fetch_yf("^TYX"),
        fetch_yf("^MOVE"),
        fetch_yf("GC=F"),
        fetch_yf("CL=F"),
        fetch_yf("^GSPC"),
        fetch_yf("M2SL", "1y", "1mo"),
        fetch_fear_greed(),
        fetch_btc_dom(),
        fetch_focus_bcb(),
        fetch_anbima_ntnb(),
        fetch_di_curve(),
    )
    try:
        brasil_block = {
            "focus":              focus_bcb,
            "di_curve":           di_curve,
            "inflacao_implicita": anbima_ntnb,
        }
    except Exception:
        brasil_block = None
    return {
        "dxy":        dxy,
        "vix":        vix,
        "us10y":      us10y,
        "us30y":      us30y,
        "move":       move,
        "gold":       gold,
        "oil":        oil,
        "sp500":      sp500,
        "usm2":       usm2,
        "fear_greed": fear_greed,
        "btc_dom":    btc_dom,
        "brasil":     brasil_block,
        "timestamp":  datetime.now().isoformat(),
    }


@app.post("/order")
async def order(request: Request):
    data   = await request.json()
    symbol = data.get("symbol", "").upper()
    side   = data.get("side", "").upper()
    qty    = data.get("qty", "")

    try:
        from binance.client import Client
        client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)
        result = client.create_order(symbol=symbol, side=side, type="MARKET", quantity=qty)
        fills      = result.get("fills", [])
        avg_price  = sum(float(f["price"]) * float(f["qty"]) for f in fills)
        total_qty  = sum(float(f["qty"]) for f in fills)
        exec_price = round(avg_price / total_qty, 4) if total_qty > 0 else 0
        emoji = "🟢" if side == "BUY" else "🔴"
        async with httpx.AsyncClient() as client_http:
            await client_http.post(DISCORD_CRIPTO, json={
                "content": f"{emoji} **ORDEM EXECUTADA** `{symbol}` | `{side}` | Qtd: `{qty}` | Preço: `{exec_price}`"
            })
        return {"status": "executado", "orderId": result["orderId"], "exec_price": exec_price}
    except Exception as e:
        return {"error": str(e)}

@app.post("/order-alpaca")
async def order_alpaca(request: Request):
    try:
        data = await request.json()
    except:
        return {"erro": "Payload inválido"}

    symbol = data.get("symbol", "").upper()
    side   = data.get("side", "buy").lower()
    qty    = str(data.get("qty", "1"))
    otype  = data.get("type", "market").lower()
    stop   = data.get("stop", None)
    tp     = data.get("tp", None)

    if not symbol:
        return {"erro": "symbol obrigatório"}

    headers = {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
        "Content-Type":        "application/json",
    }
    payload = {"symbol": symbol, "qty": qty, "side": side, "type": otype, "time_in_force": "day"}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{ALPACA_BASE_URL}/v2/orders", headers=headers, json=payload, timeout=10.0)

        result = resp.json()
        if resp.status_code not in (200, 201):
            return {"erro": result.get("message", "Erro Alpaca"), "status_code": resp.status_code}

        order_id   = result.get("id", "—")
        filled_avg = result.get("filled_avg_price", "—")
        status     = result.get("status", "—")
        hora       = datetime.now().strftime("%d/%m/%Y às %H:%M")
        emoji      = "🟢" if side == "buy" else "🔴"
        env_label  = "📄 PAPER" if "paper" in ALPACA_BASE_URL else "💵 LIVE"

        embed = {
            "embeds": [{
                "title": f"{emoji} ALPACA {side.upper()} — {symbol}",
                "color": 0x2ECC71 if side == "buy" else 0xE74C3C,
                "fields": [
                    {"name": "🏷️ Ambiente",   "value": f"`{env_label}`",   "inline": True},
                    {"name": "📦 Qtd",        "value": f"`{qty} ações`",   "inline": True},
                    {"name": "⚡ Status",     "value": f"`{status}`",      "inline": True},
                    {"name": "💰 Preço exec", "value": f"`{filled_avg}`",  "inline": True},
                    {"name": "🛑 Stop",       "value": f"`{stop or '—'}`", "inline": True},
                    {"name": "🎯 TP",         "value": f"`{tp or '—'}`",   "inline": True},
                    {"name": "🔑 Order ID",   "value": f"`{order_id}`",    "inline": False},
                ],
                "footer": {"text": f"🕐 {hora}  |  Alpaca Trading Bot"}
            }]
        }

        async with httpx.AsyncClient() as client_http:
            await client_http.post(DISCORD_ACOES, json=embed)

        return {"status": "executado", "order_id": order_id, "symbol": symbol, "side": side, "qty": qty, "broker": "alpaca"}

    except Exception as e:
        return {"erro": str(e)}
