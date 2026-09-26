from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.db import transaction

from academics.models import Department
from accounts.models import TeacherProfile, User
from accounts.validators import (
    normalize_email,
    normalize_indian_phone,
    normalize_name,
    normalize_username,
    validate_email_custom,
    validate_indian_phone,
    validate_name_custom,
    validate_username_custom,
)
from .utils import generate_next_employee_code


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


class TeacherCreateForm(forms.Form):
    """
    Form used by Staff to create a new Teacher user and profile.
    """

    username = forms.CharField(
        label="Username",
        max_length=30,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400",
                "placeholder": "e.g. jsmith",
                "autocomplete": "off",
            }
        ),
    )
    email = forms.EmailField(
        label="Email Address",
        required=True,
        widget=forms.EmailInput(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400",
                "placeholder": "teacher@smarttime.ai",
                "autocomplete": "off",
            }
        ),
    )
    first_name = forms.CharField(
        label="First Name",
        max_length=50,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400",
                "placeholder": "e.g. John",
            }
        ),
    )
    last_name = forms.CharField(
        label="Last Name",
        max_length=50,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400",
                "placeholder": "e.g. Doe",
            }
        ),
    )
    phone = forms.CharField(
        label="Phone Number (Optional)",
        max_length=15,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400",
                "placeholder": "e.g. 9876543210",
            }
        ),
    )
    password = forms.CharField(
        label="Password",
        required=True,
        widget=forms.PasswordInput(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400",
                "placeholder": "Enter temporary password",
                "autocomplete": "new-password",
            }
        ),
    )
    confirm_password = forms.CharField(
        label="Confirm Password",
        required=True,
        widget=forms.PasswordInput(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400",
                "placeholder": "Confirm password",
                "autocomplete": "new-password",
            }
        ),
    )
    employee_code = forms.CharField(
        label="Teacher Code",
        max_length=30,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-xs text-slate-500 border border-slate-200 rounded-xl bg-slate-100 font-mono cursor-not-allowed",
                "readonly": True,
            }
        ),
    )
    department = forms.ModelChoiceField(
        label="Department",
        queryset=Department.objects.all().order_by("name"),
        required=True,
        empty_label="Select Department",
        widget=forms.Select(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white",
            }
        ),
    )
    designation = forms.CharField(
        label="Designation",
        max_length=100,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400",
                "placeholder": "e.g. Assistant Professor",
            }
        ),
    )
    joining_date = forms.DateField(
        label="Joining Date (Optional)",
        required=False,
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white",
            }
        ),
    )
    status = forms.ChoiceField(
        label="Employment Status",
        choices=TeacherProfile.Status.choices,
        initial=TeacherProfile.Status.ACTIVE,
        required=False,
        widget=forms.Select(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white",
            }
        ),
    )

    def clean_status(self):
        val = self.cleaned_data.get("status")
        if not val or val not in [TeacherProfile.Status.ACTIVE, TeacherProfile.Status.INACTIVE]:
            return TeacherProfile.Status.ACTIVE
        return val

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee_code"].initial = generate_next_employee_code()

    def clean_username(self):
        val = self.cleaned_data.get("username", "")
        cleaned = normalize_username(val)
        validate_username_custom(cleaned)
        if User.objects.filter(username__iexact=cleaned).exists():
            raise forms.ValidationError("A user with that username already exists.")
        return cleaned

    def clean_email(self):
        val = self.cleaned_data.get("email", "")
        cleaned = normalize_email(val)
        validate_email_custom(cleaned)
        if User.objects.filter(email__iexact=cleaned).exists():
            raise forms.ValidationError("A user with that email already exists.")
        return cleaned

    def clean_employee_code(self):
        # Auto-generated server-side sequence; client-submitted code is never trusted
        return generate_next_employee_code()

    def clean_first_name(self):
        val = self.cleaned_data.get("first_name", "")
        if not val:
            return ""
        cleaned = normalize_name(val)
        validate_name_custom(cleaned)
        return cleaned

    def clean_last_name(self):
        val = self.cleaned_data.get("last_name", "")
        if not val:
            return ""
        cleaned = normalize_name(val)
        validate_name_custom(cleaned)
        return cleaned

    def clean_phone(self):
        val = self.cleaned_data.get("phone", "")
        if not val:
            return None
        cleaned = normalize_indian_phone(val)
        validate_indian_phone(cleaned)
        return cleaned

    def clean_designation(self):
        val = self.cleaned_data.get("designation", "")
        cleaned = val.strip()
        if not cleaned:
            raise forms.ValidationError("Designation is required.")
        return cleaned

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password:
            if password != confirm_password:
                self.add_error("confirm_password", "Passwords do not match.")
            else:
                try:
                    validate_password(password)
                except forms.ValidationError as e:
                    self.add_error("password", e)
        return cleaned_data

    def save(self):
        data = self.cleaned_data
        status = data.get("status", TeacherProfile.Status.ACTIVE)
        is_active = status == TeacherProfile.Status.ACTIVE

        with transaction.atomic():
            user = User.objects.create_user(
                username=data["username"],
                email=data["email"],
                password=data["password"],
                first_name=data.get("first_name", ""),
                last_name=data.get("last_name", ""),
                phone=data.get("phone"),
                role=User.Role.TEACHER,
                is_active=is_active,
            )
            teacher = TeacherProfile.objects.create(
                user=user,
                employee_code=data["employee_code"],
                department=data["department"],
                designation=data["designation"],
                joining_date=data.get("joining_date"),
                status=status,
            )
            return teacher


class TeacherEditForm(forms.Form):
    """
    Form used by Staff to edit an existing Teacher profile and user fields.
    Does not expose password or password hashes.
    """

    first_name = forms.CharField(
        label="First Name",
        max_length=50,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400",
                "placeholder": "e.g. John",
            }
        ),
    )
    last_name = forms.CharField(
        label="Last Name",
        max_length=50,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400",
                "placeholder": "e.g. Doe",
            }
        ),
    )
    email = forms.EmailField(
        label="Email Address",
        required=True,
        widget=forms.EmailInput(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400",
                "placeholder": "teacher@smarttime.ai",
            }
        ),
    )
    phone = forms.CharField(
        label="Phone Number (Optional)",
        max_length=15,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400",
                "placeholder": "e.g. 9876543210",
            }
        ),
    )
    employee_code = forms.CharField(
        label="Teacher Code",
        max_length=30,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-xs text-slate-500 border border-slate-200 rounded-xl bg-slate-100 font-mono cursor-not-allowed",
                "readonly": True,
            }
        ),
    )
    department = forms.ModelChoiceField(
        label="Department",
        queryset=Department.objects.all().order_by("name"),
        required=True,
        widget=forms.Select(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white",
            }
        ),
    )
    designation = forms.CharField(
        label="Designation",
        max_length=100,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400",
                "placeholder": "e.g. Assistant Professor",
            }
        ),
    )
    joining_date = forms.DateField(
        label="Joining Date (Optional)",
        required=False,
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white",
            }
        ),
    )
    status = forms.ChoiceField(
        label="Employment Status",
        choices=TeacherProfile.Status.choices,
        required=False,
        widget=forms.Select(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white",
            }
        ),
    )

    def clean_status(self):
        val = self.cleaned_data.get("status")
        if not val or val not in [TeacherProfile.Status.ACTIVE, TeacherProfile.Status.INACTIVE]:
            return self.teacher.status
        return val

    def __init__(self, teacher, *args, **kwargs):
        self.teacher = teacher
        self.user = teacher.user
        initial = kwargs.get("initial", {})
        initial.update(
            {
                "first_name": self.user.first_name,
                "last_name": self.user.last_name,
                "email": self.user.email,
                "phone": self.user.phone,
                "employee_code": self.teacher.employee_code,
                "department": self.teacher.department_id,
                "designation": self.teacher.designation,
                "joining_date": self.teacher.joining_date,
                "status": self.teacher.status,
            }
        )
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)

    def clean_email(self):
        val = self.cleaned_data.get("email", "")
        cleaned = normalize_email(val)
        validate_email_custom(cleaned)
        if User.objects.filter(email__iexact=cleaned).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("A user with that email already exists.")
        return cleaned

    def clean_employee_code(self):
        # Editing an existing teacher always preserves their current employee code
        return self.teacher.employee_code

    def clean_first_name(self):
        val = self.cleaned_data.get("first_name", "")
        if not val:
            return ""
        cleaned = normalize_name(val)
        validate_name_custom(cleaned)
        return cleaned

    def clean_last_name(self):
        val = self.cleaned_data.get("last_name", "")
        if not val:
            return ""
        cleaned = normalize_name(val)
        validate_name_custom(cleaned)
        return cleaned

    def clean_phone(self):
        val = self.cleaned_data.get("phone", "")
        if not val:
            return None
        cleaned = normalize_indian_phone(val)
        validate_indian_phone(cleaned)
        return cleaned

    def clean_designation(self):
        val = self.cleaned_data.get("designation", "")
        cleaned = val.strip()
        if not cleaned:
            raise forms.ValidationError("Designation is required.")
        return cleaned

    def save(self):
        data = self.cleaned_data
        status = data.get("status", self.teacher.status)
        is_active = status == TeacherProfile.Status.ACTIVE

        with transaction.atomic():
            self.user.first_name = data.get("first_name", "")
            self.user.last_name = data.get("last_name", "")
            self.user.email = data["email"]
            self.user.phone = data.get("phone")
            self.user.is_active = is_active
            self.user.save()

            # Preserve existing employee code unconditionally
            self.teacher.employee_code = self.teacher.employee_code
            self.teacher.department = data["department"]
            self.teacher.designation = data["designation"]
            self.teacher.joining_date = data.get("joining_date")
            self.teacher.status = status
            self.teacher.save()
            return self.teacher

