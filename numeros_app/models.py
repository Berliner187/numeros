from django.db import models
from django.http import HttpResponse
from django.db import models
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db.models import Avg, Count, Max, Min
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.translation import get_language
from django.db.models import Sum

from datetime import timedelta, datetime
import json
import uuid


class AuthUser(AbstractUser):
    id_arrival = models.CharField(max_length=100, blank=True, null=True)
    id_staff = models.UUIDField(default=uuid.uuid4, blank=False, null=False)

    groups = models.ManyToManyField(
        Group,
        related_name='customuser_set',
        blank=True,
    )
    user_permissions = models.ManyToManyField(
        Permission,
        related_name='customuser_set',
        blank=True,
    )

    confirmed_user = models.BooleanField(default=False, null=False, blank=False)
    vk_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    name = models.CharField(max_length=255, unique=False, null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)

    def __str__(self):
        return self.username

    class Meta:
        db_table = 'custom_auth_user'


class AuthAdditionalUser(models.Model):
    user = models.OneToOneField(AuthUser, on_delete=models.CASCADE, related_name='additional_info')
    id_telegram = models.IntegerField(null=True, blank=True)
    id_vk = models.IntegerField(null=True, blank=True)
    id_yandex = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'auth_additional_user'


class Subscription(models.Model):
    staff_id = models.UUIDField(blank=False, null=False, unique=True)
    plan_name = models.CharField(max_length=100)
    start_date = models.DateTimeField(auto_now_add=True)
    end_date = models.DateTimeField()
    status = models.CharField(max_length=20, choices=[
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('canceled', 'Canceled'),
    ])
    billing_cycle = models.CharField(max_length=20, choices=[
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'),
    ])
    discount = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)

    def remaining_time(self):
        return self.end_date - datetime.now()

    def __str__(self):
        return f'Subscription {self.plan_name} for {self.staff_id}'

    class Meta:
        db_table = 'subscriptions'


class AvailableSubscription(models.Model):
    PLAN_TYPES = [
        ('free_plan', 'Free – 7 days'),
        ('standard_plan', 'Standard Plan – 30 days'),
        ('premium_plan', 'Premium Plan – 30 days'),
        ('tokens_plan', 'Tokens Package'),
    ]

    plan_name = models.CharField(max_length=100, unique=True)
    plan_type = models.CharField(max_length=20, choices=PLAN_TYPES)
    amount = models.FloatField()
    expiration_date = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if self.plan_type == 'free_plan':
            self.amount = 0
            self.expiration_date = timezone.now() + timedelta(days=7)
        elif self.plan_type == 'ultra_plan':
            self.amount = 990
            self.expiration_date = timezone.now() + timedelta(days=30)
        elif self.plan_type in ['standard_plan', 'premium_plan']:
            self.amount = 220 if self.plan_type == 'standard_plan' else 590
            self.expiration_date = timezone.now() + timedelta(days=30)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Available Subscription: {self.plan_name} - {self.amount} (Expires on: {self.expiration_date})'

    class Meta:
        db_table = 'availble_subscriptions'


class Payment(models.Model):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE)
    staff_id = models.UUIDField(null=False, blank=False)
    payment_id = models.CharField(max_length=100, unique=True)
    order_id = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ])

    def __str__(self):
        return f'Payment {self.payment_id} for {self.subscription.plan_name} - {self.amount}'

    class Meta:
        db_table = 'payments'


class TransactionTracker(models.Model):
    staff_id = models.UUIDField(null=False, blank=False, unique=False)
    payment_id = models.CharField(max_length=100, unique=False)
    order_id = models.CharField(max_length=100, unique=False)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True)
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return (f"{self.staff_id}: {self.amount} on {self.date.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"{self.payment_id} {self.order_id}")

    class Meta:
        db_table = 'transactions_tracker'
