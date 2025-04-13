from rest_framework import serializers
import bleach
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import check_password
from rest_framework_simplejwt.tokens import RefreshToken
from .models import ClientData, Chat, Portfolio, PriceData, MarketNews

class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientData
        fields = ['id', 'unique_id', 'email', 'email_alternative', 'phone_number', 'dob']


class ChatSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chat
        fields = '__all__'

class PortfolioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Portfolio
        fields = ['id', 'portfolio_id', 'ticker', 'weight', 'client_id']

class PriceDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceData
        exclude = ['price_id']  # Omitimos ID si no se usa


class MarketNewsSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketNews
        fields = '__all__'

# Acá vamos a sanitizar el message del usuario con bleach.clean(value) en el chatbot.
# Así nos aseguramos que los inputs sean válidos antes de procesarlos.

class ChatbotInputSerializer(serializers.Serializer):
    email = serializers.EmailField()
    message = serializers.CharField()

    def validate_message(self, value):
        """Esto sanitiza el mensaje del usuario antes de procesarlo."""
        return bleach.clean(value) # Limpia el mensaje antes de guardarlo

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        email = data.get("email")
        password = data.get("password")

        try:
            user = ClientData.objects.get(email=email)
        except ClientData.DoesNotExist:
            raise serializers.ValidationError("Usuario no encontrado.")
        
        # 🔹 Django maneja la autenticación con `check_password`
        if not user.check_password(password):
            raise serializers.ValidationError("Contraseña incorrecta.")
        
        tokens = RefreshToken.for_user(user)
        return {
            "access": str(tokens.access_token),
            "refresh": str(tokens),
            "user_id": user.id
        }

from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework import serializers

class EmailTokenObtainSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        email = data.get("email")
        password = data.get("password")

        # Acá estaba el error, antes usaba `User.objects.filter`, debe ser `ClientData.objects.filter`
        user = ClientData.objects.filter(email=email).first()
        if user is None:
            raise serializers.ValidationError("Usuario no encontrado.")

        if not user.check_password(password):  # Django maneja la autenticación
            raise serializers.ValidationError("Contraseña incorrecta.")

        refresh = RefreshToken.for_user(user)

        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "user_id": user.id
        }

