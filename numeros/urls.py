from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('black-nigga-1337/', admin.site.urls),
    path('', include('numeros_app.urls'))
]
