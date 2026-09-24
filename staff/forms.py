from django import forms
from django.contrib.auth import authenticate
from accounts.models import User


class StaffLoginForm(forms.Form):
    """
    Login form for the Staff Web Portal.
    Authenticates via username or email and validates STAFF role authorization.
    """

    username = forms.CharField(
        label="Username or Email",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400",
                "placeholder": "Enter username or email",
                "autocomplete": "username",
                "required": True,
            }
        ),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(
            attrs={
                "class": "w-full pl-3.5 pr-11 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400",
                "placeholder": "Enter password",
                "autocomplete": "current-password",
                "required": True,
            }
        ),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get("username")
        password = cleaned_data.get("password")

        if username and password:
            user = authenticate(self.request, username=username, password=password)

            if user is None:
                raise forms.ValidationError(
                    "Invalid username/email or password.",
                    code="invalid_login",
                )

            if not user.is_active:
                raise forms.ValidationError(
                    "This account is inactive. Please contact support.",
                    code="inactive_account",
                )

            if getattr(user, "role", None) != User.Role.STAFF:
                raise forms.ValidationError(
                    "Access restricted. Only staff members can log into the staff portal.",
                    code="unauthorized_role",
                )

            self.user_cache = user

        return cleaned_data

    def get_user(self):
        return self.user_cache
