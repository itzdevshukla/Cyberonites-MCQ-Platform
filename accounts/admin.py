"""
Register Participant model with Django admin (fallback).
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Participant


@admin.register(Participant)
class ParticipantAdmin(UserAdmin):
    list_display = ('email', 'full_name', 'college', 'is_staff', 'is_active')
    list_filter = ('is_staff', 'is_active', 'college')
    search_fields = ('email', 'full_name', 'college')
    ordering = ('email',)

    fieldsets = UserAdmin.fieldsets + (
        ('Participant Info', {'fields': ('full_name', 'college', 'session_key')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Participant Info', {'fields': ('full_name', 'email', 'college')}),
    )
