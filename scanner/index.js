// ============================================================
//  JUANZITO SCANNER v1.0
//  Node.js · Express · TradingView Screener
//  Varre top 150 cryptos Binance de hora em hora
//  Calcula os 8 critérios · Notifica Discord · Expõe /results
// ============================================================

import express from 'express';
import cron    from 'node-cron';
import fetch   from 'node-fetch';

const app  = express();
app.use(express.json());

const PORT          = process.env.PORT           || 3000;
const DISCORD_URL   = process.env.DISCORD_WEBHOOK || '';
const SCORE_MIN     = parseInt(process.env.SCORE_MIN || '7');
const MAIN_RAILWAY  = process.env.MAIN_RAILWAY_URL || 'https://juanzito-trader-production.up.railway.app';

// ── Estado em memória
let scanResults = [];
let lastScan    = null;
let scanRunning = false;
let lastError   = null;
let totalVarred = 0;

// ── TradingView Screener
const TV_URL = 'https://scanner.tradingview.com/crypto/scan';

const COLUMNS = [
  'name',
  'close',
  'change',
  'EMA50', 'EMA100', 'EMA200', 'RSI',
  'close|240', 'EMA50|240', 'RSI|240',
  'MACD.macd|240', 'MACD.signal|240', 'volume|240',
  'close|60', 'EMA50|60', 'RSI|60',
];

// ── Fetch do Screener
async function fetchScreener() {
  const body = {
    filter: [
      { left: 'exchange', operation: 'in_range', right: ['BINANCE'] },
    ],
    options: { lang: 'en' },
    symbols: { query: { types: [] }, tickers: [] },
    columns: COLUMNS,
    sort: { sortBy: 'volume', sortOrder: 'desc' },
    range: [0, 150],
  };

  const res = await fetch(TV_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Origin':       'https://www.tradingview.com',
      'Referer':      'https://www.tradingview.com/',
      'User-Agent':   'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) throw new Error(`TV Screener HTTP ${res.status}`);
  const json = await res.json();
  if (!json.data || !Array.isArray(json.data)) throw new Error('Resposta inesperada do Screener');
  return json;
}

// ── Parse de uma linha do Screener
function parseRow(row) {
  const d = {};
  COLUMNS.forEach((col, i) => { d[col] = row.d[i]; });
  d.ticker = row.s;
  d.sym    = row.s.replace(/^[^:]+:/, ''); // remove prefixo BINANCE:
  return d;
}

// ── Helper: número válido ou null
function num(v) {
  return typeof v === 'number' && !isNaN(v) ? v : null;
}

// ── Calcula os 8 critérios e score
function calculateScore(d) {
  const close1d   = num(d['close']);
  const vol_1d    = num(d['volume']);
  const ema50_1d  = num(d['EMA50']);
  const ema100_1d = num(d['EMA100']);
  const ema200_1d = num(d['EMA200']);
  const rsi_1d    = num(d['RSI']);

  const close4h   = num(d['close|240']);
  const ema50_4h  = num(d['EMA50|240']);
  const rsi_4h    = num(d['RSI|240']);
  const macd_4h   = num(d['MACD.macd|240']);
  const sig_4h    = num(d['MACD.signal|240']);
  const vol_4h    = num(d['volume|240']);

  const close1h  = num(d['close|60']);
  const ema50_1h = num(d['EMA50|60']);
  const rsi_1h   = num(d['RSI|60']);

  // Os 8 critérios — mesma lógica do Pine Script v2.0
  const c1 = close1d !== null && ema50_1d !== null && ema100_1d !== null
              && close1d > ema50_1d && close1d > ema100_1d;

  const c2 = close1d !== null && ema200_1d !== null
              && close1d > ema200_1d;

  const c3 = rsi_1d !== null && rsi_1d > 50;

  const c4 = close4h !== null && ema50_4h !== null
              && close4h > ema50_4h;

  const macdHist = (macd_4h !== null && sig_4h !== null) ? macd_4h - sig_4h : null;
  const c5 = macdHist !== null && macdHist >= 0;

  // c6: volume 4H existe e é positivo (dado que vol_1d não está disponível)
  const c6 = vol_4h !== null && vol_4h > 0;

  const c7 = close1h !== null && ema50_1h !== null
              && close1h > ema50_1h;

  const c8 = rsi_1h !== null && rsi_1h > 50;

  const score = [c1,c2,c3,c4,c5,c6,c7,c8].filter(Boolean).length;
  const level = score <= 3 ? 'SEM_SETUP'
              : score <= 6 ? 'MONITORAR'
              : 'SETUP';

  return { score, level, c1, c2, c3, c4, c5, c6, c7, c8 };
}

// ── Notificação Discord
async function sendDiscord(setups) {
  if (!DISCORD_URL || setups.length === 0) return;

  const hora = new Date().toLocaleTimeString('pt-BR', {
    hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo',
  });

  const linhas = setups.map(c => {
    const stars  = c.score === 8 ? ' ★★' : c.score === 7 ? ' ★' : '';
    const preco  = c.close ? `$${parseFloat(c.close).toFixed(4)}` : '—';
    const chg    = c.change ? ` (${c.change >= 0 ? '+' : ''}${c.change.toFixed(2)}%)` : '';
    return `**${c.sym}**${stars} — Score **${c.score}/8** · ${preco}${chg}`;
  }).join('\n');

  const payload = {
    content: `⚡ **Juanzito Scanner** · ${hora} BRT\n\n${linhas}\n\n*Abrir TradingView · confirmar nível · padrão de candle · macro.*`,
  };

  try {
    await fetch(DISCORD_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    console.error('[Scanner] Erro Discord:', e.message);
  }
}

// Stablecoins e tokens sem sentido para trading direcional
const BLACKLIST = new Set([
  'USDCUSDT','USDTUSDT','BUSDUSDT','TUSDUSDT','USDPUSDT',
  'DAIUSDT','FRAXUSDT','USDDUSDT','USTUSDT','EURUSDT',
  'FDUSDUSDT','PYUSDUSDT',
]);

const MIN_PRICE = parseFloat(process.env.MIN_PRICE || '0.01'); // mín $0.01
async function runScan() {
  if (scanRunning) {
    console.log('[Scanner] Já rodando, pulando.');
    return;
  }
  scanRunning = true;
  lastError   = null;
  console.log(`[Scanner] Iniciando — ${new Date().toISOString()}`);

  try {
    const data = await fetchScreener();
    const rows = data.data
      .map(parseRow)
      .filter(d =>
        d.ticker.startsWith('BINANCE:') &&
        d.sym.endsWith('USDT') &&
        !BLACKLIST.has(d.sym)
      );
    totalVarred = rows.length;

    const scored = rows
      .map(d => ({ ...d, ...calculateScore(d) }))
      .filter(d => d.score >= 4)          // MONITORAR ou melhor
      .sort((a, b) => b.score - a.score);

    scanResults = scored;
    lastScan    = new Date().toISOString();

    const setups = scored.filter(d => d.score >= SCORE_MIN && (d.close || 0) >= MIN_PRICE);

    console.log(
      `[Scanner] ${totalVarred} varridos · ` +
      `${scored.length} candidatos (≥4) · ` +
      `${setups.length} setups (≥${SCORE_MIN})`
    );

    if (setups.length > 0) {
      await sendDiscord(setups);
      console.log(`[Scanner] Discord: ${setups.map(s => s.sym).join(', ')}`);
    } else {
      console.log('[Scanner] Nenhum setup — Discord não notificado.');
    }

  } catch (e) {
    lastError = e.message;
    console.error('[Scanner] Erro:', e.message);
  } finally {
    scanRunning = false;
  }
}

// ── Endpoints
app.get('/health', (_, res) => res.json({
  ok:         true,
  lastScan,
  running:    scanRunning,
  lastError,
  varridos:   totalVarred,
  candidatos: scanResults.length,
  setups:     scanResults.filter(d => d.score >= SCORE_MIN).length,
  score_min:  SCORE_MIN,
}));

app.get('/results', (_, res) => res.json({
  lastScan,
  running:    scanRunning,
  varridos:   totalVarred,
  candidatos: scanResults.length,
  setups:     scanResults.filter(d => d.score >= SCORE_MIN).length,
  score_min:  SCORE_MIN,
  results: scanResults.map(d => ({
    sym:    d.sym,
    score:  d.score,
    level:  d.level,
    price:  d.close,
    chg:    d.change,
    c1: d.c1, c2: d.c2, c3: d.c3, c4: d.c4,
    c5: d.c5, c6: d.c6, c7: d.c7, c8: d.c8,
  })),
}));

// Trigger manual de scan (ex: testar sem esperar o cron)
app.post('/scan', (_, res) => {
  if (!scanRunning) runScan();
  res.json({ ok: true, message: 'Scan iniciado' });
});

// ── Cron: toda hora no minuto :00
cron.schedule('0 * * * *', () => {
  console.log('[Scanner] Cron disparado');
  runScan();
});

// ── Start
app.listen(PORT, () => {
  console.log(`[Scanner] Porta ${PORT} — iniciando primeiro scan...`);
  setTimeout(runScan, 3000); // aguarda 3s para Railway terminar o bind
});
