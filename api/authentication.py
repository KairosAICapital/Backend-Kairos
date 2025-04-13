from django.contrib.auth import get_user_model
from rest_framework_simplejwt.authentication import JWTAuthentication
from .models import ClientData

User = get_user_model()

class EmailJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        """
        Sobreescribe la obtención del usuario usando email en lugar de username.
        """
        try:
            user_id = validated_token.get("user_id")
            # Get the ClientData user directly
            user = ClientData.objects.get(id=user_id)
            return user
        except ClientData.DoesNotExist:
            return None
