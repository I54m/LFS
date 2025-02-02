from django.core.files.base import File
from django.core.files.storage import FileSystemStorage
from filehost.models import UploadedFile
from django.conf import settings
import os
from urllib.parse import urljoin




class LifecycleFileStorage(FileSystemStorage):
    
    
    # def __init__(self, option=None):
    #     if not option:
    #         option = settings.CUSTOM_STORAGE_OPTIONS
        

    def url(self, name):
        url = super().url(name) # API/IMAGE/THUMBNAIL/gZ8tMsnP.png
        slug = os.path.basename(url).split('.')[0]
        domain = settings.ALLOWED_HOSTS[0]
        uploaded_file = UploadedFile.objects.get(slug=slug)

        if uploaded_file.state == UploadedFile.State.MOVING or uploaded_file.state == UploadedFile.State.ARCHIVED:
            return f"https://{domain}/{slug}/thmb/" # We are unable to provide the raw file anyway so link to the thumbnail
        
        if "THUMBNAIL" in url:
            return f"https://{domain}/{slug}/thmb/"
        else:
            return f"https://{domain}/{slug}/raw/"

    def open(self, name: str, mode: str = ...) -> File:
        return super().open(name, mode)
    
    def save(self, name: str | None, content, max_length: int | None = ...) -> str:
        return super().save(name, content, max_length)
    
    def delete(self, name: str) -> None:
        return super().delete(name)
    
    def exists(self, name: str) -> bool:
        return super().exists(name)
    
    def listdir(self, path: str) -> tuple[list[str], list[str]]:
        return super().listdir(path)
