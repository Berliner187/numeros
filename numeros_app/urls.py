from .views import *
from django.urls import path

urlpatterns = [
    path('', index_view, name='home'),

    path('payment/', create_payment, name='payment'),
    path('payment/success/', PaymentSuccessView.as_view(), name='payment_success'),
    path('payment/fail/', PaymentSuccessView.as_view(), name='payment_fail'),
    path('api/payment/initiate/', PaymentInitiateView.as_view(), name='payment_initiate'),

    path('login/telegram/', phone_number_view, name='auth_telegram'),
    path('verify-code/', verify_code_view, name='verify_code'),

    path('api/v1/signal-secure/', confirm_user, name='api_v1_signal_secure'),
    path('api/v2/one_click_auth/<str:token>/<str:token_hash>/', one_click_auth_view, name='one_click_auth'),
]
