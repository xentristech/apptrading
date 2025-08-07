import os, csv, re, time, logging
from datetime import datetime
from typing import Dict, List
import pytz, requests, openai
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────
# CONFIG GLOBAL
# ─────────────────────────────────────────────────────────────
SYMBOL       = os.getenv("SYMBOL", "BTC/USD")
API_KEY_12   = os.getenv("TWELVE_API_KEY")
OLLAMA_BASE  = os.getenv("OLLAMA_BASE")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")
TELE_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELE_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TIMEFRAMES   = [tf.strip() for tf in os.getenv("TIMEFRAMES", "5min,15min,1h").split(",")]

# OpenAI → Ollama
openai.api_key  = "none"
openai.api_base = OLLAMA_BASE

# zona horaria “de referencia”
TZ = pytz.timezone("Australia/Sydney")

# ─────────────────────────────────────────────────────────────
# LOG
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)

# ─────────────────────────────────────────────────────────────
# TwelveData helpers
# ─────────────────────────────────────────────────────────────
def _td_request(endpoint:str, params:Dict) -> Dict:
    url = f"https://api.twelvedata.com/{endpoint}"
    params.update({"symbol": SYMBOL, "apikey": API_KEY_12})
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logging.error(f"TwelveData error {endpoint}: {e}")
        return {}

def consulta_twelvedata(indicador:str, tf:str, extra:Dict=None) -> Dict:
    if extra is None:
        extra = {}
    data = _td_request(indicador, {"interval": tf, **extra})
    return data.get("values", [{}])[0] if data else {}

def get_indicadores_tf(tf:str) -> Dict:
    """Devuelve todos los indicadores relevantes para un timeframe."""
    return {
        "precio"      : consulta_twelvedata("price", tf),
        "vwap"        : consulta_twelvedata("vwap", tf),
        "rsi"         : consulta_twelvedata("rsi", tf, {"time_period": 14}),
        "macd"        : consulta_twelvedata("macd", tf),
        "bollinger"   : consulta_twelvedata("bbands", tf),
        "adx"         : consulta_twelvedata("adx", tf, {"time_period": 14}),
        "percent_b"   : consulta_twelvedata("percent_b", tf),
        "obv"         : consulta_twelvedata("obv", tf),
        "bop"         : consulta_twelvedata("bop", tf),
        "typical"     : consulta_twelvedata("typprice", tf),
        "rvol"        : consulta_twelvedata("rvol", tf),
        "stochastic"  : consulta_twelvedata("stoch", tf),
        "linearreg"   : consulta_twelvedata("linearreg", tf),
        "sma"         : consulta_twelvedata("sma", tf, {"time_period": 14}),
        "atr"         : consulta_twelvedata("atr", tf, {"time_period": 14}),
        "cci"         : consulta_twelvedata("cci", tf, {"time_period": 14}),
        "ichimoku"    : consulta_twelvedata("ichimoku", tf),
    }

def obtener_cierres(tf:str, cantidad:int=30) -> List[float]:
    data = _td_request("time_series", {
        "interval": tf,
        "outputsize": cantidad
    })
    return [float(d["close"]) for d in data.get("values", [])]

# ─────────────────────────────────────────────────────────────
# Prompt & IA
# ─────────────────────────────────────────────────────────────
def limpiar(dic:Dict) -> Dict:
    """Aplana un dict de dicts."""
    plano = {}
    for k, v in dic.items():
        if isinstance(v, dict):
            for sk, sv in v.items():
                plano[f"{k}_{sk}"] = sv
        else:
            plano[k] = v
    if "datetime" in dic:
        plano["datetime"] = dic["datetime"]
    return plano

def generar_prompt(indicadores:Dict, cierres:Dict) -> str:
    prompt = """
Actúa como un analista técnico profesional con enfoque institucional. SOLO responde en español.
Usando datos en tiempo real del activo BTC/USD, realiza un análisis completo y exacto.

Formato obligatorio:
📊 **Tabla de indicadores y valores**
✅ **Señal final: COMPRA** | **VENTA** | **NO OPERAR**
🧠 **Razonamiento técnico claro y breve**
📈 **Setup operativo sugerido**
- Entrada: <número>
- SL: <número>
- TP: <número>
- Ratio TP/SL: <número>

No añadas texto fuera de ese formato.

Datos:
"""
    for tf, data in indicadores.items():
        prompt += f"\n--- {tf} ---\n"
        for k, v in data.items():
            prompt += f"{k}: {v}\n"
        prompt += f"Cierres últimas velas: {cierres[tf]}\n"
    return prompt

def analizar_con_ollama(prompt:str) -> str:
    try:
        resp = openai.ChatCompletion.create(
            model     = OLLAMA_MODEL,
            messages  = [{"role":"user", "content": prompt}],
            temperature = 0.2,
            max_tokens  = 1500
        )
        return resp.choices[0].message.content
    except Exception as e:
        logging.error(f"Ollama error: {e}")
        return "ERROR_OLLAMA"

# ─────────────────────────────────────────────────────────────
# Telegram & CSV
# ─────────────────────────────────────────────────────────────
def enviar_telegram(texto:str) -> None:
    url  = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    for chunk in [texto[i:i+4096] for i in range(0, len(texto), 4096)]:
        r = requests.post(url, data={"chat_id": TELE_CHAT_ID, "text": chunk})
        if r.status_code != 200:
            logging.error(f"Telegram error: {r.text}")

def guardar_senal_csv(texto:str, when:datetime) -> None:
    path = "historial_senales.csv"
    headers = ["hora","tipo","entrada","tp","sl","razonamiento","texto"]
    write_header = not os.path.isfile(path)
    tipo = "COMPRA" if "COMPRA" in texto.upper() else "VENTA" if "VENTA" in texto.upper() else ""
    entrada = re.search(r"Entrada[:= ]+([\d\.]+)", texto)
    tp      = re.search(r"TP[:= ]+([\d\.]+)", texto)
    sl      = re.search(r"SL[:= ]+([\d\.]+)", texto)
    razon   = re.search(r"Razonamiento técnico[^:]*:\s*(.*?)(?:\n|$)", texto, re.IGNORECASE|re.DOTALL)
    row = [
        when.strftime("%Y-%m-%d %H:%M:%S"),
        tipo,
        entrada.group(1) if entrada else "",
        tp.group(1) if tp else "",
        sl.group(1) if sl else "",
        (razon.group(1).strip() if razon else ""),
        texto.replace("\n"," ")
    ]
    with open(path,"a",newline="",encoding="utf-8") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(headers)
        w.writerow(row)
