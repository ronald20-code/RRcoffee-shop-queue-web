from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from kiosk import views as kiosk_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="kiosk/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("register/", kiosk_views.register, name="register"),
    path("", include("kiosk.urls")),
]

# Serve uploaded photos while developing (DEBUG=True). In production, let the
# web server (nginx etc.) serve MEDIA_ROOT instead.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
