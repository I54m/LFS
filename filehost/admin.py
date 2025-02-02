from django.contrib import admin, messages
from django.contrib.admin import actions
from django.utils import timezone
from .models import UploadedFile
from filehost import tasks

class UploadedFileAdmin(admin.ModelAdmin):
    list_display = ("slug", "uploaded_at", "expiration_date", "state", "upload_type", "file_type", "mime_type", "has_thumbnail_image", "persistent", "featured", "uploader", "access")
    readonly_fields = ("file", "slug", "uploaded_at", "state", "upload_type", "file_type", "mime_type", "thumbnail")
    ordering = ("-uploaded_at", "slug",)
    list_filter = ['upload_type', 'state', 'access', 'persistent', 'featured', 'file_type', 'mime_type']
    search_fields = ['slug']

    def has_delete_permission(self, request, obj=None, *args, **kwargs):
        if obj is not None and obj.persistent:
            return False
        else:
            return True
        


    ################################################
    #               Bulk Actions                   #
    ################################################
    
    def delete_selected(self, request, queryset):
        if queryset.filter(persistent=True).count() > 0:
            messages.error(request, (
                    "Your selection included files marked as persistent, de-select them and try again! "
                    "if you wish to delete them too, unmark them as persistent and try again."
                ))
            return

        return actions.delete_selected(self, request, queryset)

    def expire_today(self, request, queryset):
        if queryset.filter(persistent=True).count() > 0:
            messages.error(request, (
                    "Your selection included files marked as persistent, de-select them and try again! "
                    "if you wish to expire them too, unmark them as persistent and try again."
                ))
            return
        
        else:
            for uploaded_file in queryset:
                uploaded_file.expiration_date = timezone.localdate()
                uploaded_file.save()
            messages.success(request, (
                    "The selected files have been set to expire today! "
                    "They will be expired and moved once the task runs."
                ))
            return
            
    def take_ownership(self, request, queryset):
        for uploaded_file in queryset:
            uploaded_file.uploader = request.user
            uploaded_file.save()
        messages.success(request, (
                "You are now the uploader/owner of the selected files!"
            ))
    
    def archive_selected(self, request, queryset):
        if queryset.filter(persistent=True).count() > 0:
            messages.error(request, (
                    "Your selection included files marked as persistent, de-select them and try again! "
                    "if you wish to archive them too, unmark them as persistent and try again."
                ))
            return
        
        elif queryset.filter(state=UploadedFile.State.ARCHIVED).count() > 0:
            messages.error(request, (
                    "Your selection included files that are already archived, de-select them and try again! "
                ))
            return
        
        else:
            
            slugs = list(uf.slug for uf in queryset)            
            tasks.archive_files.delay(slugs)
            messages.success(request, (
                    "The selected files are now being archived! "
                    "This may take some time so please be patient..."
                ))
            return
    
    def localise_selected(self, request, queryset):
        if queryset.filter(state=UploadedFile.State.LOCAL).count() > 0:
            messages.error(request, (
                    "Your selection included files that are already local, de-select them and try again! "
                ))
            return
        
        else:
            slugs = list(uf.slug for uf in queryset)
            tasks.localise_files.delay(slugs)
            messages.success(request, (
                    "The selected files are now being localised! "
                    "This may take some time so please be patient..."
                ))
            return
    

    def private_selected(self, request, queryset):
        for uf in queryset:
            uf.access = UploadedFile.Access.PRIVATE
            uf.save()
        messages.success(request, (
                    "The selected files are now set to private! "
                ))
        
    def members_only_selected(self, request, queryset):
        for uf in queryset:
            uf.access = UploadedFile.Access.MEMBERS_ONLY
            uf.save()
        messages.success(request, (
                    "The selected files are now set to members only! "
                ))
    
    def public_selected(self, request, queryset):
        for uf in queryset:
            uf.access = UploadedFile.Access.PUBLIC
            uf.save()
        messages.success(request, (
                    "The selected files are now set to public! "
                ))

    actions = [delete_selected, expire_today, take_ownership, archive_selected, localise_selected, private_selected, members_only_selected, public_selected]


admin.site.register(UploadedFile, UploadedFileAdmin)