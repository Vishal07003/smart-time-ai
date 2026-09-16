from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import StudentProfile, TeacherProfile
from .permissions import IsStaffRole, IsStudentRole, IsTeacherRole
from .profile_serializers import (
    StudentMeUpdateSerializer,
    StudentProfileCreateSerializer,
    StudentProfileSerializer,
    StudentProfileUpdateSerializer,
    TeacherMeUpdateSerializer,
    TeacherProfileCreateSerializer,
    TeacherProfileSerializer,
    TeacherProfileUpdateSerializer,
)


class TeacherListCreateView(APIView):
    """
    GET  /api/v1/teachers/     - List all teacher profiles (STAFF only)
    POST /api/v1/teachers/     - Create a new Teacher user & profile (STAFF only)
    """

    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        teachers = TeacherProfile.objects.select_related("user", "department").all()
        serializer = TeacherProfileSerializer(teachers, many=True)
        return Response(
            {
                "success": True,
                "count": teachers.count(),
                "teachers": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = TeacherProfileCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        teacher = serializer.save()
        return Response(
            {
                "success": True,
                "message": "Teacher created successfully.",
                "teacher": TeacherProfileSerializer(teacher).data,
            },
            status=status.HTTP_201_CREATED,
        )


class TeacherDetailView(APIView):
    """
    GET    /api/v1/teachers/{id}/ - Retrieve teacher profile (STAFF only)
    PUT    /api/v1/teachers/{id}/ - Full update teacher profile (STAFF only)
    PATCH  /api/v1/teachers/{id}/ - Partial update teacher profile (STAFF only)
    DELETE /api/v1/teachers/{id}/ - Delete teacher profile & user (STAFF only)
    """

    permission_classes = [IsAuthenticated, IsStaffRole]

    def get_object(self, pk):
        return get_object_or_404(
            TeacherProfile.objects.select_related("user", "department"),
            pk=pk,
        )

    def get(self, request, pk):
        teacher = self.get_object(pk)
        serializer = TeacherProfileSerializer(teacher)
        return Response(
            {
                "success": True,
                "teacher": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        teacher = self.get_object(pk)
        serializer = TeacherProfileUpdateSerializer(
            teacher,
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)
        updated_teacher = serializer.save()
        return Response(
            {
                "success": True,
                "message": "Teacher updated successfully.",
                "teacher": TeacherProfileSerializer(updated_teacher).data,
            },
            status=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        teacher = self.get_object(pk)
        serializer = TeacherProfileUpdateSerializer(
            teacher,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        updated_teacher = serializer.save()
        return Response(
            {
                "success": True,
                "message": "Teacher updated successfully.",
                "teacher": TeacherProfileSerializer(updated_teacher).data,
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        teacher = self.get_object(pk)
        user = teacher.user
        user.delete()  # Cascade deletes teacher_profile as well
        return Response(
            {
                "success": True,
                "message": "Teacher deleted successfully.",
            },
            status=status.HTTP_200_OK,
        )


class TeacherMeView(APIView):
    """
    GET   /api/v1/teachers/me/ - Retrieve authenticated teacher's own profile
    PATCH /api/v1/teachers/me/ - Update authenticated teacher's personal details
    """

    permission_classes = [IsAuthenticated, IsTeacherRole]

    def get_object(self, request):
        return get_object_or_404(
            TeacherProfile.objects.select_related("user", "department"),
            user=request.user,
        )

    def get(self, request):
        teacher = self.get_object(request)
        serializer = TeacherProfileSerializer(teacher)
        return Response(
            {
                "success": True,
                "teacher": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def patch(self, request):
        teacher = self.get_object(request)
        serializer = TeacherMeUpdateSerializer(
            teacher,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {
                "success": True,
                "message": "Personal profile updated successfully.",
                "teacher": TeacherProfileSerializer(teacher).data,
            },
            status=status.HTTP_200_OK,
        )


# =========================================================================
# STUDENT PROFILE VIEWS
# =========================================================================


class StudentListCreateView(APIView):
    """
    GET  /api/v1/students/     - List all student profiles (STAFF only)
    POST /api/v1/students/     - Create a new Student user & profile (STAFF only)
    """

    permission_classes = [IsAuthenticated, IsStaffRole]

    def get(self, request):
        students = StudentProfile.objects.select_related(
            "user", "division", "batch"
        ).all()
        serializer = StudentProfileSerializer(students, many=True)
        return Response(
            {
                "success": True,
                "count": students.count(),
                "students": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = StudentProfileCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        student = serializer.save()
        return Response(
            {
                "success": True,
                "message": "Student created successfully.",
                "student": StudentProfileSerializer(student).data,
            },
            status=status.HTTP_201_CREATED,
        )


class StudentDetailView(APIView):
    """
    GET    /api/v1/students/{id}/ - Retrieve student profile (STAFF only)
    PUT    /api/v1/students/{id}/ - Full update student profile (STAFF only)
    PATCH  /api/v1/students/{id}/ - Partial update student profile (STAFF only)
    DELETE /api/v1/students/{id}/ - Delete student profile & user (STAFF only)
    """

    permission_classes = [IsAuthenticated, IsStaffRole]

    def get_object(self, pk):
        return get_object_or_404(
            StudentProfile.objects.select_related("user", "division", "batch"),
            pk=pk,
        )

    def get(self, request, pk):
        student = self.get_object(pk)
        serializer = StudentProfileSerializer(student)
        return Response(
            {
                "success": True,
                "student": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        student = self.get_object(pk)
        serializer = StudentProfileUpdateSerializer(
            student,
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)
        updated_student = serializer.save()
        return Response(
            {
                "success": True,
                "message": "Student updated successfully.",
                "student": StudentProfileSerializer(updated_student).data,
            },
            status=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        student = self.get_object(pk)
        serializer = StudentProfileUpdateSerializer(
            student,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        updated_student = serializer.save()
        return Response(
            {
                "success": True,
                "message": "Student updated successfully.",
                "student": StudentProfileSerializer(updated_student).data,
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        student = self.get_object(pk)
        user = student.user
        user.delete()  # Cascade deletes student_profile as well
        return Response(
            {
                "success": True,
                "message": "Student deleted successfully.",
            },
            status=status.HTTP_200_OK,
        )


class StudentMeView(APIView):
    """
    GET   /api/v1/students/me/ - Retrieve authenticated student's own profile
    PATCH /api/v1/students/me/ - Update authenticated student's personal details
    """

    permission_classes = [IsAuthenticated, IsStudentRole]

    def get_object(self, request):
        return get_object_or_404(
            StudentProfile.objects.select_related("user", "division", "batch"),
            user=request.user,
        )

    def get(self, request):
        student = self.get_object(request)
        serializer = StudentProfileSerializer(student)
        return Response(
            {
                "success": True,
                "student": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def patch(self, request):
        student = self.get_object(request)
        serializer = StudentMeUpdateSerializer(
            student,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {
                "success": True,
                "message": "Personal profile updated successfully.",
                "student": StudentProfileSerializer(student).data,
            },
            status=status.HTTP_200_OK,
        )
