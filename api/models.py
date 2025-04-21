from django.db import models
import uuid
from django.utils.timezone import now

from django.contrib.auth.models import AbstractUser
from django.db import models
import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
import uuid

class ClientDataManager(BaseUserManager):
    def create_user(self, email, password=None, dob=None, **extra_fields):
        if not email:
            raise ValueError('El email es obligatorio')

        email = self.normalize_email(email)

        # 🔹 Si `dob` no está definido, asignamos un valor por defecto
        if dob is None:
            dob = "2000-01-01"  # Puedes cambiar esta fecha si lo deseas

        user = self.model(email=email, dob=dob, **extra_fields)
        user.set_password(password)  # 🔹 Hashea la contraseña antes de guardarla
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        
        # 🔹 Llamamos a `create_user()` pasando `dob` como argumento
        return self.create_user(email, password, dob="2000-01-01", **extra_fields)


class ClientData(AbstractBaseUser, PermissionsMixin):
    id = models.AutoField(primary_key=True)
    unique_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    email = models.EmailField(max_length=255, unique=True)
    email_alternative = models.EmailField(max_length=255, blank=True, null=True)
    phone_number = models.CharField(max_length=50)
    dob = models.DateField()
    fecha_registro = models.DateTimeField(auto_now_add=True)

    perfil_riesgo = models.CharField(
        max_length=50, 
        choices=[
            ('Muy Conservador', 'Muy Conservador'),
            ('Conservador', 'Conservador'),
            ('Moderado', 'Moderado'),
            ('Agresivo', 'Agresivo'),
            ('Muy Agresivo', 'Muy Agresivo')
        ], 
        null=True, 
        blank=True
    )
    
    porcentaje_riesgo = models.IntegerField(null=True, blank=True)
    total_investment = models.DecimalField(max_digits=10, decimal_places=2, default=100.00)
    portfolio_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    last_value_update = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = ClientDataManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "Client_Data"

    def __str__(self):
        return self.email



class Portfolio(models.Model):
    id = models.AutoField(primary_key=True)
    client = models.ForeignKey(
        ClientData,  # 🔹 Relación con el cliente
        on_delete=models.CASCADE,
        related_name="portfolios"
    )
    portfolio_id = models.BigIntegerField()
    ticker = models.CharField(max_length=500)
    weight = models.FloatField()
    shares = models.DecimalField(max_digits=15, decimal_places=6, null=True, blank=True)
    purchase_price = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)

    def save(self, *args, **kwargs):
        # If shares_amount was passed, use it for shares field
        shares_amount = kwargs.pop('shares_amount', None)
        if shares_amount is not None:
            self.shares = shares_amount
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'portfolios'


class Chat(models.Model):
    chat_id = models.AutoField(primary_key=True)  # 🔹 Dejar que Django lo maneje automáticamente
    user = models.ForeignKey(ClientData, on_delete=models.CASCADE)
    time = models.DateTimeField(auto_now_add=True)
    conversation = models.TextField()
    title = models.CharField(max_length=255, blank=True, null=True)  # Nuevo campo para el título

    class Meta:
        db_table = "Chats"

    def __str__(self):
        return f"Chat {self.chat_id} - {self.user.email}"


class MarketNews(models.Model):
    news_id = models.AutoField(primary_key=True)  # Eliminamos null=True
    time = models.DateTimeField()
    news = models.TextField()
    news_embedding = models.TextField()
    sentiment_score = models.FloatField()
    sentiment_class = models.CharField(max_length=50)
    tickers = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'Market_News'

class PriceData(models.Model):
    price_id = models.AutoField(primary_key=True)  # Eliminamos null=True
    ticker = models.CharField(max_length=15)  # Agregamos max_length
    time = models.DateTimeField()
    price = models.FloatField()

    class Meta:
        db_table = 'Price_Data'


import uuid
from django.utils.timezone import now, timedelta
from django.db import models
from django.contrib.auth.models import AbstractBaseUser
from .models import ClientData

class PasswordResetCode(models.Model):
    user = models.ForeignKey(ClientData, on_delete=models.CASCADE)
    code = models.CharField(max_length=6, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        return now() > self.created_at + timedelta(minutes=10)  # Expira en 10 minutos

    def __str__(self):
        return f"Password Reset Code for {self.user.email}"

    class Meta:
        db_table = "PasswordResetCode"

class PortfolioValues(models.Model):
    user = models.ForeignKey(ClientData, on_delete=models.CASCADE)
    date = models.DateField()  # 🔹 Nueva columna para registrar la fecha
    total_value = models.DecimalField(max_digits=15, decimal_places=2)

    class Meta:
        db_table = "portfolio_values"
        unique_together = ("user", "date")  # 🔹 Asegura que no haya registros duplicados por usuario y fecha

    def __str__(self):
        return f"{self.user.email} - {self.date} - ${self.total_value}"
