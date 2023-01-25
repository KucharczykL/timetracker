"""timetracker URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from rest_framework import routers, serializers, viewsets
from games.models import Game, Purchase, Platform, Session


class GameSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Game
        fields = "__all__"


class PlatformSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Platform
        fields = "__all__"


class PurchaseSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Purchase
        fields = "__all__"


class SessionSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Session
        fields = "__all__"


class GameViewSet(viewsets.ModelViewSet):
    queryset = Game.objects.all()
    serializer_class = GameSerializer


class PlatformViewSet(viewsets.ModelViewSet):
    queryset = Platform.objects.all()
    serializer_class = PlatformSerializer


class PurchaseViewSet(viewsets.ModelViewSet):
    queryset = Purchase.objects.all()
    serializer_class = PurchaseSerializer


class SessionViewSet(viewsets.ModelViewSet):
    queryset = Session.objects.all()
    serializer_class = SessionSerializer


router = routers.DefaultRouter()
router.register(r"games", GameViewSet)
router.register(r"platforms", PlatformViewSet)
router.register(r"purchases", PurchaseViewSet)
router.register(r"sessions", SessionViewSet)


urlpatterns = [
    path("api/", include(router.urls)),
    path("api-auth/", include("rest_framework.urls", namespace="rest_framework")),
]

if settings.DEBUG:
    urlpatterns.append(path("admin/", admin.site.urls))
