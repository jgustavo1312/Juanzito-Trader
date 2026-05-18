'use strict';

// ============================================================
//  JUANZITO TRADER — DISCORD SCANNER BOT v1.0
//  Roda a cada 15 min · Notifica só quando chega em 🟢
//  LONG ONLY · Spot · Modo conservador (R/R 1:2)
// ============================================================

const DISCORD_WEBHOOK = process.env.DISCORD_WEBHOOK;
const PAIRS           = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT'];
const INTERVAL_MS     = 15 * 60 * 1000; // 15 minutos
const BINANCE         = 'https://api.binance.com/api/v3';

if (!DISCORD_WEBHOOK) {
  console.error('❌ Variável DISCORD_WEBHOOK não definida. Configure no Railway.');
  process.exit(1);
}

// --- Estado em memória ---
const prevLevel = {}; // { 'BTCUSDT': 'none' | 'watch' | 'setup' }

// ============================================================
//  FUNÇÕES DE INDICADORES (idênticas ao painel)
// ============================================================
function ema(data, n) {
  if (data.length < n) return null;
  const k = 2 / (n + 1);
  let e = data.slice(0, n).reduce((a, b) => a + b, 0) / n;
  for (let i = n; i < data.length; i++) e = data[i] * k + e * (1 - k);
  return e;
}

function rsi(data, n = 14) {
  if (data.length < n + 1) return null;
  let g = 0, l = 0;
  for (let i = data.length - n; i < data.length; i++) {
    const d = data[i] - data[i - 1];
    if (d > 0) g += d; else l += Math.abs(d);
  }
  const ag = g / n, al = l / n;
  if (al === 0) return 100;
  return 100 - (100 / (1 + ag / al));
}

function macd(data) {
  if (data.length < 40) return null;
  const k12 = 2 / 13, k26 = 2 / 27, k9 = 2 / 10;
  let e12 = data.slice(0, 12).reduce((a, b) => a + b, 0) / 12;
  for (let i = 12; i < 26; i++) e12 = data[i] * k12 + e12 * (1 - k12);
  let e26 = data.slice(0, 26).reduce((a, b) => a + b, 0) / 26;
  const macdLine = [];
  for (let i = 26; i < data.length; i++) {
    e12 = data[i] * k12 + e12 * (1 - k12);
    e26 = data[i] * k26 + e26 * (1 - k26);
    macdLine.push(e12 - e26);
  }
  if (macdLine.length < 9) return null;
  let signal = macdLine.slice(0, 9).reduce((a, b) => a + b, 0) / 9;
  for (let i = 9; i < macdLine.length; i++) signal = macdLine[i] * k9 + signal * (1 - k9);
  const macdVal = macdLine[macdLine.length - 1];
  const hist    = macdVal - signal;
  return { line: hist, signal: macdVal, hist: signal };
}

// ============================================================
//  MOTOR DE SINAL (idêntico ao painel v1.7)
// ============================================================
function evaluateSignal(d) {
  if (!d || d.error) return null;
  const criteria = [
    { tf: '1D', name: 'EMAs 50/100 alinhadas (>E50 e >E100)', ok: !!(d.price > d.e50 && d.price > d.e100) },
    { tf: '1D', name: 'RSI diário > 50 (momentum bullish)',    ok: !!(d.rsi != null && d.rsi > 50) },
    { tf: '4H', name: 'Preço acima da EMA50 no 4H',            ok: !!(d.d4h && d.d4h.price > d.d4h.e50) },
    { tf: '4H', name: 'MACD histograma positivo no 4H',        ok: !!(d.d4h && d.d4h.macd && d.d4h.macd.hist >= 0) },
    { tf: '1H', name: 'Preço acima da EMA50 no 1H',            ok: !!(d.d1h && d.d1h.price > d.d1h.e50) },
    { tf: '1H', name: 'RSI 1H > 50 (entrada com momentum)',    ok: !!(d.d1h && d.d1h.rsi != null && d.d1h.rsi > 50) },
  ];
  const score = criteria.filter(c => c.ok).length;
  const level = score <= 2 ? 'none' : score <= 4 ? 'watch' : 'setup';
  return { criteria, score, max: 6, level };
}

// ============================================================
//  CÁLCULO DE STOP LOSS E TAKE PROFIT
//  Stop: swing low dos últimos 10 candles 1H - 0.3% buffer
//  TP:   R/R 1:2 conservador
// ============================================================
function calcLevels(price, kl1h, kl4h) {
  // Stop Loss — swing low 1H
  const lows1h   = kl1h.slice(-11, -1).map(k => parseFloat(k[3]));
  const swingLow = Math.min(...lows1h);
  const stop     = swingLow * 0.997;
  const risk     = price - stop;

  // Take Profit — R/R 1:2
  const tp    = price + (risk * 2);
  const rr    = risk > 0 ? (tp - price) / risk : 0;

  // Próxima resistência 4H (referência extra — não usada no TP, só informação)
  const highs4h   = kl4h.slice(-30).map(k => parseFloat(k[2]));
  const aboveRes  = highs4h.filter(h => h > price * 1.001);
  const nextRes   = aboveRes.length > 0 ? Math.min(...aboveRes) : null;

  return {
    stop,
    tp,
    nextRes,
    rr,
    stopPct: ((stop - price) / price * 100),
    tpPct:   ((tp - price) / price * 100),
  };
}

// ============================================================
//  FETCH BINANCE — 4 requisições simultâneas por par
// ============================================================
function buildTF(klines, price) {
  const closes = klines.map(k => parseFloat(k[4]));
  return {
    price,
    e50:  ema(closes, 50),
    e100: ema(closes, 100),
    e200: ema(closes, 200),
    rsi:  rsi(closes),
    macd: macd(closes),
  };
}

async function fetchPair(sym) {
  try {
    const [tk, kl1d, kl4h, kl1h] = await Promise.all([
      fetch(`${BINANCE}/ticker/24hr?symbol=${sym}`).then(r => r.json()),
      fetch(`${BINANCE}/klines?symbol=${sym}&interval=1d&limit=1000`).then(r => r.json()),
      fetch(`${BINANCE}/klines?symbol=${sym}&interval=4h&limit=500`).then(r => r.json()),
      fetch(`${BINANCE}/klines?symbol=${sym}&interval=1h&limit=500`).then(r => r.json()),
    ]);
    if (tk.code) return { error: true, msg: tk.msg };
    const price = parseFloat(tk.lastPrice);
    return {
      price,
      chg24: parseFloat(tk.priceChangePercent),
      ...buildTF(kl1d, price),
      d4h:  buildTF(kl4h, price),
      d1h:  buildTF(kl1h, price),
      kl1h,   // candles brutos para calcStop
      kl4h,   // candles brutos para resistência
    };
  } catch (e) {
    return { error: true, msg: e.message };
  }
}

// ============================================================
//  FORMATAÇÃO
// ============================================================
function fmt(p) {
  if (p >= 10000) return p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (p >= 1)     return p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  return p.toFixed(6);
}

// ============================================================
//  ENVIO DE ALERTA NO DISCORD
// ============================================================
async function sendAlert(sym, d, sig, levels) {
  const chk = (ok) => ok ? '✅' : '❌';

  const criteriaText = sig.criteria
    .map(c => `${chk(c.ok)} \`${c.tf}\` ${c.name}`)
    .join('\n');

  const resLine = levels.nextRes
    ? `\n📌 Próx. resistência 4H: **$${fmt(levels.nextRes)}** (referência)`
    : '';

  const embed = {
    embeds: [{
      title: `⚡ SETUP DETECTADO — ${sym}`,
      color: 0x00c875,
      fields: [
        {
          name: '🟢 Score automático',
          value: `**${sig.score}/${sig.max}** critérios confirmados — verificar manualmente`,
          inline: false,
        },
        {
          name: '💰 Preço atual',
          value: `**$${fmt(d.price)}**  ·  ${d.chg24 >= 0 ? '+' : ''}${d.chg24.toFixed(2)}% 24H`,
          inline: false,
        },
        {
          name: '🔍 Critérios automáticos',
          value: criteriaText,
          inline: false,
        },
        {
          name: '📐 Níveis sugeridos (modo conservador)',
          value: [
            `🛑 **Stop Loss:** $${fmt(levels.stop)} (${levels.stopPct.toFixed(1)}%)`,
            `🎯 **Take Profit:** $${fmt(levels.tp)} (+${levels.tpPct.toFixed(1)}%)`,
            `⚖️ **R/R:** 1 : ${levels.rr.toFixed(2)}`,
            resLine,
          ].filter(Boolean).join('\n'),
          inline: false,
        },
        {
          name: '⚠️ Confirmar antes de entrar',
          value: '→ Abrir TradingView · 1D → 4H → 1H\n→ Candle de reversão no 1H\n→ Coinglass (liquidações 30s)\n→ Checklist 9/9 completo',
          inline: false,
        },
      ],
      footer: { text: 'Juanzito Trader Bot · LONG ONLY · Spot · R/R 1:2 conservador' },
      timestamp: new Date().toISOString(),
    }],
  };

  try {
    const res = await fetch(DISCORD_WEBHOOK, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(embed),
    });
    if (!res.ok) {
      const txt = await res.text();
      console.error(`[DISCORD] Erro ${res.status}: ${txt}`);
    } else {
      console.log(`[${ts()}] ✅ Alerta enviado — ${sym} ${sig.score}/6`);
    }
  } catch (e) {
    console.error(`[DISCORD] Falha no envio: ${e.message}`);
  }
}

// ============================================================
//  SCAN PRINCIPAL
// ============================================================
function ts() { return new Date().toISOString().replace('T', ' ').slice(0, 19); }

async function scan() {
  console.log(`\n[${ts()}] 🔍 Iniciando scan — ${PAIRS.join(', ')}`);

  for (const sym of PAIRS) {
    try {
      const d = await fetchPair(sym);

      if (!d || d.error) {
        console.log(`[${sym}] ❌ Erro no fetch: ${d?.msg || 'desconhecido'}`);
        continue;
      }

      const sig = evaluateSignal(d);
      if (!sig) continue;

      const prev = prevLevel[sym] ?? 'none';
      prevLevel[sym] = sig.level;

      const emoji = { none: '🔴', watch: '🟡', setup: '🟢' }[sig.level];
      console.log(`[${sym}] ${emoji} ${sig.score}/6  prev=${prev}  now=${sig.level}`);

      // Notifica SOMENTE na transição para 'setup'
      if (sig.level === 'setup' && prev !== 'setup') {
        const levels = calcLevels(d.price, d.kl1h, d.kl4h);
        await sendAlert(sym, d, sig, levels);
      }
    } catch (e) {
      console.error(`[${sym}] Exceção: ${e.message}`);
    }

    // Pausa entre pares para não pressionar a API
    await new Promise(r => setTimeout(r, 1200));
  }

  console.log(`[${ts()}] ✔ Scan completo. Próximo em 15 min.\n`);
}

// ============================================================
//  START
// ============================================================
console.log('🚀 Juanzito Trader Bot iniciado');
console.log(`   Pares: ${PAIRS.join(' · ')}`);
console.log(`   Intervalo: 15 minutos`);
console.log(`   Modo: LONG ONLY · Spot · R/R conservador 1:2\n`);

scan();
setInterval(scan, INTERVAL_MS);
