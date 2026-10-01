from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from registration import views

urlpatterns = [
    path("", views.catalog, name="catalog"),
    path("signup/", views.signup, name="signup"),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("my-courses/", views.my_courses, name="my_courses"),
    path("sections/<int:section_id>/register/", views.register, name="register"),
    path("sections/<int:section_id>/drop/", views.drop, name="drop"),
    path("health/", views.health, name="health"),
    path("admin/", admin.site.urls),
]
