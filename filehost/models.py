from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver
from django.db import models
from django.utils import timezone
from django.conf import settings
from django.contrib import admin
from mimetypes import guess_type
from i54m_apiuser.models import ApiUser
import os, string, random





SLUG_LENGTH = 8

def random_slug():
    randomstring = ''.join(random.choices(string.ascii_letters + string.digits, k=SLUG_LENGTH))
    if (UploadedFile.objects.filter(slug=randomstring).count() > 0):
        # In the unlikely event that the slug is already taken we regenerate a new slug until we have one that is not taken
        randomstring = random_slug()
    return randomstring

def get_mime_type(filename):
    try:
        mime_type, encoding = guess_type(filename)
        if mime_type == "application/octet-stream":
            return "application/octet-stream", UploadedFile.FileType.FILE
        upper_type = mime_type.split('/')[0].upper()
        return mime_type, upper_type
    except:
        return "application/octet-stream", UploadedFile.FileType.FILE

def file_path(self, filename):
    self.uploaded_at = timezone.now()
    ext = filename.split('.')[-1]
    if ext == 'gz':
        ext = 'tar.gz'
    filename = f"{self.slug}.{ext}"
    path = os.path.join(self.upload_type, self.file_type, filename)
    self.file_path = path
    return path

class UploadedFile(models.Model):
    class State():
        LOCAL = "LOCAL"
        ARCHIVED = "ARCHIVED"
        MOVING = "MOVING"
        CHOICES = (
         (LOCAL, "Local"),
         (ARCHIVED, "Archived"),
        )
    class UploadType():
        MANUAL = "MANUAL"
        API = "API"
        EMAIL_ATTACHMENT = "EMAIL_ATTACHMENT"

        TYPES = [MANUAL, API, EMAIL_ATTACHMENT]

        CHOICES = (
         (MANUAL, "Manual"),
         (API, "Api"),
         (EMAIL_ATTACHMENT, "Email Attachment")
        )
    class FileType():

        FILE = 'FILE' #default if mime type is not a supported file type
        IMAGE = 'IMAGE'
        AUDIO = 'AUDIO'
        VIDEO = 'VIDEO'
        TEXT = 'TEXT'
        FONT = 'FONT'
        MODEL = 'MODEL'
        APPLICATION = 'APPLICATION'

        # RAW_VIEWING = [IMAGE, TEXT, AUDIO, VIDEO]

        SUPPORTED_ARCHIVE_MIMETYPES = [
            'application/x-compressed',	
            'application/x-zip-compressed',	
            'application/zip',
            'multipart/x-zip',
            'application/x-tar',
            'application/x-gzip',
            'application/x-gtar',
            'application/x-tgz',
        ]

        TYPES = [FILE, IMAGE, AUDIO, VIDEO, TEXT, FONT, MODEL, APPLICATION]

        CHOICES = (
            (FILE, "File"),
            (IMAGE, "Image"),
            (AUDIO, "Audio"),
            (VIDEO, "Video"),
            (TEXT, "Text"),
            (FONT, "Font"),
            (MODEL, "Model"),
            (APPLICATION, "Application")
        )
    class Access():
        PUBLIC = "PUBLIC"
        MEMBERS_ONLY = "MEMBERS_ONLY"
        PRIVATE = "PRIVATE"

        CHOICES = (
            (PUBLIC, "Public"),
            (MEMBERS_ONLY, "Members Only"),
            (PRIVATE, "Private"),
        )


    slug = models.SlugField(primary_key=True, unique=True, null=False, max_length=8, default=random_slug)
    file = models.FileField(null=True, upload_to=file_path)
    file_path = models.CharField(null=False, editable=False, max_length=64, default="/MANUAL/FILE/UNKNOWN.TXT")
    uploaded_at = models.DateTimeField(null=True)
    expiration_date = models.DateField()
    state = models.CharField(max_length=16, choices=State.CHOICES, default=State.LOCAL)
    upload_type = models.CharField(max_length=16, choices=UploadType.CHOICES, default=UploadType.MANUAL)
    file_type = models.CharField(max_length=16, choices=FileType.CHOICES, default=FileType.FILE)
    persistent = models.BooleanField(default=False)
    mime_type = models.CharField(max_length=128, default="UNKNOWN")
    # Resized image thumbnail for images. This does not get archived and is presented while de-archiving file. This is also used in the oembed integration
    thumbnail = models.ImageField(null=True)
    thumbnail_path = models.CharField(null=True, editable=False, max_length=64)
    uploader = models.ForeignKey(ApiUser, null=True, on_delete=models.SET_NULL)
    # Whether to feature this file on the filehost homepage
    featured = models.BooleanField(default=True)
    access = models.CharField(max_length=16, choices=Access.CHOICES, default=Access.PUBLIC) 

    @property
    def file_or_thumb(self):
        '''
            Method to fetch the thumbnail file when the full version cannnot be fetched
        '''
        if (self.state == UploadedFile.State.ARCHIVED or self.state == UploadedFile.State.MOVING) and self.has_thumbnail:
            return self.thumbnail
        else:
            return self.file

    @property
    def svg_preview(self):
        filename = os.path.basename(self.file_path)
        return self.generate_basic_svg_preview(filename)

    @property
    def has_thumbnail(self) -> bool:
        if self.thumbnail:
            if os.path.isfile(self.thumbnail.path):
                return True
        return False

    @admin.display(
			boolean=True,
			description='Thumbnail Image?',
	)
    def has_thumbnail_image(self):
        return self.has_thumbnail

    def set_expiration(self, days=0, weeks=0, months=0, years=0):
        if years > 0:
            days = days + (years * 364)
        if months > 0:
            days = days + (months * 30)

        # prevent setting negative dates
        if days < 0: 
            days = 0
        if weeks < 0:
            weeks = 0
    
        self.expiration_date = timezone.localdate() + timezone.timedelta(days=days, weeks=weeks)
        self.save()
                 
    def set_persistent(self):
        self.persistent = True
        self.save()

    def set_moving(self):
        if self.persistent:
           return ValueError("Error: trying to move a persistent file! This defeats the purpose of persistent files!")
        self.state = UploadedFile.State.MOVING
        self.save()

    def set_archived(self, days=0, weeks=0, months=0, years=0):
        if self.persistent:
           return ValueError("Error: trying to archive a persistent file! This defeats the purpose of persistent files!")
        self.state = UploadedFile.State.ARCHIVED
        self.set_expiration(days, weeks, months, years)
        self.save()

    def can_be_managed_by(self, user: ApiUser):
        if self.uploader is None or user is None: return False
        if not user.is_authenticated: return False
        if user.is_superuser: return True
        return self.uploader == user

    def __str__(self):
        return self.slug
    
    def generate_basic_svg_preview(self, filename):
        ext = filename.split('.')[-1]
        if ext == 'gz':
            ext = 'tar.gz'
        # Make sure the mime type is split every 32 charcters to prevent text getting too crammed
        mimetype = self.mime_type
        mimetype_line_1 = " "
        mimetype_line_2 = " "
        mimetype_line_3 = " "
        if len(mimetype) > 32:
            n = 32
            out = [(string[i:i+n]) for i in range(0, len(string), n)]
            if out[0]:
                mimetype_line_1 = out[0]
            if out[1]:
                mimetype_line_2 = out[1]
            if out[2]:
                mimetype_line_3 = out[2]

        else:
            mimetype_line_1 = mimetype
        # put varibles into the standard svg thumbnail
        return f"""<svg id="preview" viewBox="0 0 512 512" width="100%" height="256px" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" version="1.1">
                    <rect x="0" y="0" width="512" height="512" fill="#343434"></rect>
                    
                    <text style="alignment-baseline: middle; text-anchor:middle;" x="256" y="64" fill="#eeeeee" font-size="4em" dy="0">
                        <tspan x="256" dy="1.2em">{filename}</tspan>
                        <tspan x="256" dy="1.2em">{ext}</tspan>
                        <tspan textLength="416" lengthAdjust="spacingAndGlyphs" x="256" dy="1.2em">{mimetype_line_1}</tspan>
                        <tspan textLength="416" lengthAdjust="spacingAndGlyphs" x="256" dy="1.2em">{mimetype_line_2}</tspan>
                        <tspan textLength="416" lengthAdjust="spacingAndGlyphs" x="256" dy="1.2em">{mimetype_line_3}</tspan>

                    </text>

                </svg>"""

    


@receiver(pre_save, sender=UploadedFile)
def pre_save_hook(instance: UploadedFile, *args, **kwargs):
    # Set the mime_type, this only needs to be done when the file is first created (mime type is not set)
    # but also needs to be done before actually saving so that the path where the file is saved reflects the file type
    if instance.state == UploadedFile.State.LOCAL and instance.mime_type == "UNKNOWN":
        instance.mime_type, upper_type = get_mime_type(instance.file.name)
        if upper_type not in UploadedFile.FileType.TYPES:
            instance.file_type = UploadedFile.FileType.FILE
        else:
            instance.file_type = upper_type
    
    # Ensure that files that are not publically accessible do not get featured on the homepage
    if not instance.access == UploadedFile.Access.PUBLIC:
        instance.featured = False


@receiver(post_save, sender=UploadedFile)
def post_save_hook(instance: UploadedFile, created, *args, **kwargs):
    # If the file has just been created we will generate a thumbnail and setup the thumbnail_path property
    if created: 
        from .tasks import create_thumbnail # import moved into function due to circular import
        # If we are in a test env we will not run thumbnail creation async as tests need to this to be done before they can verify it's creation
        if settings.TEST_ENV:
            create_thumbnail(instance.slug)
        else:
            create_thumbnail.delay(instance.slug)

        


@receiver(post_delete, sender=UploadedFile)
def post_delete_hook(instance: UploadedFile, *args, **kwargs):

    # Delete Local file
    if instance.state == UploadedFile.State.LOCAL and instance.file and os.path.isfile(instance.file.path):
        os.remove(instance.file.path)

    # Delete Archived file
    elif instance.state == UploadedFile.State.ARCHIVED:
        from .tasks import delete_archived_file # import moved into function due to circular import
        delete_archived_file.delay(instance.slug) 
        
    # Delete Locally saved Thumbnail if it exists
    if instance.thumbnail and os.path.isfile(instance.thumbnail.path):
        os.remove(instance.thumbnail.path)

    # Make sure that the instance itself has actually been deleted, this is done seperately for archived files as they are deleted asynchronically
    if instance.state != UploadedFile.State.ARCHIVED and UploadedFile.objects.filter(slug=instance.slug).count() > 0:
        instance.delete()