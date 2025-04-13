import sqlite3
import random
import pandas as pd
import numpy as np
import openai
import os
import re 
from .models import MarketNews, PriceData

# 📌 1. Funciones auxiliares para la encuesta de perfil de riesgo

OBJETIVOS_INVERSION = {
    1: 1,  # Preservar el capital
    2: 2,  # Crecimiento moderado
    3: 3,  # Crecimiento a largo plazo
    4: 4   # Maximizar el rendimiento
}

def calcular_porcentaje_riesgo(respuestas):
    """
    Calcula el nivel de riesgo del usuario basado en sus respuestas.

    Parameters:
        respuestas (dict): Respuestas del usuario en la encuesta.

    Returns:
        int: Nivel de riesgo en porcentaje.
    """
    puntaje_total = (
        respuestas["actitud_riesgo"] +
        respuestas["tolerancia_riesgo"] +
        OBJETIVOS_INVERSION.get(respuestas["objetivo_inversion"], 0) +
        respuestas["horizonte_inversion"]
    )

    if puntaje_total <= 8:
        return 0
    elif puntaje_total <= 12:
        return 2
    elif puntaje_total <= 16:
        return 5
    elif puntaje_total <= 20:
        return 10
    else:
        return 15


def clasificar_perfil(respuestas):
    """
    Clasifica el perfil de riesgo del usuario basado en sus respuestas.

    Parameters:
        respuestas (dict): Respuestas del usuario en la encuesta.

    Returns:
        str: Perfil de riesgo (Muy Conservador, Conservador, etc.).
    """
    puntaje_total = (
        respuestas["actitud_riesgo"] +
        respuestas["tolerancia_riesgo"] +
        OBJETIVOS_INVERSION.get(respuestas["objetivo_inversion"], 0) +
        respuestas["horizonte_inversion"]
    )

    if puntaje_total <= 8:
        return "Muy Conservador"
    elif puntaje_total <= 12:
        return "Conservador"
    elif puntaje_total <= 16:
        return "Moderado"
    elif puntaje_total <= 20:
        return "Agresivo"
    else:
        return "Muy Agresivo"


# 📌 2. Funciones para obtener datos de precios

from api.models import PriceData
import random
import pandas as pd
import numpy as np
from django.db.models import Min, Max

def generate_random_symbols(num_symbols):
    """
    Obtiene una lista de tickers aleatorios desde la base de datos PostgreSQL (ORM Django).

    Parameters:
        num_symbols (int): Número de símbolos aleatorios a seleccionar.

    Returns:
        list: Lista de tickers aleatorios.
    """
    tickers = list(PriceData.objects.values_list('ticker', flat=True).distinct())
    return random.sample(tickers, min(num_symbols, len(tickers)))

# Acá, utilicé placeholders "?" en lugar de formatear cadenas directamente en SQL (función download_price_data).
# Evito SQL Injection protegiendo los parámetros en la consulta.

def download_price_data(symbols):
    """
    Obtiene datos de precios ajustados desde PostgreSQL usando el ORM de Django.

    Parameters:
        symbols (list): Lista de tickers.

    Returns:
        pd.DataFrame: DataFrame con los precios ajustados.
    """
    queryset = PriceData.objects.filter(ticker__in=symbols)

    min_date = queryset.aggregate(Min('time'))['time__min']
    max_date = queryset.aggregate(Max('time'))['time__max']

    if not min_date or not max_date:
        raise ValueError("No se encontraron datos de precios para los símbolos seleccionados.")

    print(f"📌 Rango de fechas encontrado: {min_date} a {max_date}")

    data = queryset.filter(time__range=(min_date, max_date)).values('time', 'ticker', 'price')
    df = pd.DataFrame(list(data))

    if df.empty:
        return pd.DataFrame()

    df['time'] = pd.to_datetime(df['time'])
    df = df.drop_duplicates(subset=['time', 'ticker'])
    return df.pivot(index='time', columns='ticker', values='price')


def fetch_prices(tickers, start_date, end_date):
    """
    Obtiene los precios de los tickers desde PostgreSQL usando el ORM de Django.

    Parameters:
        tickers (list): Lista de tickers.
        start_date (str): Fecha de inicio (YYYY-MM-DD).
        end_date (str): Fecha de fin (YYYY-MM-DD).

    Returns:
        pd.DataFrame: DataFrame con los precios ajustados.
    """
    data = PriceData.objects.filter(
        ticker__in=tickers,
        time__range=[start_date, end_date]
    ).values('time', 'ticker', 'price')

    df = pd.DataFrame(list(data))

    if df.empty:
        return pd.DataFrame()

    df['time'] = pd.to_datetime(df['time'])
    df = df.drop_duplicates(subset=['time', 'ticker'])
    return df.pivot(index='time', columns='ticker', values='price')


# 📌 3. Funciones para generar y evaluar portfolios

def generate_portfolio(target_risk, symbols, mean_returns, cov_matrix):
    """
    Genera un portafolio de inversión basado en el nivel de riesgo.

    Parameters:
        target_risk (float): Nivel de riesgo deseado.
        symbols (list): Lista de activos.
        mean_returns (pd.Series): Rendimientos promedio de los activos.
        cov_matrix (pd.DataFrame): Matriz de covarianza de los activos.

    Returns:
        dict: Portafolio generado con tickers y pesos.
    """
    num_assets = len(symbols)
    weights = np.random.uniform(size=num_assets)
    weights /= np.sum(weights)

    portfolio = {symbols[i]: weights[i] for i in range(num_assets)}
    return portfolio


def create_custom_portfolio(num_symbols, mean_ret, cov_mat, custom_risk_level):
    """
    Crea un portafolio personalizado basado en el riesgo del usuario.

    Returns:
        dict: Portafolio con tickers y pesos.
    """
    tickers = generate_random_symbols(num_symbols)
    return generate_portfolio(custom_risk_level, tickers, mean_ret, cov_mat)

from api.models import PriceData, Portfolio, PortfolioValues, ClientData
from django.utils.timezone import timedelta, now
def calculate_portfolio_values_for_user(user):
    portfolios = Portfolio.objects.filter(client=user)
    if not portfolios.exists():
        print("⚠️ Usuario sin portafolio para calcular valores.")
        return
    tickers = list(portfolios.values_list('ticker', flat=True).distinct())
    end_date = now().date()
    start_date = end_date - timedelta(days=30)
    df_prices = fetch_prices(tickers, start_date, end_date)
    if df_prices.empty:
        print("⚠️ No se encontraron precios para los tickers del portafolio.")
        return
    for date, row in df_prices.iterrows():
        total_value = 0
        for position in portfolios:
            shares = float(position.shares or 0)
            price = row.get(position.ticker)
            if price:
                total_value += shares * price
        PortfolioValues.objects.update_or_create(
            user=user,
            date=date.date(),
            defaults={'total_value': total_value}
        )
    print(f"✅ PortfolioValues generados para {user.email}")

def extract_tickers(portfolio):
    """ Devuelve la lista de tickers de un portafolio. """
    return list(portfolio.keys())


def calculate_portfolio_volatility(portfolio, cov_matrix):
    """ Calcula la volatilidad anualizada de un portafolio. """
    weights = np.array(list(portfolio.values()))
    return np.sqrt(np.dot(np.dot(weights.T, cov_matrix), weights)) * np.sqrt(252)


# 4 - Función para clasificar preguntas (LLM):

# Cargar la API Key desde variables de entorno
# Obtener la API key de OpenAI desde variables de entorno
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# 🏷️ Modelo para la clasificación de preguntas
CLASSIFIER_MODEL = "gpt-4o-mini" 
FINANCE_PROMPT = """
Eres un clasificador de preguntas especializado en detectar si una pregunta está relacionada con finanzas o economía. 

- Si la pregunta menciona temas como acciones, inversiones, mercados financieros, tasas de interés, inflación, criptomonedas, análisis técnico o fundamental, entonces responde con "Sí".
- Si la pregunta solicita un resumen de la conversación y el tema principal de la conversación fue finanzas o economía, responde con "Sí".
- Si la pregunta es completamente ajena a finanzas o economía, responde con "No".

Pregunta: "{pregunta}"
Respuesta:
"""


def clasificar_pregunta(pregunta, contexto_chat=""):
    """
    Utiliza un modelo LLM para clasificar si la pregunta es sobre finanzas/economía.
    Devuelve True si la pregunta es financiera, False si no lo es.
    """
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        contexto = f"\nHistorial del chat: {contexto_chat[:500]}" if contexto_chat else ""

        prompt = FINANCE_PROMPT.format(pregunta=pregunta) + contexto # Agregar contexto del chat

        response = client.chat.completions.create(
            model=CLASSIFIER_MODEL,
            messages=[{"role": "system", "content": prompt}]
        )
        resultado = response.choices[0].message.content.strip()
        return resultado.lower() == "sí"  # Devuelve True si es una pregunta financiera
    except Exception as e:
        print(f"❌ Error en clasificar_pregunta: {e}")
        return False  # Por seguridad, si hay un error, se bloquea la pregunta

# 5 - Esta función es para generar títulos para los chats.
def generar_titulo(primer_mensaje):
    """
    Genera un título para el chat basado en el primer mensaje del usuario.
    """
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Eres un asistente que asigna títulos a conversaciones."},
            {"role": "user", "content": f"Genera un título corto y descriptivo para esta conversación: {primer_mensaje}"},
        ]
    )
    
    return response.choices[0].message.content.strip()


from .models import MarketNews, PriceData
import datetime
import json
from django.utils.timezone import now 

def obtener_noticias_recientes(ticker=None):
    """
    Obtiene las últimas noticias del mercado.
    """
    if ticker:
        noticias = MarketNews.objects.filter(tickers__icontains=ticker).order_by('-time')
    else:
        noticias = MarketNews.objects.order_by('-time')

    if not noticias.exists():  # ⚠️ Si no hay noticias, evitar el error
        print(f"⚠️ No se encontraron noticias para {ticker}")
        return []

    return [
        {
            "time": noticia.time.strftime("%Y-%m-%d %H:%M:%S") if noticia.time else "Fecha no disponible",
            "news": noticia.news
        }
        for noticia in noticias
    ]


def obtener_precio_ticker(ticker):
    """
    Obtiene los precios históricos del ticker.
    """
    precios = PriceData.objects.filter(ticker=ticker).order_by('-time')

    if not precios.exists():  # ⚠️ Si no hay precios, evitar el error
        print(f"⚠️ No se encontraron precios para {ticker}")
        return []

    return [
        {
            "time": price.time.strftime("%Y-%m-%d %H:%M:%S") if price.time else "Fecha no disponible",
            "price": price.price
        }
        for price in precios
    ]




import re

def extract_ticker(user_input):
    """
    Extrae el símbolo del ticker desde el mensaje del usuario.
    """
    # Expresión regular para buscar tickers de bolsa (usualmente en mayúsculas y de 1 a 5 caracteres)
    pattern = r'\b[A-Z]{1,5}\b'
    
    # Buscar posibles tickers en el mensaje
    matches = re.findall(pattern, user_input)

    # Filtrar palabras comunes que no son tickers
    stop_words = {"USD", "EUR", "AÑO", "MES", "DÍA", "DAME", "NOTICIAS", "PRECIO", "DE", "Y", "PARA", "LOS", "ÚLTIMOS"}
    tickers = [match for match in matches if match not in stop_words]

    # Si hay al menos un ticker, devolver el primero
    return tickers[0] if tickers else None
