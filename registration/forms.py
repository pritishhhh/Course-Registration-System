from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.db import connection


class SignUpForm(UserCreationForm):
    full_name = forms.CharField(max_length=150)
    email = forms.EmailField()

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "full_name", "email", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM students WHERE lower(email) = %s LIMIT 1", [email])
            if cursor.fetchone():
                raise forms.ValidationError("An account with this email already exists.")
        return email
