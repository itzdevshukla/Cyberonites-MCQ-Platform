from django.contrib import admin
from .models import ViolationLog, AuditLog


@admin.register(ViolationLog)
class ViolationLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'participant', 'quiz', 'violation_type', 'ip_address')
    list_filter = ('violation_type', 'quiz', 'created_at')
    search_fields = ('participant__email', 'participant__full_name', 'details')
    readonly_fields = [f.name for f in ViolationLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor_email', 'action', 'target_model', 'target_id', 'ip_address')
    list_filter = ('action', 'target_model', 'created_at')
    search_fields = ('actor_email', 'action', 'target_model', 'target_id', 'ip_address')
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
