from .views import *
from django.urls import path

urlpatterns = [
    path('', index_view, name='home'),
]
