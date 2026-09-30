from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.db import transaction

from academics.models import (
    Classroom,
    Department,
    Division,
    Laboratory,
    PracticalBatch,
    Program,
    Semester,
    Subject,
    TeacherAvailability,
    TeacherLeave,
    TeacherSubject,
    Timetable,
    TimetableConflict,
    TimetableSlot,
)
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


# ==================== STUDENT FORMS ====================

from academics.models import Division, PracticalBatch
from accounts.models import StudentProfile
from .utils import generate_next_student_code

_INPUT_CLASS = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400"
_SELECT_CLASS = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white"
_READONLY_CLASS = "w-full px-3.5 py-2.5 text-xs text-slate-500 border border-slate-200 rounded-xl bg-slate-100 font-mono cursor-not-allowed"


class StudentCreateForm(forms.Form):
    """
    Form used by Staff to create a new Student user account and profile.
    """

    username = forms.CharField(
        label="Username",
        max_length=30,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": _INPUT_CLASS,
                "placeholder": "e.g. jdoe",
                "autocomplete": "off",
            }
        ),
    )
    email = forms.EmailField(
        label="Email Address",
        required=True,
        widget=forms.EmailInput(
            attrs={
                "class": _INPUT_CLASS,
                "placeholder": "student@smarttime.ai",
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
                "class": _INPUT_CLASS,
                "placeholder": "e.g. Rahul",
            }
        ),
    )
    last_name = forms.CharField(
        label="Last Name",
        max_length=50,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": _INPUT_CLASS,
                "placeholder": "e.g. Sharma",
            }
        ),
    )
    phone = forms.CharField(
        label="Phone Number (Optional)",
        max_length=15,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": _INPUT_CLASS,
                "placeholder": "e.g. 9876543210",
            }
        ),
    )
    password = forms.CharField(
        label="Password",
        required=True,
        widget=forms.PasswordInput(
            attrs={
                "class": _INPUT_CLASS,
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
                "class": _INPUT_CLASS,
                "placeholder": "Confirm password",
                "autocomplete": "new-password",
            }
        ),
    )
    student_code = forms.CharField(
        label="Student Code",
        max_length=30,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": _READONLY_CLASS,
                "readonly": True,
            }
        ),
    )
    division = forms.ModelChoiceField(
        label="Division",
        queryset=Division.objects.all().order_by("name"),
        required=True,
        empty_label="Select Division",
        widget=forms.Select(
            attrs={"class": _SELECT_CLASS}
        ),
    )
    batch = forms.ModelChoiceField(
        label="Practical Batch",
        queryset=PracticalBatch.objects.all().order_by("name"),
        required=False,
        empty_label="Select Batch (Optional)",
        widget=forms.Select(
            attrs={"class": _SELECT_CLASS}
        ),
    )
    roll_number = forms.CharField(
        label="Roll Number",
        max_length=30,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": _INPUT_CLASS,
                "placeholder": "e.g. 101",
            }
        ),
    )
    admission_year = forms.IntegerField(
        label="Admission Year",
        required=True,
        widget=forms.NumberInput(
            attrs={
                "class": _INPUT_CLASS,
                "placeholder": "e.g. 2024",
                "min": "2000",
                "max": "2099",
            }
        ),
    )
    status = forms.ChoiceField(
        label="Student Status",
        choices=StudentProfile.Status.choices,
        initial=StudentProfile.Status.ACTIVE,
        required=False,
        widget=forms.Select(
            attrs={"class": _SELECT_CLASS}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["student_code"].initial = generate_next_student_code()

    def clean_status(self):
        val = self.cleaned_data.get("status")
        valid_statuses = [s[0] for s in StudentProfile.Status.choices]
        if not val or val not in valid_statuses:
            return StudentProfile.Status.ACTIVE
        return val

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

    def clean_student_code(self):
        # Auto-generated server-side sequence; client-submitted code is never trusted
        return generate_next_student_code()

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

    def clean_roll_number(self):
        val = self.cleaned_data.get("roll_number", "")
        cleaned = str(val).strip()
        if not cleaned:
            raise forms.ValidationError("Roll number is required.")
        return cleaned

    def clean_admission_year(self):
        val = self.cleaned_data.get("admission_year")
        if val is None:
            raise forms.ValidationError("Admission year is required.")
        if val < 2000 or val > 2099:
            raise forms.ValidationError("Admission year must be between 2000 and 2099.")
        return val

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

        # Validate roll number uniqueness within division
        division = cleaned_data.get("division")
        roll_number = cleaned_data.get("roll_number")
        if division and roll_number:
            if StudentProfile.objects.filter(
                division=division,
                roll_number__iexact=roll_number,
            ).exists():
                self.add_error(
                    "roll_number",
                    "A student with this roll number already exists in this division.",
                )

        # Validate batch belongs to division
        batch = cleaned_data.get("batch")
        if batch and division:
            if batch.division_id != division.id:
                self.add_error(
                    "batch",
                    "The selected practical batch does not belong to the selected division.",
                )

        return cleaned_data

    def save(self):
        data = self.cleaned_data
        status = data.get("status", StudentProfile.Status.ACTIVE)
        is_active = status == StudentProfile.Status.ACTIVE

        with transaction.atomic():
            user = User.objects.create_user(
                username=data["username"],
                email=data["email"],
                password=data["password"],
                first_name=data.get("first_name", ""),
                last_name=data.get("last_name", ""),
                phone=data.get("phone"),
                role=User.Role.STUDENT,
                is_active=is_active,
            )
            student = StudentProfile.objects.create(
                user=user,
                student_code=data["student_code"],
                division=data["division"],
                batch=data.get("batch"),
                roll_number=data["roll_number"],
                admission_year=data["admission_year"],
                status=status,
            )
            return student


class StudentEditForm(forms.Form):
    """
    Form used by Staff to edit an existing Student profile and user fields.
    Does not expose password or password hashes.
    """

    first_name = forms.CharField(
        label="First Name",
        max_length=50,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": _INPUT_CLASS,
                "placeholder": "e.g. Rahul",
            }
        ),
    )
    last_name = forms.CharField(
        label="Last Name",
        max_length=50,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": _INPUT_CLASS,
                "placeholder": "e.g. Sharma",
            }
        ),
    )
    email = forms.EmailField(
        label="Email Address",
        required=True,
        widget=forms.EmailInput(
            attrs={
                "class": _INPUT_CLASS,
                "placeholder": "student@smarttime.ai",
            }
        ),
    )
    phone = forms.CharField(
        label="Phone Number (Optional)",
        max_length=15,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": _INPUT_CLASS,
                "placeholder": "e.g. 9876543210",
            }
        ),
    )
    student_code = forms.CharField(
        label="Student Code",
        max_length=30,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": _READONLY_CLASS,
                "readonly": True,
            }
        ),
    )
    division = forms.ModelChoiceField(
        label="Division",
        queryset=Division.objects.all().order_by("name"),
        required=True,
        widget=forms.Select(
            attrs={"class": _SELECT_CLASS}
        ),
    )
    batch = forms.ModelChoiceField(
        label="Practical Batch",
        queryset=PracticalBatch.objects.all().order_by("name"),
        required=False,
        empty_label="Select Batch (Optional)",
        widget=forms.Select(
            attrs={"class": _SELECT_CLASS}
        ),
    )
    roll_number = forms.CharField(
        label="Roll Number",
        max_length=30,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": _INPUT_CLASS,
                "placeholder": "e.g. 101",
            }
        ),
    )
    admission_year = forms.IntegerField(
        label="Admission Year",
        required=True,
        widget=forms.NumberInput(
            attrs={
                "class": _INPUT_CLASS,
                "placeholder": "e.g. 2024",
                "min": "2000",
                "max": "2099",
            }
        ),
    )
    status = forms.ChoiceField(
        label="Student Status",
        choices=StudentProfile.Status.choices,
        required=False,
        widget=forms.Select(
            attrs={"class": _SELECT_CLASS}
        ),
    )

    def __init__(self, student, *args, **kwargs):
        self.student = student
        self.user = student.user
        initial = kwargs.get("initial", {})
        initial.update(
            {
                "first_name": self.user.first_name,
                "last_name": self.user.last_name,
                "email": self.user.email,
                "phone": self.user.phone,
                "student_code": self.student.student_code,
                "division": self.student.division_id,
                "batch": self.student.batch_id,
                "roll_number": self.student.roll_number,
                "admission_year": self.student.admission_year,
                "status": self.student.status,
            }
        )
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)

    def clean_status(self):
        val = self.cleaned_data.get("status")
        valid_statuses = [s[0] for s in StudentProfile.Status.choices]
        if not val or val not in valid_statuses:
            return self.student.status
        return val

    def clean_email(self):
        val = self.cleaned_data.get("email", "")
        cleaned = normalize_email(val)
        validate_email_custom(cleaned)
        if User.objects.filter(email__iexact=cleaned).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("A user with that email already exists.")
        return cleaned

    def clean_student_code(self):
        # Editing an existing student always preserves their current student code
        return self.student.student_code

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

    def clean_roll_number(self):
        val = self.cleaned_data.get("roll_number", "")
        cleaned = str(val).strip()
        if not cleaned:
            raise forms.ValidationError("Roll number is required.")
        return cleaned

    def clean_admission_year(self):
        val = self.cleaned_data.get("admission_year")
        if val is None:
            raise forms.ValidationError("Admission year is required.")
        if val < 2000 or val > 2099:
            raise forms.ValidationError("Admission year must be between 2000 and 2099.")
        return val

    def clean(self):
        cleaned_data = super().clean()

        # Validate roll number uniqueness within division (excluding self)
        division = cleaned_data.get("division")
        roll_number = cleaned_data.get("roll_number")
        if division and roll_number:
            if StudentProfile.objects.filter(
                division=division,
                roll_number__iexact=roll_number,
            ).exclude(pk=self.student.pk).exists():
                self.add_error(
                    "roll_number",
                    "A student with this roll number already exists in this division.",
                )

        # Validate batch belongs to division
        batch = cleaned_data.get("batch")
        if batch and division:
            if batch.division_id != division.id:
                self.add_error(
                    "batch",
                    "The selected practical batch does not belong to the selected division.",
                )

        return cleaned_data

    def save(self):
        data = self.cleaned_data
        status = data.get("status", self.student.status)
        is_active = status == StudentProfile.Status.ACTIVE

        with transaction.atomic():
            self.user.first_name = data.get("first_name", "")
            self.user.last_name = data.get("last_name", "")
            self.user.email = data["email"]
            self.user.phone = data.get("phone")
            self.user.is_active = is_active
            self.user.save()

            # Preserve existing student code unconditionally
            self.student.student_code = self.student.student_code
            self.student.division = data["division"]
            self.student.batch = data.get("batch")
            self.student.roll_number = data["roll_number"]
            self.student.admission_year = data["admission_year"]
            self.student.status = status
            self.student.save()
            return self.student


# ==============================================================================
# ACADEMIC MANAGEMENT FORMS
# ==============================================================================

class DepartmentForm(forms.ModelForm):
    """
    Form for creating and editing Academic Departments.
    Uses existing Department model (fields: name, code).
    """

    class Meta:
        model = Department
        fields = ["name", "code"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        input_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400"

        self.fields["name"].widget = forms.TextInput(
            attrs={
                "class": input_classes,
                "placeholder": "e.g. Computer Science and Engineering",
            }
        )
        self.fields["code"].widget = forms.TextInput(
            attrs={
                "class": input_classes,
                "placeholder": "e.g. CSE",
            }
        )

    def clean_name(self):
        name = self.cleaned_data.get("name", "").strip()
        if not name:
            raise forms.ValidationError("Department name is required.")
        return name

    def clean_code(self):
        code = self.cleaned_data.get("code", "").strip().upper()
        if not code:
            raise forms.ValidationError("Department code is required.")
        qs = Department.objects.filter(code__iexact=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A department with this code already exists.")
        return code


class ProgramForm(forms.ModelForm):
    """
    Form for creating and editing Academic Programs.
    """

    class Meta:
        model = Program
        fields = ["department", "name", "code", "duration_years"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        input_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400"
        select_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white"

        self.fields["department"].queryset = Department.objects.all().order_by("name")
        self.fields["department"].widget.attrs.update({"class": select_classes})
        self.fields["department"].empty_label = "Select department..."

        self.fields["name"].widget = forms.TextInput(
            attrs={
                "class": input_classes,
                "placeholder": "e.g. Bachelor of Technology in Computer Science",
            }
        )
        self.fields["code"].widget = forms.TextInput(
            attrs={
                "class": input_classes,
                "placeholder": "e.g. BTECH-CS",
            }
        )
        self.fields["duration_years"].widget = forms.NumberInput(
            attrs={
                "class": input_classes,
                "min": 1,
                "max": 10,
                "placeholder": "4",
            }
        )

    def clean_name(self):
        name = self.cleaned_data.get("name", "").strip()
        if not name:
            raise forms.ValidationError("Program name is required.")
        return name

    def clean_code(self):
        from academics.models import Program
        code = self.cleaned_data.get("code", "").strip().upper()
        if not code:
            raise forms.ValidationError("Program code is required.")
        qs = Program.objects.filter(code__iexact=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A program with this code already exists.")
        return code

    def clean_duration_years(self):
        duration = self.cleaned_data.get("duration_years")
        if duration is None or duration < 1 or duration > 10:
            raise forms.ValidationError("Duration in years must be between 1 and 10.")
        return duration


class SemesterForm(forms.ModelForm):
    """
    Form for creating and editing Academic Semesters.
    """

    class Meta:
        model = Semester
        fields = ["program", "number", "academic_year"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        input_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400"
        select_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white"

        self.fields["program"].queryset = Program.objects.select_related("department").all().order_by("name")
        self.fields["program"].widget.attrs.update({"class": select_classes})
        self.fields["program"].empty_label = "Select program..."

        self.fields["number"].widget = forms.NumberInput(
            attrs={
                "class": input_classes,
                "min": 1,
                "max": 20,
                "placeholder": "e.g. 1, 2, 3...",
            }
        )
        self.fields["academic_year"].widget = forms.TextInput(
            attrs={
                "class": input_classes,
                "placeholder": "e.g. 2025-2026",
            }
        )

    def clean_academic_year(self):
        from academics.validators import validate_academic_year
        val = self.cleaned_data.get("academic_year", "").strip()
        try:
            return validate_academic_year(val)
        except forms.ValidationError as e:
            raise e

    def clean(self):
        cleaned_data = super().clean()
        program = cleaned_data.get("program")
        number = cleaned_data.get("number")
        academic_year = cleaned_data.get("academic_year")

        if program and number:
            max_semesters = program.duration_years * 2
            if number > max_semesters:
                self.add_error(
                    "number",
                    f"Semester number ({number}) cannot exceed maximum program semesters ({max_semesters})."
                )

        if program and number and academic_year:
            qs = Semester.objects.filter(
                program=program,
                number=number,
                academic_year__iexact=academic_year.strip()
            )
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    "A semester with this program, number, and academic year already exists."
                )

        return cleaned_data


class DivisionForm(forms.ModelForm):
    """
    Form for creating and editing Class Divisions.
    """

    class Meta:
        model = Division
        fields = ["semester", "name", "capacity"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        input_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400"
        select_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white"

        self.fields["semester"].queryset = Semester.objects.select_related("program").all().order_by("program__name", "number")
        self.fields["semester"].widget.attrs.update({"class": select_classes})
        self.fields["semester"].empty_label = "Select semester..."

        self.fields["name"].widget = forms.TextInput(
            attrs={
                "class": input_classes,
                "placeholder": "e.g. A, B, Div-1",
            }
        )
        self.fields["capacity"].widget = forms.NumberInput(
            attrs={
                "class": input_classes,
                "min": 1,
                "placeholder": "60",
            }
        )

    def clean_name(self):
        name = self.cleaned_data.get("name", "").strip().upper()
        if not name:
            raise forms.ValidationError("Division name is required.")
        return name

    def clean_capacity(self):
        cap = self.cleaned_data.get("capacity")
        if cap is None or cap <= 0:
            raise forms.ValidationError("Capacity must be a positive integer greater than 0.")
        return cap

    def clean(self):
        cleaned_data = super().clean()
        semester = cleaned_data.get("semester")
        name = cleaned_data.get("name")

        if semester and name:
            qs = Division.objects.filter(semester=semester, name__iexact=name)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error("name", "A division with this name already exists in this semester.")

        return cleaned_data


class PracticalBatchForm(forms.ModelForm):
    """
    Form for creating and editing Practical / Lab Batches.
    """

    class Meta:
        model = PracticalBatch
        fields = ["division", "name", "capacity"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        input_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400"
        select_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white"

        self.fields["division"].queryset = Division.objects.select_related("semester", "semester__program").all().order_by("semester__program__name", "name")
        self.fields["division"].widget.attrs.update({"class": select_classes})
        self.fields["division"].empty_label = "Select division..."

        self.fields["name"].widget = forms.TextInput(
            attrs={
                "class": input_classes,
                "placeholder": "e.g. P1, P2, Batch-A",
            }
        )
        self.fields["capacity"].widget = forms.NumberInput(
            attrs={
                "class": input_classes,
                "min": 1,
                "placeholder": "20",
            }
        )

    def clean_name(self):
        name = self.cleaned_data.get("name", "").strip().upper()
        if not name:
            raise forms.ValidationError("Batch name is required.")
        return name

    def clean_capacity(self):
        cap = self.cleaned_data.get("capacity")
        if cap is None or cap <= 0:
            raise forms.ValidationError("Capacity must be a positive integer greater than 0.")
        return cap

    def clean(self):
        from academics.models import PracticalBatch
        cleaned_data = super().clean()
        division = cleaned_data.get("division")
        name = cleaned_data.get("name")

        if division and name:
            qs = PracticalBatch.objects.filter(division=division, name__iexact=name)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error("name", "A batch with this name already exists in this division.")

        return cleaned_data


class SubjectForm(forms.ModelForm):
    """
    Form for creating and editing Curricular Subjects / Courses with multiple delivery components.
    Supports any combination of:
    - Lecture (weekly lectures, lecture session duration)
    - Practical (weekly practicals, practical session duration)
    - Tutorial (tutorial session duration)
    """

    has_lecture = forms.BooleanField(
        required=False,
        initial=True,
        label="Lecture",
    )
    has_practical = forms.BooleanField(
        required=False,
        initial=False,
        label="Practical",
    )
    has_tutorial = forms.BooleanField(
        required=False,
        initial=False,
        label="Tutorial",
    )

    class Meta:
        model = Subject
        fields = [
            "program",
            "name",
            "code",
            "credits",
            "weekly_lectures",
            "weekly_practicals",
            "duration_minutes",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        input_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400"
        select_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white"

        self.fields["program"].queryset = Program.objects.select_related("department").all().order_by("name")
        self.fields["program"].widget.attrs.update({"class": select_classes})
        self.fields["program"].empty_label = "Select program..."

        self.fields["name"].widget = forms.TextInput(
            attrs={
                "class": input_classes,
                "placeholder": "e.g. Java Programming",
            }
        )
        self.fields["code"].widget = forms.TextInput(
            attrs={
                "class": input_classes,
                "placeholder": "e.g. CS201, IT-302",
            }
        )

        self.fields["credits"].widget = forms.NumberInput(
            attrs={
                "class": input_classes,
                "step": "0.5",
                "min": "0",
                "placeholder": "4.0",
            }
        )
        self.fields["weekly_lectures"].widget = forms.NumberInput(
            attrs={
                "class": input_classes,
                "min": "0",
                "placeholder": "4",
            }
        )
        self.fields["weekly_practicals"].widget = forms.NumberInput(
            attrs={
                "class": input_classes,
                "min": "0",
                "placeholder": "2",
            }
        )
        self.fields["duration_minutes"].widget = forms.NumberInput(
            attrs={
                "class": input_classes,
                "min": "1",
                "placeholder": "60",
            }
        )

        # Pre-populate checkboxes if editing existing instance
        if self.instance and self.instance.pk:
            has_lec = (self.instance.weekly_lectures or 0) > 0 or self.instance.type == Subject.Type.LECTURE
            has_prac = (self.instance.weekly_practicals or 0) > 0 or self.instance.type == Subject.Type.PRACTICAL
            has_tut = self.instance.type == Subject.Type.TUTORIAL

            self.fields["has_lecture"].initial = has_lec
            self.fields["has_practical"].initial = has_prac
            self.fields["has_tutorial"].initial = has_tut
        elif not self.is_bound:
            self.fields["has_lecture"].initial = True
            self.fields["has_practical"].initial = False
            self.fields["has_tutorial"].initial = False

    def clean_name(self):
        name = self.cleaned_data.get("name", "").strip()
        if not name:
            raise forms.ValidationError("Subject name is required.")
        return name

    def clean_code(self):
        code = self.cleaned_data.get("code", "").strip().upper()
        if not code:
            raise forms.ValidationError("Subject code is required.")
        qs = Subject.objects.filter(code__iexact=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A subject with this code already exists.")
        return code

    def clean_credits(self):
        credits_val = self.cleaned_data.get("credits")
        if credits_val is None or credits_val < 0:
            raise forms.ValidationError("Credits must be a non-negative number.")
        return credits_val

    def clean(self):
        cleaned_data = super().clean()
        has_lecture = cleaned_data.get("has_lecture", False)
        has_practical = cleaned_data.get("has_practical", False)
        has_tutorial = cleaned_data.get("has_tutorial", False)

        if not (has_lecture or has_practical or has_tutorial):
            raise forms.ValidationError("Please select at least one delivery component (Lecture, Practical, or Tutorial).")

        weekly_lectures = cleaned_data.get("weekly_lectures") or 0
        weekly_practicals = cleaned_data.get("weekly_practicals") or 0
        duration_minutes = cleaned_data.get("duration_minutes")

        # Validate Lecture component requirements
        if has_lecture:
            if weekly_lectures <= 0:
                self.add_error("weekly_lectures", "Weekly lecture sessions must be at least 1 when Lecture component is selected.")
        else:
            cleaned_data["weekly_lectures"] = 0

        # Validate Practical component requirements
        if has_practical:
            if weekly_practicals <= 0:
                self.add_error("weekly_practicals", "Weekly practical sessions must be at least 1 when Practical component is selected.")
        else:
            cleaned_data["weekly_practicals"] = 0

        # Duration validation
        if duration_minutes is None or duration_minutes <= 0:
            self.add_error("duration_minutes", "Session duration must be greater than 0 minutes.")

        # Determine primary model delivery type based on selected components
        if has_lecture:
            cleaned_data["type"] = Subject.Type.LECTURE
        elif has_practical:
            cleaned_data["type"] = Subject.Type.PRACTICAL
        elif has_tutorial:
            cleaned_data["type"] = Subject.Type.TUTORIAL

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.type = self.cleaned_data.get("type", instance.type)
        instance.weekly_lectures = self.cleaned_data.get("weekly_lectures", 0)
        instance.weekly_practicals = self.cleaned_data.get("weekly_practicals", 0)
        if commit:
            instance.save()
        return instance


class TeacherSubjectForm(forms.ModelForm):
    """
    Form for assigning a Curricular Subject to a Teacher Profile.
    """

    class Meta:
        model = TeacherSubject
        fields = ["subject", "priority"]

    def __init__(self, *args, teacher=None, **kwargs):
        self.teacher = teacher or (kwargs.get("instance").teacher if kwargs.get("instance") else None)
        super().__init__(*args, **kwargs)

        select_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white"
        input_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400"

        self.fields["subject"].queryset = Subject.objects.select_related("program", "program__department").all().order_by("code")
        self.fields["subject"].widget.attrs.update({"class": select_classes})
        self.fields["subject"].empty_label = "Select Subject..."

        self.fields["priority"].widget = forms.NumberInput(
            attrs={
                "class": input_classes,
                "min": "1",
                "max": "10",
                "placeholder": "1",
            }
        )

    def clean(self):
        cleaned_data = super().clean()
        subject = cleaned_data.get("subject")
        if self.teacher and subject:
            qs = TeacherSubject.objects.filter(teacher=self.teacher, subject=subject)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error("subject", f"Subject '{subject.code}' is already assigned to this teacher.")
        return cleaned_data


class TeacherAvailabilityForm(forms.ModelForm):
    """
    Form for configuring weekly availability time slots for a teacher.
    """

    class Meta:
        model = TeacherAvailability
        fields = ["day", "start_time", "end_time", "is_available"]

    def __init__(self, *args, teacher=None, **kwargs):
        self.teacher = teacher or (kwargs.get("instance").teacher if kwargs.get("instance") else None)
        super().__init__(*args, **kwargs)

        select_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white"
        input_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white"

        self.fields["day"].widget.attrs.update({"class": select_classes})
        self.fields["start_time"].widget = forms.TimeInput(
            attrs={"class": input_classes, "type": "time"}
        )
        self.fields["end_time"].widget = forms.TimeInput(
            attrs={"class": input_classes, "type": "time"}
        )
        self.fields["is_available"].widget.attrs.update(
            {"class": "h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"}
        )

    def clean(self):
        cleaned_data = super().clean()
        day = cleaned_data.get("day")
        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")

        if start_time and end_time and start_time >= end_time:
            self.add_error("end_time", "End time must be strictly after start time.")

        if self.teacher and day and start_time and end_time:
            qs = TeacherAvailability.objects.filter(
                teacher=self.teacher,
                day=day,
                start_time__lt=end_time,
                end_time__gt=start_time,
            )
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error("start_time", "Time slot overlaps with another scheduled slot on this day.")

        return cleaned_data


class TeacherLeaveForm(forms.ModelForm):
    """
    Form for submitting and managing teacher leave records.
    """

    class Meta:
        model = TeacherLeave
        fields = ["start_date", "end_date", "reason", "status"]

    def __init__(self, *args, teacher=None, is_staff_manager=True, **kwargs):
        self.teacher = teacher or (kwargs.get("instance").teacher if kwargs.get("instance") else None)
        super().__init__(*args, **kwargs)

        select_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white"
        input_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white"
        textarea_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400"

        self.fields["start_date"].widget = forms.DateInput(
            attrs={"class": input_classes, "type": "date"}
        )
        self.fields["end_date"].widget = forms.DateInput(
            attrs={"class": input_classes, "type": "date"}
        )
        self.fields["reason"].widget = forms.Textarea(
            attrs={"class": textarea_classes, "rows": 3, "placeholder": "Specify reason for leave..."}
        )
        self.fields["status"].widget.attrs.update({"class": select_classes})

        if not is_staff_manager:
            self.fields["status"].widget = forms.HiddenInput()

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        reason = cleaned_data.get("reason", "").strip()

        if not reason:
            self.add_error("reason", "Reason for leave cannot be blank.")

        if start_date and end_date:
            if start_date > end_date:
                self.add_error("end_date", "End date must be greater than or equal to start date.")

            if self.teacher:
                qs = TeacherLeave.objects.filter(
                    teacher=self.teacher,
                    start_date__lte=end_date,
                    end_date__gte=start_date,
                ).exclude(status=TeacherLeave.Status.REJECTED)
                if self.instance and self.instance.pk:
                    qs = qs.exclude(pk=self.instance.pk)
                if qs.exists():
                    self.add_error("start_date", "A leave record already overlaps with the selected date range.")

        return cleaned_data


class ClassroomForm(forms.ModelForm):
    """
    Form for creating and editing physical classroom resources.
    """

    class Meta:
        model = Classroom
        fields = ["building", "room_number", "floor", "capacity", "status"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        input_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400"
        select_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white"

        self.fields["building"].widget = forms.TextInput(
            attrs={"class": input_classes, "placeholder": "e.g. Main Academic Block, Block A"}
        )
        self.fields["room_number"].widget = forms.TextInput(
            attrs={"class": input_classes, "placeholder": "e.g. 101, LH-1"}
        )
        self.fields["floor"].widget = forms.NumberInput(
            attrs={"class": input_classes, "placeholder": "0 (Ground floor), 1, 2"}
        )
        self.fields["capacity"].widget = forms.NumberInput(
            attrs={"class": input_classes, "min": "1", "placeholder": "60"}
        )
        self.fields["status"].widget.attrs.update({"class": select_classes})

    def clean(self):
        cleaned_data = super().clean()
        building = (cleaned_data.get("building") or "").strip()
        room_number = (cleaned_data.get("room_number") or "").strip()

        if building and room_number:
            qs = Classroom.objects.filter(building__iexact=building, room_number__iexact=room_number)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error("room_number", f"Classroom '{room_number}' in building '{building}' already exists.")

        return cleaned_data


class LaboratoryForm(forms.ModelForm):
    """
    Form for creating and editing laboratory resources.
    """

    class Meta:
        model = Laboratory
        fields = ["building", "lab_number", "name", "floor", "capacity", "status"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        input_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400"
        select_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white"

        self.fields["building"].widget = forms.TextInput(
            attrs={"class": input_classes, "placeholder": "e.g. Engineering Block, Block B"}
        )
        self.fields["lab_number"].widget = forms.TextInput(
            attrs={"class": input_classes, "placeholder": "e.g. LAB-101, L1"}
        )
        self.fields["name"].widget = forms.TextInput(
            attrs={"class": input_classes, "placeholder": "e.g. Advanced Computing Lab, Electronics Lab"}
        )
        self.fields["floor"].widget = forms.NumberInput(
            attrs={"class": input_classes, "placeholder": "0, 1, 2"}
        )
        self.fields["capacity"].widget = forms.NumberInput(
            attrs={"class": input_classes, "min": "1", "placeholder": "30"}
        )
        self.fields["status"].widget.attrs.update({"class": select_classes})

    def clean(self):
        cleaned_data = super().clean()
        building = (cleaned_data.get("building") or "").strip()
        lab_number = (cleaned_data.get("lab_number") or "").strip()

        if building and lab_number:
            qs = Laboratory.objects.filter(building__iexact=building, lab_number__iexact=lab_number)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error("lab_number", f"Laboratory '{lab_number}' in building '{building}' already exists.")

        return cleaned_data


class TimetableForm(forms.ModelForm):
    """
    Form for creating a new Timetable container for a Semester and Academic Year.
    Automates next version numbering and sets status to DRAFT.
    """

    class Meta:
        model = Timetable
        fields = ["semester", "academic_year", "status"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        select_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white"
        input_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400"

        self.fields["semester"].widget.attrs.update({"class": select_classes})
        self.fields["semester"].queryset = Semester.objects.select_related("program").all().order_by("program__name", "number")
        self.fields["academic_year"].widget = forms.TextInput(
            attrs={"class": input_classes, "placeholder": "e.g. 2025-2026"}
        )
        self.fields["status"].widget.attrs.update({"class": select_classes})
        if not self.instance.pk:
            self.fields["status"].initial = Timetable.Status.DRAFT

    def clean_academic_year(self):
        year = self.cleaned_data.get("academic_year", "").strip()
        from academics.validators import validate_academic_year
        return validate_academic_year(year)


class TimetableGenerateForm(forms.Form):
    """
    Form for initiating AI Timetable generation with pre-generation configuration:
    - Academic context (Semester, Division)
    - Schedule settings (Working days, Daily start/end times, Slot duration, Lunch break)
    - Optimization & constraint preferences (Practical periods, consecutive limits, gaps, distribution)
    - Natural language instructions
    """

    DAY_CHOICES = [
        ("MONDAY", "Monday"),
        ("TUESDAY", "Tuesday"),
        ("WEDNESDAY", "Wednesday"),
        ("THURSDAY", "Thursday"),
        ("FRIDAY", "Friday"),
        ("SATURDAY", "Saturday"),
    ]

    PRACTICAL_PERIOD_CHOICES = [
        ("ANY", "No Preference / Any Time"),
        ("AFTERNOON", "Prefer Afternoon (12:00 - 16:00)"),
        ("MORNING", "Prefer Morning (09:00 - 12:00)"),
    ]

    semester = forms.ModelChoiceField(
        queryset=Semester.objects.select_related("program").all().order_by("program__name", "number"),
        empty_label="Select Semester",
        widget=forms.Select(
            attrs={"class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white"}
        ),
    )
    academic_year = forms.CharField(
        max_length=9,
        widget=forms.TextInput(
            attrs={"class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400", "placeholder": "e.g. 2025-2026"}
        ),
    )
    division = forms.ModelChoiceField(
        queryset=Division.objects.select_related("semester").all(),
        required=False,
        empty_label="All Divisions in Semester",
        widget=forms.Select(
            attrs={"class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white"}
        ),
    )

    # Basic Schedule Settings
    working_days = forms.MultipleChoiceField(
        choices=DAY_CHOICES,
        initial=["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"],
        widget=forms.CheckboxSelectMultiple(attrs={"class": "rounded text-indigo-600 focus:ring-indigo-500"}),
        required=True,
    )
    daily_start_time = forms.CharField(
        initial="09:00",
        widget=forms.TextInput(
            attrs={"class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white", "placeholder": "09:00"}
        ),
    )
    daily_end_time = forms.CharField(
        initial="17:00",
        widget=forms.TextInput(
            attrs={"class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white", "placeholder": "17:00"}
        ),
    )
    slot_duration_minutes = forms.IntegerField(
        initial=60,
        min_value=30,
        max_value=180,
        widget=forms.NumberInput(
            attrs={"class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white", "placeholder": "60"}
        ),
    )
    lunch_break_start = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white", "placeholder": "e.g. 13:00"}
        ),
    )
    lunch_break_end = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white", "placeholder": "e.g. 14:00"}
        ),
    )

    # Preferences & Optimization toggles
    prefer_practicals_period = forms.ChoiceField(
        choices=PRACTICAL_PERIOD_CHOICES,
        initial="AFTERNOON",
        widget=forms.Select(
            attrs={"class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white"}
        ),
        required=False,
    )
    avoid_teacher_consecutive = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"}),
    )
    avoid_division_gaps = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"}),
    )
    subject_distribution = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"}),
    )

    # Natural Language Requirements
    natural_language_requirements = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white placeholder-slate-400 font-mono text-xs",
                "rows": 3,
                "placeholder": "e.g. Keep practical sessions mostly in the afternoon and avoid more than 2 consecutive classes for a teacher.",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If semester is specified in bound or initial data, filter division choices
        semester_id = None
        if self.is_bound:
            semester_id = self.data.get("semester")
        elif "semester" in self.initial:
            val = self.initial.get("semester")
            semester_id = getattr(val, "id", val)

        if semester_id:
            self.fields["division"].queryset = Division.objects.filter(semester_id=semester_id)

    def clean_academic_year(self):
        year = self.cleaned_data.get("academic_year", "").strip()
        from academics.validators import validate_academic_year
        return validate_academic_year(year)

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("daily_start_time", "").strip()
        end = cleaned_data.get("daily_end_time", "").strip()
        if start and end and start >= end:
            self.add_error("daily_end_time", "Daily end time must be after start time.")

        l_start = cleaned_data.get("lunch_break_start", "").strip()
        l_end = cleaned_data.get("lunch_break_end", "").strip()
        if (l_start and not l_end) or (l_end and not l_start):
            self.add_error("lunch_break_end", "Both lunch break start and end times must be provided.")
        elif l_start and l_end and l_start >= l_end:
            self.add_error("lunch_break_end", "Lunch break end time must be after start time.")

        return cleaned_data


class TimetableSlotForm(forms.ModelForm):
    """
    Form for creating and editing individual TimetableSlot instances within a Timetable.
    Enforces academic context scoping and resource constraints.
    """

    class Meta:
        model = TimetableSlot
        fields = [
            "division",
            "batch",
            "subject",
            "teacher",
            "classroom",
            "laboratory",
            "day",
            "start_time",
            "end_time",
            "session_type",
            "status",
        ]

    def __init__(self, *args, timetable=None, **kwargs):
        self.timetable = timetable or (kwargs.get("instance").timetable if kwargs.get("instance") else None)
        super().__init__(*args, **kwargs)

        select_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white"
        input_classes = "w-full px-3.5 py-2.5 text-sm text-slate-900 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-600 outline-none transition duration-150 bg-white"

        for field_name in ["division", "batch", "subject", "teacher", "classroom", "laboratory", "day", "session_type", "status"]:
            if field_name in self.fields:
                self.fields[field_name].widget.attrs.update({"class": select_classes})

        self.fields["start_time"].widget = forms.TimeInput(
            attrs={"class": input_classes, "type": "time"}
        )
        self.fields["end_time"].widget = forms.TimeInput(
            attrs={"class": input_classes, "type": "time"}
        )

        self.fields["batch"].required = False
        self.fields["classroom"].required = False
        self.fields["laboratory"].required = False

        if self.timetable:
            # Scope division to timetable semester
            self.fields["division"].queryset = Division.objects.filter(semester=self.timetable.semester).order_by("name")
            # Scope batches
            self.fields["batch"].queryset = PracticalBatch.objects.filter(division__semester=self.timetable.semester).select_related("division").order_by("division__name", "name")
            # Scope subjects to program
            self.fields["subject"].queryset = Subject.objects.filter(program=self.timetable.semester.program).order_by("name")
        else:
            self.fields["division"].queryset = Division.objects.select_related("semester").all()
            self.fields["batch"].queryset = PracticalBatch.objects.select_related("division").all()
            self.fields["subject"].queryset = Subject.objects.select_related("program").all()

        self.fields["teacher"].queryset = TeacherProfile.objects.select_related("user", "department").filter(user__is_active=True).order_by("user__first_name", "user__last_name")
        self.fields["classroom"].queryset = Classroom.objects.filter(status=Classroom.Status.AVAILABLE).order_by("building", "room_number")
        self.fields["laboratory"].queryset = Laboratory.objects.filter(status=Laboratory.Status.AVAILABLE).order_by("building", "lab_number")

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")
        session_type = cleaned_data.get("session_type")
        classroom = cleaned_data.get("classroom")
        laboratory = cleaned_data.get("laboratory")
        division = cleaned_data.get("division")
        batch = cleaned_data.get("batch")

        if start_time and end_time and start_time >= end_time:
            self.add_error("end_time", "End time must be strictly after start time.")

        if self.timetable and division and division.semester_id != self.timetable.semester_id:
            self.add_error("division", "Selected division does not belong to the timetable's semester.")

        if batch and division and batch.division_id != division.id:
            self.add_error("batch", "Selected batch does not belong to the selected division.")

        if session_type == TimetableSlot.SessionType.PRACTICAL:
            if not laboratory and not classroom:
                self.add_error("laboratory", "Practical sessions require an assigned laboratory.")
        elif session_type in (TimetableSlot.SessionType.LECTURE, TimetableSlot.SessionType.TUTORIAL):
            if not classroom and not laboratory:
                self.add_error("classroom", "Lecture and tutorial sessions require an assigned classroom.")

        return cleaned_data







