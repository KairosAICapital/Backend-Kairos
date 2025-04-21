from datetime import datetime
import json
import os
import uuid
from django.db import models  # Added missing import for models
from django.http import JsonResponse
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth.hashers import make_password, check_password
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404  # Add this import
import openai
import numpy as np  # Add this import
from django.utils.timezone import now
from django.db.models import Count
import json, bleach
from django.http import JsonResponse

from api.utils import (
    generate_random_symbols, 
    download_price_data, 
    create_custom_portfolio, 
    extract_tickers, 
    fetch_prices,
    clasificar_pregunta,
    generar_titulo,
    obtener_noticias_recientes,
    obtener_precio_ticker,
    extract_ticker,
    calculate_portfolio_values_for_user,
    obtener_noticias_ticker
)

from rest_framework import viewsets, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.views.decorators.csrf import csrf_exempt
from rest_framework.permissions import IsAuthenticated
from django.utils.html import escape

import os
import json
import openai
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.timezone import now
from api.models import ClientData, Chat, Portfolio, PortfolioValues, PriceData

from .models import ClientData, Chat, Portfolio, PriceData, MarketNews
from .serializers import (
    ClientSerializer, 
    ChatSerializer, 
    PortfolioSerializer, 
    PriceDataSerializer, 
    MarketNewsSerializer, 
    LoginSerializer, 
    EmailTokenObtainSerializer
)

import openai

# Viewset classes
class ClientViewSet(viewsets.ModelViewSet):
    queryset = ClientData.objects.all()
    serializer_class = ClientSerializer

class ChatViewSet(viewsets.ModelViewSet):
    queryset = Chat.objects.all()
    serializer_class = ChatSerializer

class PortfolioViewSet(viewsets.ModelViewSet):
    queryset = Portfolio.objects.all()
    serializer_class = PortfolioSerializer

class PriceDataViewSet(viewsets.ModelViewSet):
    queryset = PriceData.objects.all()
    serializer_class = PriceDataSerializer

class MarketNewsViewSet(viewsets.ModelViewSet):
    queryset = MarketNews.objects.all()
    serializer_class = MarketNewsSerializer

# Obtener la API key de OpenAI desde variables de entorno
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

from openai.types.beta.threads import RunSubmitToolOutputsRequest
from openai.types.beta import Thread
from openai.types.shared_params import FunctionDefinition
from django.views.decorators.csrf import csrf_exempt

from api.utils import obtener_noticias_ticker_tool, formatear_contexto_usuario  # Asegúrate de tener esta función definida

@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def chatbot_response(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            user_input = bleach.clean(data.get("message", "")).strip()
            chat_title = bleach.clean(data.get("chat_title", "")).strip()
            user = request.user

            if not user_input:
                return JsonResponse({"error": "Falta el mensaje del usuario"}, status=400)

            chat = None
            if chat_title:
                chat = Chat.objects.filter(user=user, title=chat_title).order_by("-time").first()
            else:
                chat = Chat.objects.filter(user=user).order_by("-time").first()
                if chat:
                    chat_title = chat.title

            num_messages = Chat.objects.filter(user=user, title=chat_title).count() if chat else 0
            if not chat or num_messages >= 20:
                chat_title = generar_titulo(user_input)
                chat = Chat.objects.create(user=user, time=now(), title=chat_title, conversation="[]")

            chat_history = Chat.objects.filter(user=user, title=chat_title).order_by("-time")[:20]
            chat_context = []
            for message in reversed(chat_history):
                try:
                    conversation = json.loads(message.conversation)
                    if isinstance(conversation, dict):
                        chat_context.append({"role": "user", "content": conversation.get("question", "")})
                        chat_context.append({"role": "assistant", "content": conversation.get("response", "")})
                except json.JSONDecodeError:
                    continue

            chat_context.append({"role": "user", "content": user_input})

            es_financiera = clasificar_pregunta(user_input, contexto_chat=json.dumps(chat_context))

            if not es_financiera:
                return JsonResponse({"error": "La pregunta no está relacionada con finanzas o economía."}, status=400)


            if not OPENAI_API_KEY:
                return JsonResponse({"error": "API key de OpenAI no configurada"}, status=500)

            system_prompt = (
                "Eres Kairos, un asesor financiero digital confiable, empático y bien informado, diseñado para guiar a personas de Latinoamérica (especialmente Uruguay) en su camino hacia una mejor salud financiera."
                "Tu estilo es claro, conversacional y profesional. Usás un lenguaje simple pero preciso. Acompañás al usuario en cada paso, adaptándote a su nivel de conocimiento."
                "No das consejos financieros personalizados, pero sí explicás estrategias, productos financieros y principios económicos con enfoque educativo."
                "Si el usuario menciona una empresa o ticker y pide novedades, deberás usar la herramienta 'obtener_noticias_ticker' para responder con información actualizada."
            )

            # Inyección del system prompt
            chat_context.insert(0, {"role": "system", "content": system_prompt})

            # Inyección del contexto personalizado del usuario
            contexto_usuario = formatear_contexto_usuario(user)
            chat_context.insert(1, {
                "role": "user",
                "content": f"[Contexto del usuario]\n{contexto_usuario}"
            })

            tools = [obtener_noticias_ticker_tool]

            client = openai.OpenAI(api_key=OPENAI_API_KEY)

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=chat_context,
                tools=tools,
                tool_choice="auto",
                stream=False
            )

            first_choice = response.choices[0]

            if first_choice.finish_reason == "tool_calls":
                tool_call = first_choice.message.tool_calls[0]
                function_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)

                if function_name == "obtener_noticias_ticker":
                    noticias = obtener_noticias_ticker(arguments["ticker"])

                    chat_context.append({"role": "assistant", "tool_call_id": tool_call.id, "content": None, "tool_calls": [tool_call.dict()]})
                    chat_context.append({"role": "tool", "tool_call_id": tool_call.id, "name": "obtener_noticias_ticker", "content": json.dumps(noticias)})

                    final_response = client.chat.completions.create(
                        model="gpt-4o",
                        messages=chat_context,
                        stream=False
                    )
                    content = final_response.choices[0].message.content
                else:
                    content = "La herramienta solicitada no está implementada."
            else:
                content = first_choice.message.content

            bot_response_safe = escape(content)

            Chat.objects.create(
                user=user,
                time=datetime.now(),
                title=chat_title,
                conversation=json.dumps({
                    "question": escape(user_input),
                    "response": bot_response_safe
                })
            )

            return JsonResponse({"response": bot_response_safe, "title": chat_title}, status=200)

        except json.JSONDecodeError:
            return JsonResponse({"error": "Error en el formato JSON"}, status=400)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Método no permitido"}, status=405)


# Esta parte se encarga de registrar al usuario
@api_view(["POST"])
def registrar_usuario(request):
    """
    Endpoint para registrar un nuevo usuario.
    """
    try:
        data = request.data  # DRF maneja JSON automáticamente

        email = data.get("email")
        email_alternative = data.get("email_alternative")
        phone_number = data.get("phone_number")
        dob = data.get("dob")
        password = data.get("password")

        # Validar que no falten campos
        if not all([email, email_alternative, phone_number, dob, password]):
            return Response({"error": "Faltan datos"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Validar formato de email
        try:
            validate_email(email)
        except ValidationError:
            return Response({"error": "Email inválido"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Verificar si el usuario ya existe
        if ClientData.objects.filter(email=email).exists():
            return Response({"error": "Este email ya está registrado"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Convertir fecha de nacimiento a tipo Date
        dob = datetime.strptime(dob, "%Y-%m-%d").date()

        # Crear usuario
        usuario = ClientData(
            unique_id=uuid.uuid4(),
            email=email,
            email_alternative=email_alternative,
            phone_number=phone_number,
            dob=dob
        )
        usuario.set_password(password)  # 🔹 Hashea la contraseña correctamente
        usuario.save()

        # Serializar el usuario creado
        serializer = ClientSerializer(usuario)

        return Response({"message": "Usuario registrado correctamente", "user": serializer.data}, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Implementamos una función para logear al usuario, donde además ya se autentica al mismo
@csrf_exempt
def login_usuario(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            email = data.get("email")
            password = data.get("password")

            if not email or not password:
                return JsonResponse({"error": "Faltan datos"}, status=400)

            try:
                user = ClientData.objects.get(email=email)
            except ClientData.DoesNotExist:
                return JsonResponse({"error": "Usuario no encontrado"}, status=404)

            # Verificamos la contraseña con el método de Django
            if not user.check_password(password):
                return JsonResponse({"error": "Contraseña incorrecta"}, status=401)

            # Generamos los tokens JWT
            refresh = RefreshToken.for_user(user)
            access_token = str(refresh.access_token)

            return JsonResponse({
                "message": "Inicio de sesión exitoso",
                "access": access_token,
                "refresh": str(refresh),
                "user_id": user.id
            }, status=200)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Método no permitido"}, status=405)

# Mapeo de objetivos de inversión
OBJETIVOS_INVERSION = {
    'Preservar el capital': 1,
    'Crecimiento moderado': 2,
    'Crecimiento a largo plazo': 3,
    'Maximizar el rendimiento': 4
}

# Función para calcular el porcentaje de riesgo
def calcular_porcentaje_riesgo(respuestas):
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

# Función para clasificar el perfil de riesgo
def clasificar_perfil(respuestas):
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

@api_view(["POST"])
def perfil_riesgo(request):
    try:
        data = request.data
        user_id = data.get("user_id")

        # Buscar usuario
        usuario = ClientData.objects.get(id=user_id)

        # Calcular perfil de riesgo y porcentaje
        perfil = clasificar_perfil(data)
        porcentaje_riesgo = calcular_porcentaje_riesgo(data)

        # Guardar en la base de datos
        usuario.perfil_riesgo = perfil
        usuario.porcentaje_riesgo = porcentaje_riesgo
        usuario.save()

        return Response({
            "message": "Perfil de riesgo calculado con éxito",
            "perfil_riesgo": perfil,
            "porcentaje_riesgo": porcentaje_riesgo
        }, status=status.HTTP_200_OK)

    except ClientData.DoesNotExist:
        return Response({"error": "Usuario no encontrado"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Función para generar el portfolio customizado
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
import json
import uuid
import numpy as np
from .models import ClientData, Portfolio
from .utils import generate_random_symbols, download_price_data, create_custom_portfolio

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.http import JsonResponse
import json
import numpy as np
import uuid
from api.models import ClientData, PortfolioValues, PriceData 
from api.utils import generate_random_symbols, download_price_data, create_custom_portfolio  # 🔹 Asegúrate de importar correctamente
from rest_framework_simplejwt.authentication import JWTAuthentication

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
import numpy as np
import uuid
import json
from decimal import Decimal, InvalidOperation
import time  # solo si quieres mantener el sleep

@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def generar_portfolio(request):
    print("======== DEBUG: Iniciando generar_portfolio() ========")

    try:
        time.sleep(2)  # pequeño delay de seguridad (opcional)
        user = request.user
        if not user.is_authenticated:
            return JsonResponse({"error": "Usuario no autenticado", "error_code": 401}, status=401)

        client = get_object_or_404(ClientData, email=user.email)
        print(f"✅ Usuario autenticado: {client.email}")

        if client.porcentaje_riesgo is None:
            return JsonResponse({"error": "El usuario no tiene un perfil de riesgo asignado"}, status=400)

        if client.total_investment is None:
            return JsonResponse({"error": "Monto de inversión no definido"}, status=400)

        try:
            investment_amount = Decimal(str(client.total_investment))
            if investment_amount.is_nan():
                raise ValueError("Total investment es NaN")
        except (InvalidOperation, ValueError) as e:
            return JsonResponse({"error": f"Monto de inversión inválido: {e}"}, status=400)

        porcentaje_riesgo = client.porcentaje_riesgo
        num_symbols_list = [20]
        portfolios = []

        for num_symbols in num_symbols_list:
            random_symbols = generate_random_symbols(num_symbols)
            if not random_symbols:
                return JsonResponse({"error": f"No se encontraron {num_symbols} activos válidos."}, status=400)

            price_data = download_price_data(random_symbols)
            log_ret = np.log(price_data / price_data.shift(1))
            mean_ret = log_ret.mean()
            cov_mat = log_ret.cov() * 252

            portfolio = create_custom_portfolio(num_symbols, mean_ret, cov_mat, porcentaje_riesgo)
            latest_prices = {}

            for ticker in portfolio.keys():
                latest_price_data = PriceData.objects.filter(ticker=ticker).order_by('-time').first()
                price = latest_price_data.price if latest_price_data else 100.0
                if price is None or np.isnan(price):
                    print(f"⚠️ Precio inválido para {ticker}, usando 100.0 por defecto")
                    price = 100.0
                latest_prices[ticker] = price

            portfolio_id = uuid.uuid4().int % 10**6
            portfolio_details = []

            for ticker, weight in portfolio.items():
                try:
                    print(f"🔍 Procesando ticker: {ticker}, peso recibido: {weight}")

                    if weight is None or np.isnan(weight):
                        raise ValueError(f"Peso inválido para {ticker}: {weight}")

                    weight = float(weight)
                    print(f"✅ Peso convertido: {weight}")

                    price_raw = latest_prices.get(ticker, 100.0)
                    print(f"🔍 Precio crudo para {ticker}: {price_raw}")

                    if price_raw is None or (isinstance(price_raw, float) and np.isnan(price_raw)):
                        print(f"⚠️ Precio inválido para {ticker}, usando 100.0 por defecto")
                        price_raw = 100.0

                    price = Decimal(str(price_raw))
                    print(f"✅ Precio convertido: {price}")

                    allocated_amount = Decimal(str(weight)) * investment_amount
                    shares = allocated_amount / price if price > 0 else Decimal("0")

                    print(f"📊 Monto asignado: {allocated_amount}, Acciones: {shares}")

                    if any([
                        weight is None or np.isnan(weight),
                        shares is None or np.isnan(float(shares)),
                        price is None or (isinstance(price, float) and np.isnan(price)),
                        str(price).lower() == 'nan'
                    ]):
                        raise ValueError(f"⚠️ Valores inválidos detectados - weight: {weight}, shares: {shares}, price: {price}")

                    print(f"🛠 Guardando posición - Ticker: {ticker}, weight: {weight}, shares: {shares}, price: {price}")

                    Portfolio.objects.create(
                        client=client,
                        portfolio_id=portfolio_id,
                        ticker=ticker,
                        weight=weight,
                        shares=shares,
                        purchase_price=price
                    )

                    portfolio_details.append({
                        "ticker": ticker,
                        "weight": weight,
                        "shares": float(shares),
                        "purchase_price": float(price),
                        "allocated_amount": float(allocated_amount)
                    })

                except (ValueError, InvalidOperation) as e:
                    print(f"❌ Error al procesar {ticker}: {e}")
                    continue
                except Exception as e:
                    print(f"❌ Error creando posición para {ticker}: {e}")
                    continue

            portfolios.append({
                "portfolio_id": portfolio_id,
                "num_symbols": num_symbols,
                "total_investment": float(investment_amount),
                "portfolio": portfolio_details
            })

            try:
                inv_amount_decimal = Decimal(str(investment_amount))
                print(f"✅ Guardando valor total del portafolio: {inv_amount_decimal}")
                
                PortfolioValues.objects.create(
                    user=client,
                    date=now().date(),
                    total_value=inv_amount_decimal
                )
                print("✅ PortfolioValues guardado correctamente.")
            except Exception as e:
                print(f"❌ ERROR al guardar PortfolioValues: {str(e)}")

            print(f"✅ Portfolio {portfolio_id} generado con éxito.")

            # 🔐 Aislar cualquier otro fallo en una envoltura
            try:
                calculate_portfolio_values_for_user(client)
            except Exception as e:
                print(f"⚠️ ERROR al calcular valor de portafolio del usuario: {str(e)}")

            # 🎯 Devolver al frontend inmediatamente, sin bloquear por errores internos
            return JsonResponse({
                "message": "Portfolios generados correctamente",
                "client_id": client.id,
                "portfolios": portfolios
            }, status=201)

    except json.JSONDecodeError:
        return JsonResponse({"error": "Error en el formato JSON"}, status=400)
    except Exception as e:
        print(f"❌ ERROR inesperado: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)


@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def obtener_portfolio_usuario(request, client_id):
    """
    Obtiene el portafolio de inversión de un usuario dado su client_id.
    """
    try:
        # El usuario autenticado debe ser una instancia de ClientData
        if not isinstance(request.user, ClientData):
            return Response(
                {"error": "Usuario no válido"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Si el ID del usuario autenticado no coincide con el client_id solicitado
        if request.user.id != client_id:
            return Response(
                {"error": "No tienes permiso para ver este portfolio"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get portfolios for this user
        portfolios = Portfolio.objects.filter(client=request.user)
        if not portfolios.exists():
            return Response(
                {"message": "El usuario no tiene portfolio"},
                status=status.HTTP_200_OK
            )
        
        # Serialize portfolio info
        serializer = PortfolioSerializer(portfolios, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        print(f"❌ Error obtaining portfolio: {str(e)}")
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    
@api_view(["GET"])
def get_price_data(request):
    """
    Endpoint para obtener datos de precios ajustados.
    
    Parámetros de consulta:
    - symbols: Lista de tickers separados por comas (ej: AAPL,MSFT,GOOGL)
    - start_date: Fecha de inicio (YYYY-MM-DD)
    - end_date: Fecha de fin (YYYY-MM-DD)
    """
    try:
        # Obtener parámetros de la consulta
        symbols_param = request.query_params.get('symbols', '')
        start_date = request.query_params.get('start_date', '')
        end_date = request.query_params.get('end_date', '')
        
        # Validar parámetros
        if not symbols_param or not start_date or not end_date:
            return Response(
                {"error": "Se requieren los parámetros symbols, start_date y end_date"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # Convertir symbols de string a lista
        symbols = [s.strip() for s in symbols_param.split(',')]
        
        # Validar fechas
        try:
            datetime.strptime(start_date, "%Y-%m-%d")
            datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            return Response(
                {"error": "Formato de fecha inválido. Use YYYY-MM-DD"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Obtener datos usando la función original
        price_data = download_price_data(symbols, start_date, end_date)
        
        # Convertir DataFrame a formato JSON serializable
        price_data.index = price_data.index.strftime('%Y-%m-%d')
        result = price_data.reset_index().to_dict(orient='records')
        
        return Response(
            {"message": "Datos obtenidos con éxito", "data": result}, 
            status=status.HTTP_200_OK
        )
        
    except Exception as e:
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

from api.models import PriceData
import pandas as pd
from rest_framework.response import Response
from rest_framework.decorators import api_view
from rest_framework import status
from django.db.models import Max

@api_view(["GET"])
def get_price_data_endpoint(request):
    """
    Endpoint para obtener datos de precios ajustados desde PostgreSQL.

    Parámetros de consulta:
    - symbols: Lista de tickers separados por comas (ej: AAPL,MSFT,GOOGL)
    """
    try:
        print("🔍 DEBUG: get_price_data_endpoint called")

        # Obtener parámetros de la consulta
        symbols_param = request.query_params.get('symbols', '')

        if not symbols_param:
            return Response(
                {"error": "Se requiere el parámetro symbols"},
                status=status.HTTP_400_BAD_REQUEST
            )

        symbols = [s.strip() for s in symbols_param.split(',')]
        print(f"🔍 DEBUG: Requested symbols: {symbols}")

        # Consultar últimos precios para cada símbolo desde PostgreSQL (Django ORM)
        result_data = []
        latest_prices = {}

        for symbol in symbols:
            latest = PriceData.objects.filter(ticker=symbol).order_by('-time').first()

            if latest:
                time_str = latest.time.strftime("%Y-%m-%d")
                print(f"🔍 DEBUG: Found latest price for {symbol}: ${latest.price} on {time_str}")

                if time_str not in latest_prices:
                    latest_prices[time_str] = {'time': time_str}
                latest_prices[time_str][symbol] = latest.price

        for date, data in latest_prices.items():
            result_data.append(data)

        print(f"🔍 DEBUG: Returning {len(result_data)} data points")

        return Response(
            {"message": "Datos obtenidos con éxito", "data": result_data},
            status=status.HTTP_200_OK
        )

    except Exception as e:
        import traceback
        print(f"❌ DEBUG: Error in get_price_data_endpoint: {str(e)}")
        print(traceback.format_exc())
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# Alias for backward compatibility
get_price_data = get_price_data_endpoint

class EmailTokenObtainView(APIView):
    """
    Endpoint para obtener tokens JWT usando email y contraseña.
    """
    def post(self, request):
        serializer = EmailTokenObtainSerializer(data=request.data)
        if serializer.is_valid():
            return Response(serializer.validated_data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(["GET"])
def get_user_chat_history(request, user_id):
    """
    Endpoint para obtener el historial de chats de un usuario.
    
    Parámetros:
    - user_id: ID del usuario
    
    Retorna:
    - Lista de chats con sus títulos y fechas, agrupados por título
    """
    try:
        # Verificar si el usuario existe
        try:
            user = ClientData.objects.get(id=user_id)
        except ClientData.DoesNotExist:
            return Response(
                {"error": "Usuario no encontrado"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Obtener todos los chats únicos (por título) del usuario
        # Usamos values() y annotate() para agrupar por título y obtener el más reciente
        chats = Chat.objects.filter(user=user) \
                            .values('title') \
                            .annotate(last_time=models.Max('time'), 
                                     message_count=models.Count('title')) \
                            .order_by('-last_time')
        
        # Formatear los resultados
        chat_history = []
        for chat in chats:
            chat_history.append({
                'title': chat['title'],
                'last_message_time': chat['last_time'],
                'message_count': chat['message_count']
            })
        
        return Response({
            "user_id": user_id,
            "chats": chat_history
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        import traceback
        print(f"❌ ERROR: Error en get_user_chat_history: {str(e)}")
        print(traceback.format_exc())
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(["GET"])
def get_chat_messages(request, chat_title, user_id):
    """
    Endpoint para obtener los mensajes de un chat específico.
    
    Parámetros:
    - chat_title: Título del chat
    - user_id: ID del usuario
    
    Retorna:
    - Lista de mensajes del chat (máximo 20)
    """
    try:
        # Verificar si el usuario existe
        try:
            user = ClientData.objects.get(id=user_id)
        except ClientData.DoesNotExist:
            return Response(
                {"error": "Usuario no encontrado"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Obtener los mensajes del chat (limitado a los últimos 20)
        messages = Chat.objects.filter(
            user=user,
            title=chat_title
        ).order_by('-time')[:20]  # Limitado a 20 mensajes
        
        # Si no hay mensajes, retornar error
        if not messages:
            return Response(
                {"error": "Chat no encontrado o sin mensajes"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Formatear los mensajes
        formatted_messages = []
        for message in reversed(messages):  # Invertimos para orden cronológico
            try:
                conversation = json.loads(message.conversation)
                if isinstance(conversation, dict):
                    formatted_messages.append({
                        'question': conversation.get('question', ''),
                        'response': conversation.get('response', ''),
                        'time': message.time
                    })
            except json.JSONDecodeError:
                continue  # Si hay errores en JSON, ignoramos el mensaje corrupto
        
        return Response({
            "chat_title": chat_title,
            "user_id": user_id,
            "messages": formatted_messages
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        import traceback
        print(f"❌ ERROR: Error en get_chat_messages: {str(e)}")
        print(traceback.format_exc())
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def calculate_portfolio_value(request, client_id=None):
    """
    Calculates the value of a user's portfolio based on the number of shares
    and market prices at a specific date (or latest prices if no date provided).
    Also updates the user's portfolio_value field when using current prices.
    """
    try:
        valuation_date_str = request.query_params.get('valuation_date', None)
        valuation_date = None
        is_historical = False

        if valuation_date_str:
            try:
                valuation_date = datetime.strptime(valuation_date_str, "%Y-%m-%d").date()
                is_historical = True
                print(f"🔍 Calculating historical portfolio value for date: {valuation_date}")
            except ValueError:
                return Response({"error": "Formato de fecha inválido. Use YYYY-MM-DD"}, status=status.HTTP_400_BAD_REQUEST)

        if client_id is None:
            client = request.user
        else:
            if request.user.id != client_id and not request.user.is_staff:
                return Response({"error": "No tienes permiso para ver este portfolio"}, status=status.HTTP_403_FORBIDDEN)
            client = get_object_or_404(ClientData, id=client_id)

        portfolios = Portfolio.objects.filter(client=client)
        if not portfolios.exists():
            return Response({"message": "El usuario no tiene portfolio"}, status=status.HTTP_200_OK)

        tickers = set(portfolios.values_list('ticker', flat=True))
        ticker_prices = {}

        for ticker in tickers:
            try:
                if is_historical:
                    price_query = PriceData.objects.filter(ticker=ticker, time__date=valuation_date).order_by('-time')
                    if not price_query.exists():
                        price_query = PriceData.objects.filter(ticker=ticker, time__date__lte=valuation_date).order_by('-time')
                    price_data = price_query.first()
                else:
                    price_data = PriceData.objects.filter(ticker=ticker).order_by('-time').first()

                if price_data:
                    price_value = price_data.price
                    if price_value is None or str(price_value).lower() == 'nan':
                        raise ValueError(f"Precio inválido para {ticker}: {price_value}")
                    ticker_prices[ticker] = price_value
                    price_date = price_data.time.date()
                    if is_historical and price_date != valuation_date:
                        print(f"⚠️ No exact price found for {ticker} on {valuation_date}, using price from {price_date}")
                else:
                    print(f"⚠️ No price data found for {ticker}")
            except Exception as e:
                print(f"⚠️ Error getting price for {ticker}: {str(e)}")

        portfolio_values = {}
        ticker_details = []
        total_value = 0
        portfolio_ids = set(portfolios.values_list('portfolio_id', flat=True))

        for p_id in portfolio_ids:
            portfolio_items = portfolios.filter(portfolio_id=p_id)
            portfolio_value = 0

            for item in portfolio_items:
                try:
                    valuation_price = ticker_prices.get(item.ticker, item.purchase_price)
                    if str(valuation_price).lower() == 'nan':
                        raise ValueError(f"Valuation price NaN para {item.ticker}")

                    shares = float(item.shares)
                    purchase_price = float(item.purchase_price)
                    weight = float(item.weight)

                    if any(map(lambda x: str(x).lower() == 'nan', [shares, purchase_price, weight])):
                        raise ValueError(f"NaN detectado en posición de {item.ticker}")

                    position_value = shares * valuation_price
                    price_change_pct = ((valuation_price - purchase_price) / purchase_price) * 100 if purchase_price > 0 else 0

                    portfolio_value += position_value
                    total_value += position_value

                    ticker_details.append({
                        'ticker': item.ticker,
                        'portfolio_id': item.portfolio_id,
                        'shares': shares,
                        'purchase_price': purchase_price,
                        'valuation_price': valuation_price,
                        'weight': weight,
                        'position_value': position_value,
                        'price_change_pct': price_change_pct
                    })
                except Exception as e:
                    print(f"❌ Error procesando {item.ticker}: {e}")

            portfolio_values[p_id] = round(portfolio_value, 2)

        if not is_historical:
            client.portfolio_value = round(total_value, 2)
            client.last_value_update = now()
            client.save()
            valuation_reference_date = client.last_value_update
        else:
            valuation_reference_date = valuation_date

        return Response({
            "user_id": client.id,
            "total_investment": float(client.total_investment),
            "portfolio_value": round(total_value, 2),
            "valuation_date": valuation_reference_date,
            "is_historical_valuation": is_historical,
            "return_pct": ((total_value - float(client.total_investment)) / float(client.total_investment)) * 100 if float(client.total_investment) > 0 else 0,
            "portfolios": portfolio_values,
            "holdings": ticker_details
        }, status=status.HTTP_200_OK)

    except Exception as e:
        import traceback
        print(f"❌ ERROR: Error calculating portfolio value: {str(e)}")
        print(traceback.format_exc())
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    

import random
import string
from datetime import timedelta
from django.utils.timezone import now
from django.core.mail import send_mail
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from api.models import ClientData, PasswordResetCode

@csrf_exempt
def solicitar_recuperacion(request):
    """
    Genera un código de recuperación y lo envía al email del usuario.
    """
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            email = data.get("email")

            if not email:
                return JsonResponse({"error": "Falta el email"}, status=400)

            try:
                user = ClientData.objects.get(email=email)
            except ClientData.DoesNotExist:
                return JsonResponse({"error": "Usuario no encontrado"}, status=404)

            # Generar código de recuperación (6 dígitos aleatorios)
            code = ''.join(random.choices(string.digits, k=6))

            # Guardar en la base de datos
            PasswordResetCode.objects.create(user=user, code=code, created_at=now())

            # Enviar email con el código
            send_mail(
                "Código de recuperación de contraseña",
                f"Tu código de recuperación es: {code}\n\nEste código expira en 10 minutos.",
                "kairosaicapital@gmail.com",
                [email],
                fail_silently=False
            )

            return JsonResponse({"message": "Código enviado al email"}, status=200)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Método no permitido"}, status=405)

@csrf_exempt
def verificar_codigo(request):
    """
    Verifica si el código de recuperación ingresado por el usuario es correcto.
    """
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            email = data.get("email")
            code = data.get("code")

            if not email or not code:
                return JsonResponse({"error": "Faltan datos"}, status=400)

            try:
                user = ClientData.objects.get(email=email)
                reset_code = PasswordResetCode.objects.filter(user=user).order_by('-created_at').first()
            except ClientData.DoesNotExist:
                return JsonResponse({"error": "Usuario no encontrado"}, status=404)

            if not reset_code:
                return JsonResponse({"error": "Código inválido"}, status=400)

            # Verificar si el código ingresado es el mismo que el de la base de datos
            if reset_code.code != code:
                return JsonResponse({"error": "Código incorrecto"}, status=400)

            # Verificar si el código ha expirado
            if reset_code.is_expired():
                return JsonResponse({"error": "Código expirado"}, status=400)

            return JsonResponse({"message": "Código válido"}, status=200)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Método no permitido"}, status=405)



from django.contrib.auth.hashers import make_password

@csrf_exempt
def cambiar_password(request):
    """
    Permite cambiar la contraseña de un usuario si el código de recuperación es válido.
    """
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            email = data.get("email")
            code = data.get("code")
            new_password = data.get("new_password")

            if not email or not code or not new_password:
                return JsonResponse({"error": "Faltan datos"}, status=400)

            try:
                user = ClientData.objects.get(email=email)
                reset_code = PasswordResetCode.objects.filter(user=user, code=code).order_by('-created_at').first()
            except ClientData.DoesNotExist:
                return JsonResponse({"error": "Usuario no encontrado"}, status=404)

            if not reset_code:
                return JsonResponse({"error": "Código inválido"}, status=400)

            if reset_code.code != code:
                return JsonResponse({"error": "Código incorrecto"}, status=400)

            if reset_code.is_expired():
                return JsonResponse({"error": "Código expirado"}, status=400)

            # Cambiar la contraseña del usuario
            user.password = make_password(new_password)
            user.save()

            # Eliminar el código de recuperación usado
            reset_code.delete()

            return JsonResponse({"message": "Contraseña cambiada correctamente"}, status=200)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Método no permitido"}, status=405)

@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_portfolio_values(request, client_id=None):
    """
    Retrieves historical portfolio values for a user within a date range.
    
    Parameters:
    - client_id: Optional user ID. If not provided, uses the authenticated user.
    
    Query Parameters:
    - start_date: Required date in YYYY-MM-DD format for beginning of range
    - end_date: Required date in YYYY-MM-DD format for end of range
    
    Returns:
    - List of portfolio values within the specified date range
    """
    try:
        # Get date range from query parameters
        start_date_str = request.query_params.get('start_date')
        end_date_str = request.query_params.get('end_date')
        
        # Validate parameters
        if not start_date_str or not end_date_str:
            return Response(
                {"error": "Los parámetros start_date y end_date son obligatorios"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # Parse and validate the date format
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"error": "Formato de fecha inválido. Use YYYY-MM-DD"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # Ensure start date is before end date
        if start_date > end_date:
            return Response(
                {"error": "La fecha de inicio debe ser anterior a la fecha de fin"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Determine which user's portfolio to fetch
        if client_id is None:
            client = request.user
        else:
            # Only allow admins or the user themselves to access their portfolio values
            if request.user.id != client_id and not request.user.is_staff:
                return Response(
                    {"error": "No tienes permiso para ver estos datos"}, 
                    status=status.HTTP_403_FORBIDDEN
                )
            client = get_object_or_404(ClientData, id=client_id)
        
        # Query for portfolio values within the date range
        portfolio_values = PortfolioValues.objects.filter(
            user=client,
            date__gte=start_date,
            date__lte=end_date
        ).order_by('date')
        
        # Check if we found any values
        if not portfolio_values.exists():
            return Response(
                {"message": "No hay valores de portafolio en el rango de fechas especificado"}, 
                status=status.HTTP_200_OK
            )
        
        # Format the results
        values_data = []
        for value in portfolio_values:
            values_data.append({
                'date': value.date,
                'total_value': float(value.total_value)
            })
        
        # Get starting investment value for comparison
        total_investment = float(client.total_investment)
        
        return Response({
            "user_id": client.id,
            "total_investment": total_investment,
            "start_date": start_date,
            "end_date": end_date,
            "portfolio_values": values_data,
            "total_return_pct": ((float(values_data[-1]['total_value']) - total_investment) / total_investment * 100) 
                if values_data and total_investment > 0 else 0
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        import traceback
        print(f"❌ ERROR: Error retrieving portfolio values: {str(e)}")
        print(traceback.format_exc())
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


