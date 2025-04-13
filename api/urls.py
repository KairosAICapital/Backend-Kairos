from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import (
    ClientViewSet, ChatViewSet, PortfolioViewSet, PriceDataViewSet, MarketNewsViewSet,
    chatbot_response, registrar_usuario, login_usuario, perfil_riesgo, 
    generar_portfolio, obtener_portfolio_usuario, EmailTokenObtainView, 
    get_price_data_endpoint, get_user_chat_history, get_chat_messages, calculate_portfolio_value,
    solicitar_recuperacion, verificar_codigo, cambiar_password, get_portfolio_values
)

# Crear un router para las vistas de la API
router = DefaultRouter()
router.register(r'clients', ClientViewSet)
router.register(r'chats', ChatViewSet)
router.register(r'portfolios', PortfolioViewSet)
router.register(r'price_data', PriceDataViewSet)
router.register(r'market_news', MarketNewsViewSet)

# Definir las rutas de la API
urlpatterns = [
    path('', include(router.urls)),
    path('chatbot/', chatbot_response, name="chatbot"), # Agregamos la ruta para la LLM
    path('register/', registrar_usuario, name='registrar_usuario'), # Registro de usuario
    path('login/', login_usuario, name='login_usuario'), # Login de usuario
    path('perfil-riesgo/', perfil_riesgo, name="perfil_riesgo"), # Evaluación del perfil de riesgo
    path('generar-portfolio/', generar_portfolio, name="generar_portfolio"), # Generación del portfolio
    path('obtener-portfolio/<int:client_id>/', obtener_portfolio_usuario, name='obtener_portfolio_usuario'), # Obtener portafolio del usuario
    path("get-price-data/", get_price_data_endpoint, name="get_price_data"), # Obtener datos de precios del día anterior
    path("token/", EmailTokenObtainView.as_view(), name="token_obtain_pair"),  # Obtiene access y refresh token
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),  # Refresca el access token
    path('user-chats/<int:user_id>/', get_user_chat_history, name='get_user_chat_history'),  # Obtener historial de chats por usuario
    path('chat-messages/<str:chat_title>/<int:user_id>/', get_chat_messages, name='get_chat_messages'),  # Obtener mensajes de un chat específico
    path("recuperar-password/", solicitar_recuperacion, name="recuperar_password"),
    path("verificar-codigo/", verificar_codigo, name="verificar_codigo"),
    path("cambiar-password/", cambiar_password, name="cambiar_password"),
    
    # New endpoint for calculating portfolio value
    path('calculate-portfolio-value/', calculate_portfolio_value, name='calculate_portfolio_value'),
    path('calculate-portfolio-value/<int:client_id>/', calculate_portfolio_value, name='calculate_portfolio_value_by_id'),
    
    # New endpoint for fetching historical portfolio values
    path('portfolio-values/', get_portfolio_values, name='get_portfolio_values'),
    path('portfolio-values/<int:client_id>/', get_portfolio_values, name='get_portfolio_values_by_id')
]
