from celery import shared_task
import paramiko, os, traceback
from filehost.models import UploadedFile
from filehost.oembed import CACHED_OEMBED_DICT as OEMBED_CACHE
from filehost.oembed import CACHE_AGE
from django.utils import timezone
from django.conf import settings
from stat import S_ISREG
from LFS.settings import env_file as ENV_FILE
import configparser, shutil
from PIL import Image
import ffmpeg
import environ

from preview_generator.manager import PreviewManager



# Load environment variables
env = environ.Env.read_env(ENV_FILE)

# NAS connection details 
config = configparser.ConfigParser()
config.read_file(open(r'/usr/share/django/config/LFS/nas.cnf'))

NAS_HOST = env('NAS_HOST')
NAS_SFTP_PORT = env('NAS_PORT')
NAS_USERNAME = env('NAS_USERNAME')
NAS_PATH = env('NAS_PATH')
PRIVATE_KEY_PATH = env('NAS_PRIVATE_KEY_PATH')


def print_error_info(e: Exception, transport: paramiko.Transport):
    print(f"The following credentials were used:")
    print(f"NAS_HOST: {NAS_HOST}")
    print(f"NAS_SFTP_PORT: {NAS_SFTP_PORT}")
    print(f"NAS_USERNAME: {NAS_USERNAME}")
    print(f"NAS_PATH: {NAS_PATH}")
    print(f"PRIVATE_KEY_PATH: {PRIVATE_KEY_PATH}")
    print(f"transport connection info:")
    print(f"transport.is_alive: {transport.is_alive()}")
    print(f"transport.is_active: {transport.is_active()}")
    print(f"transport.is_authenticated: {transport.is_authenticated()}")
    traceback.print_exception(e, limit=5)


@shared_task
def expire_files():
    """
    Task to periodically expire files and move them to the NAS archive if they have reached their expiration_date
    """
    transport = None
    try:
        # exception counter for for loop so that an exception does not stop all files from being processed, but only stops that current file
        exception_counter = 0

        # Connect to NAS via SFTP
        transport = paramiko.Transport((NAS_HOST, NAS_SFTP_PORT))
        private_key = paramiko.RSAKey(filename=PRIVATE_KEY_PATH)
        transport.connect(username=NAS_USERNAME, pkey=private_key)
        sftp = paramiko.SFTPClient.from_transport(transport)

        # Fetch list of expired files that are not persistent
        expired_files = UploadedFile.objects.filter(persistent=False).filter(expiration_date__lte=timezone.now())

        for uploaded_file in expired_files:
            match uploaded_file.state:

                # file is stored locally and has expired and will now be archived
                case UploadedFile.State.LOCAL:
                    try:
                        uploaded_file.set_moving()
                        nas_file_path = os.path.join(NAS_PATH, uploaded_file.file_path)

                        # Check that the file exists/is a file if not raise FileNotFoundError
                        if os.path.isfile(uploaded_file.file.path):
                            # Move the file to the nas and mark as acrhived
                            sftp.put(uploaded_file.file.path, nas_file_path)
                            uploaded_file.set_archived(years=1)
                            uploaded_file.file.delete()
                        else:
                            raise FileNotFoundError(f"Could not verify the file with path: {uploaded_file.file.path} exists or is a file!")
                    except Exception as local_e:
                        exception_counter+=1
                        print(f"Failed to archive local expired file: {uploaded_file} with local path: {uploaded_file.file.path}. Error: {local_e}")
                        traceback.print_exception(local_e, limit=3)
                        continue

                # file is stored on the nas archive and has expired, delete the file then delete the model
                case UploadedFile.State.ARCHIVED:
                    try:
                        # Get the file on the nas archive and delete both the file and the model
                        nas_file_path = os.path.join(NAS_PATH, uploaded_file.file_path)
                        sftp.remove(nas_file_path)
                        if uploaded_file.thumbnail and os.path.isfile(uploaded_file.thumbnail):
                            uploaded_file.thumbnail.delete()
                        uploaded_file.delete()
                    except Exception as archived_e:
                        exception_counter+=1
                        print(f"Failed to delete archived expired file: {uploaded_file} with remote path: {nas_file_path}. Error: {archived_e}")
                        traceback.print_exception(archived_e, limit=3)
                        continue

        # Close the SFTP connection to the NAS
        sftp.close()
        transport.close()

        if exception_counter >= 1:
            raise Exception(f"Multiple exceptions ({exception_counter}) were encountered while archiving/deleting expired files, Please review logs for more info")

        return True
    except Exception as e:
        # Print Helpful debug messages
        print(f"Expiring files has failed: {e}")
        print_error_info(e, transport)
        return False
    
@shared_task
def archive_files(slugs):
    """
    Task to forcfully archive files and move them to the NAS archive
    """
    transport = None
    try:
        # exception counter for for loop so that an exception does not stop all files from being processed, but only stops that current file
        exception_counter = 0

        # Connect to NAS via SFTP
        transport = paramiko.Transport((NAS_HOST, NAS_SFTP_PORT))
        private_key = paramiko.RSAKey(filename=PRIVATE_KEY_PATH)
        transport.connect(username=NAS_USERNAME, pkey=private_key)
        sftp = paramiko.SFTPClient.from_transport(transport)

        for slug in slugs:
            uploaded_file = UploadedFile.objects.get(slug=slug)

            if uploaded_file.state == UploadedFile.State.LOCAL:
                    uploaded_file.set_moving()
                    try:
                        nas_file_path = os.path.join(NAS_PATH, uploaded_file.file_path)

                        # Check that the file exists/is a file if not raise FileNotFoundError
                        if os.path.isfile(uploaded_file.file.path):
                            # Move the file to the nas and mark as acrhived
                            sftp.put(uploaded_file.file.path, nas_file_path)
                            uploaded_file.set_archived(years=1)
                            uploaded_file.file.delete()
                        else:
                            raise FileNotFoundError(f"Could not verify the file with path: {uploaded_file.file.path} exists or is a file!")
                    except Exception as local_e:
                        exception_counter+=1
                        print(f"Failed to archive local file: {uploaded_file} with local path: {uploaded_file.file.path}. Error: {local_e}")
                        traceback.print_exception(local_e, limit=3)
                        continue

        # Close the SFTP connection to the NAS
        sftp.close()
        transport.close()

        if exception_counter >= 1:
            raise Exception(f"Multiple exceptions ({exception_counter}) were encountered while archiving/deleting expired files, Please review logs for more info")

        return True
    except Exception as e:
        # Print Helpful debug messages
        print(f"Forcefully Archiving files has failed: {e}")
        print_error_info(e, transport)
        return False

@shared_task
def localise_files(slugs):
    """
    Task to forcfully dearchive files and move them to local storage
    """
    transport = None
    try:
        # exception counter for for loop so that an exception does not stop all files from being processed, but only stops that current file
        exception_counter = 0

        # Connect to NAS via SFTP
        transport = paramiko.Transport((NAS_HOST, NAS_SFTP_PORT))
        private_key = paramiko.RSAKey(filename=PRIVATE_KEY_PATH)
        transport.connect(username=NAS_USERNAME, pkey=private_key)
        sftp = paramiko.SFTPClient.from_transport(transport)

        for slug in slugs:
            uploaded_file = UploadedFile.objects.get(slug=slug)

            if uploaded_file.state == UploadedFile.State.ARCHIVED:
                    try:
                        uploaded_file.set_moving()
                        # Establish file paths
                        archive_path = os.path.join(NAS_PATH, uploaded_file.file_path)
                        local_path = os.path.join(settings.MEDIA_ROOT, uploaded_file.file_path)
                        
                        # Retrive the file from the nas and move to local system while ensuring required variables are set to expected values
                        sftp.get(archive_path, local_path)
                        uploaded_file.file.name = uploaded_file.file_path
                        uploaded_file.state = UploadedFile.State.LOCAL
                        uploaded_file.set_expiration(months=6)
                        uploaded_file.save()

                        # Remove the file from the nas once we have got it on the local system and set all the required variables
                        sftp.remove(archive_path)
                    except Exception as local_e:
                        exception_counter+=1
                        print(f"Failed to localise archived file: {uploaded_file}. Error: {local_e}")
                        traceback.print_exception(local_e, limit=3)
                        continue

        # Close the SFTP connection to the NAS
        sftp.close()
        transport.close()

        if exception_counter >= 1:
            raise Exception(f"Multiple exceptions ({exception_counter}) were encountered while archiving/deleting expired files, Please review logs for more info")

        return True
    except Exception as e:
        # Print Helpful debug messages
        print(f"Forcefully Localising files has failed: {e}")
        print_error_info(e, transport)
        return False

@shared_task
def localise_file(slug: str): 
    """
    Task to dearchive a file and move it from the NAS Archive to local storage
    """
    transport = None
    try:
        #UploadedFile to retrive from the nas archive
        uploaded_file = UploadedFile.objects.get(slug=slug)

        # Check the file is actually Archived and not already being moved
        if uploaded_file.state == UploadedFile.State.ARCHIVED:
            uploaded_file.set_moving()
            # Connect to NAS via SFTP
            transport = paramiko.Transport((NAS_HOST, NAS_SFTP_PORT))
            private_key = paramiko.RSAKey(filename=PRIVATE_KEY_PATH)
            transport.connect(username=NAS_USERNAME, pkey=private_key)
            sftp = paramiko.SFTPClient.from_transport(transport)
            
            # Establish file paths
            archive_path = os.path.join(NAS_PATH, uploaded_file.file_path)
            local_path = os.path.join(settings.MEDIA_ROOT, uploaded_file.file_path)
            
            # Retrive the file from the nas and move to local system while ensuring required variables are set to expected values
            sftp.get(archive_path, local_path)
            uploaded_file.file.name = uploaded_file.file_path
            uploaded_file.state = UploadedFile.State.LOCAL
            uploaded_file.set_expiration(months=6)
            uploaded_file.save()

            # Remove the file from the nas once we have got it on the local system and set all the required variables
            sftp.remove(archive_path)


            # Close the SFTP connection
            sftp.close()
            transport.close()

            return True

        elif uploaded_file.state == UploadedFile.State.LOCAL:
            raise TypeError(f"Could not de-archive file: {uploaded_file}, as it is already set to local and is not archived!")
        
    except Exception as e:
        # Print Helpful debug messages
        print(f"Dearchiving file: {slug} has failed: {e}")
        print_error_info(e, transport)
        return False

@shared_task
def delete_archived_file(slug: str):
    """
    Task to delete an archived file
    """
    transport = None
    try:
        #UploadedFile to retrive from the nas archive
        uploaded_file = UploadedFile.objects.get(slug=slug)

        # Check the file is actually Archived
        if uploaded_file.state == UploadedFile.State.ARCHIVED:
            uploaded_file.set_moving()
            # Connect to NAS via SFTP
            transport = paramiko.Transport((NAS_HOST, NAS_SFTP_PORT))
            private_key = paramiko.RSAKey(filename=PRIVATE_KEY_PATH)
            transport.connect(username=NAS_USERNAME, pkey=private_key)
            sftp = paramiko.SFTPClient.from_transport(transport)
            
            # Establish file paths
            archive_path = os.path.join(NAS_PATH, uploaded_file.file_path)

            # Get the file on the nas archive and delete the file
            sftp.remove(archive_path)

            # Close the SFTP connection
            sftp.close()
            transport.close()

            # Make sure that the instance itself ahs actually been deleted
            if UploadedFile.objects.filter(slug=uploaded_file.slug).count() > 0:
                uploaded_file.delete()

            return True

        elif uploaded_file.state == UploadedFile.State.LOCAL:
            raise TypeError(f"Could not delete local file: {uploaded_file}, as it is not archived!")
        
    except Exception as e:
        # Print Helpful debug messages
        print(f"Deleting archived file: {slug} has failed: {e}")
        print_error_info(e, transport)
        return False
    
    
@shared_task
def cleanup_orphaned_files_local():
    """
    Task to make sure that we remove files from local storage that no longer have an UploadedFile instance related to them for various reasons
    """
    # search through the upload_type directories in the media root to find all files
    for upload_type in UploadedFile.UploadType.TYPES:
        for dirpath, dirs, files in os.walk(settings.MEDIA_ROOT, upload_type):
            for name in files:
                # extract slug from file and check to see whether it matches an uploaded file
                slug = name.split('.')[0]
                if UploadedFile.objects.filter(slug=slug).count() > 0:
                    continue
                else:
                    # if the file doesn't match any uploaded files then we log the path and delete the file
                    full_path = os.path.join(dirpath, name)
                    print (f"Cleaning up orphaned local file: {full_path}")
                    os.remove(full_path)

@shared_task
def cleanup_orpahaned_files_archived():
    """
    Task to make sure that we remove files from the NAS archive that no longer have an UploadedFile instance related to them for various reasons
    """
    transport = None
    try:
        # Connect to NAS via SFTP
        transport = paramiko.Transport((NAS_HOST, NAS_SFTP_PORT))
        private_key = paramiko.RSAKey(filename=PRIVATE_KEY_PATH)
        transport.connect(username=NAS_USERNAME, pkey=private_key)
        sftp = paramiko.SFTPClient.from_transport(transport)
        
        for upload_type in UploadedFile.UploadType.TYPES:
            for file_type in UploadedFile.FileType.TYPES:
                for entry in sftp.listdir_attr(NAS_PATH + upload_type + "/" + file_type):
                    mode = entry.st_mode
                    if S_ISREG(mode):
                        # extract slug from file and check to see whether it matches an uploaded file
                        slug = entry.filename.split('.')[0]
                        if UploadedFile.objects.filter(slug=slug).count() > 0:
                            continue
                        else:
                            # if the file doesn't match any uploaded files then we log the path and delete the file
                            full_path = NAS_PATH + upload_type + "/" + file_type + "/" + entry.filename
                            print (f"Cleaning up orphaned archived file: {full_path}")
                            sftp.remove(full_path)

        # Close the SFTP connection
        sftp.close()
        transport.close()

        return True
                
    except Exception as e:
        # Print Helpful debug messages
        print(f"Cleaning up orphaned archived files has failed: {e}")
        print_error_info(e, transport)
        return False
    
@shared_task
def cleanup_orphaned_files_async():
    """
    Orphan cleanup tasks combined into one method call
    """
    cleanup_orphaned_files_local.delay()
    cleanup_orpahaned_files_archived.delay()
    
def test_sftp(debug=True):
    transport = None
    try:
        if debug:
            print("Attempting sftp connection to NAS...")
        # Connect to NAS via SFTP
        transport = paramiko.Transport((NAS_HOST, NAS_SFTP_PORT))
        private_key = paramiko.RSAKey(filename=PRIVATE_KEY_PATH)
        transport.connect(username=NAS_USERNAME, pkey=private_key)
        sftp = paramiko.SFTPClient.from_transport(transport)

        if debug:
            print("Connected, listing directories...")
        sftp.listdir()
        if debug:
            print("Success! Closing connection...")
        
        # Close the SFTP connection
        sftp.close()
        transport.close()
        if debug:
            print("Connection closed, everything seems to work!")

        return True
                
    except Exception as e:
        # Print Helpful debug messages
        print(f"Testing sftp connection has failed: {e}")
        print_error_info(e, transport)
        return False


@shared_task
def maintain_oembed_cache():
    """
    Task to make sure that we remove items that have been in the oembed cache for too long
    """
    cache_copy = OEMBED_CACHE # to prevent altering the cache while iterating through it
    for slug in cache_copy.keys():
        response, last_accessed = OEMBED_CACHE[slug]
        if last_accessed <= (timezone.now() + timezone.timedelta(seconds=CACHE_AGE)):
            del OEMBED_CACHE[slug]


@shared_task
def create_thumbnail(slug: str, manager: PreviewManager = PreviewManager('/tmp/cache/', create_folder=True)):
    try:
        uploaded_file = UploadedFile.objects.get(slug=slug)
        # Setup Thumbnail paths and get filename
        filename = os.path.basename(uploaded_file.file_path)
        uploaded_file.thumbnail_path = os.path.join(uploaded_file.upload_type, uploaded_file.file_type, "THUMBNAIL", filename)
        absolute_thumb_path = os.path.join(settings.MEDIA_ROOT, uploaded_file.thumbnail_path)
        absolute_file_path = os.path.join(settings.MEDIA_ROOT, uploaded_file.file_path)

        # Check that the thumbnail path exists if not create it
        thumbnail_dir = os.path.join(settings.MEDIA_ROOT, uploaded_file.upload_type, uploaded_file.file_type, "THUMBNAIL")
        if not os.path.exists(thumbnail_dir):
            os.mkdir(thumbnail_dir)

        thumbnail_ext = ""

        # If mime type is supported by the preview builder then we build a thumbnail preview of the file
        if uploaded_file.mime_type in manager.get_supported_mimetypes():
            print("mimetype is supported by preview builder!")
            try:
                new_thumbnail_file_path = ""
                
                if uploaded_file.mime_type in UploadedFile.FileType.SUPPORTED_ARCHIVE_MIMETYPES:
                    print("creating zip file preview...")
                    # Create the archive text preview using preview generator
                    archive_text_preview = manager.get_text_preview(file_path=absolute_file_path)
                    print("created zip file text preview!")
                    # Create a Jpeg of the text preview of the file
                    new_thumbnail_file_path = manager.get_jpeg_preview(file_path=archive_text_preview, height=512, width=512)
                    print("created zip file JPEG preview!")
                else:
                    print("creating standard JPEG preview...")      
                    # Create the thumbnail using preview generator
                    new_thumbnail_file_path = manager.get_jpeg_preview(file_path=absolute_file_path, height=512, width=512)
                    print("created standard JPEG preview!")

                print("Copying preview to new location...")
                # Copy the new thumbnail to it's permanent location
                thumbnail_ext = "jpeg"
                shutil.copy2(new_thumbnail_file_path, f"{absolute_thumb_path}.jpeg")
                absolute_thumb_path = f"{absolute_thumb_path}.jpeg"
            except Exception as e:
                print(f"Creating thumbnail for: {slug} has failed: {e}")
                traceback.print_exception(e, limit=5)
                print("error occurred during thumbnail generation, creating basic svg thumbnail...")
                # An error occurred during preivew generation, we will generate a basic svg preview instead
                svg = uploaded_file.generate_basic_svg_preview(filename)
                # Write to an svg thumbnail file
                thumbnail_ext = "svg"
                with open(f"{absolute_thumb_path}.svg", 'w') as f:
                    f.write(svg)
                    f.close()
                absolute_thumb_path = f"{absolute_thumb_path}.svg"

        else:
            print("mimetype is not supported by preview generator, creating basic svg...")
            # Mimetype is not supported by preview generator so we make a basic svg of the slug and mimetype
            svg = uploaded_file.generate_basic_svg_preview(filename)
            # Write to an svg thumbnail file
            thumbnail_ext = "svg"
            with open(f"{absolute_thumb_path}.svg", 'w') as f:
                f.write(svg)
                f.close()
            absolute_thumb_path = f"{absolute_thumb_path}.svg"

        if not (thumbnail_ext == 'svg'):
            print("thumbnail is not an svg, attempting to resize...")
            # Resize the image to make sure that it is going to be 512x512
            img = Image.open(absolute_thumb_path)
            if img.width > 512 or img.height > 512:
                img.thumbnail((512, 512))
            # Save and close the thumbnail image regardless of whether we resized it or not as we still opened the image file
            img.save(absolute_thumb_path)
            img.close()
            print("thumbnail resized!")

        print("Adjusting uploaded file properties...")
        # Force point the thumbnail property to the new file and save
        uploaded_file.thumbnail_path = f"{uploaded_file.thumbnail_path}.{thumbnail_ext}"
        uploaded_file.thumbnail.name = uploaded_file.thumbnail_path
        uploaded_file.save()
        print("uploaded file properties adjusted! Thumbnail saved!")
    except Exception as e:
        # Print Helpful debug messages
        print(f"Creating thumbnail for: {slug} has failed: {e}")
        traceback.print_exception(e, limit=5)
