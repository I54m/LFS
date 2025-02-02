from django.test import TestCase, override_settings
from django.core.files import File
from django.conf import settings
from django.utils import timezone
import os

from filehost import tasks
from .models import UploadedFile, random_slug, SLUG_LENGTH, post_save_hook
from i54m_apiuser.models import ApiUser
from django.contrib.auth.models import AnonymousUser


### Test Data Files for upload ###

TEST_FILE = "filehost/test_file_uploads/test.54m"
TEST_FONT = "filehost/test_file_uploads/test.otf"
TEST_MODEL = "filehost/test_file_uploads/test.obj"
TEST_AUDIO = "filehost/test_file_uploads/test.mp3"
TEST_VIDEO = "filehost/test_file_uploads/test.mp4"
TEST_IMAGE = "filehost/test_file_uploads/test.png"
TEST_ZIP = "filehost/test_file_uploads/test.zip"
TEST_TEXT = "filehost/test_file_uploads/test.txt"
TEST_APPLICATION = "filehost/test_file_uploads/test.exe"

TEST_FILE_PATHS = (
    (TEST_FILE, "file"),
    (TEST_FONT, "font"),
    (TEST_MODEL, "model"),
    (TEST_AUDIO, "audio"),
    (TEST_VIDEO, "video"),
    (TEST_IMAGE, "image"),
    (TEST_ZIP, "zip"), 
    (TEST_TEXT, "text"),
    (TEST_APPLICATION, "application")
    )

# Isolated test media root so that prod data is not altered
TEST_MEDIA_ROOT = os.path.join(settings.BASE_DIR, 'test_media/')

UPLOAD_TYPES = UploadedFile.UploadType.TYPES



def create_test_apiusers(cls):
    cls.admin_user = ApiUser.objects.create_superuser(username="test_admin", password="password")
    cls.staff_user = ApiUser.objects.create(username="test_staff", password="password")
    cls.staff_user.is_staff = True
    cls.staff_user.save()
    cls.staff_user.refresh_from_db()
    cls.other_user = ApiUser.objects.create(username="test_user", password="password")
    cls.uploader_user = ApiUser.objects.create(username="test_uploader", password="password")


def create_test_uploaded_files(cls):
    create_test_apiusers(cls)
    for file_path in TEST_FILE_PATHS:
        for type in UPLOAD_TYPES:
            uf = UploadedFile(file=File(open(file_path[0], "rb")), upload_type=type, uploader=cls.uploader_user)
            uf.set_expiration(days=1)
            uf.save()
            # force run post_save_hook synchronically and refresh from db so that post save functions work correctly and are reflected in tests
            post_save_hook(instance=uf, created=True)
            uf.refresh_from_db()
            cls.uploaded_files[f"{type.lower()}-{file_path[1]}"] = uf
            

def delete_test_uploaded_files(cls):
    for key in cls.uploaded_files.keys():
        uploaded_file = cls.uploaded_files[key]
        uploaded_file.refresh_from_db()
        if uploaded_file.file and os.path.isfile(uploaded_file.file.path):
            os.remove(uploaded_file.file.path)
        if uploaded_file.thumbnail and os.path.isfile(uploaded_file.thumbnail.path):
            os.remove(uploaded_file.thumbnail.path)
        try:
            os.remove(uploaded_file.thumbnail_path)
            os.remove(uploaded_file.file_path)
        except:
            pass
        uploaded_file.delete()
    try:
        for root, dirs, files in os.walk(TEST_MEDIA_ROOT, topdown=False):
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(TEST_MEDIA_ROOT)
    except Exception as e:
        print(f"Failed to clean up all directories: {e}")
    else:
        print("All cleaned up!")

# TODO MORE TESTS YAY!!!!

######################################################################################################################
# ------------------------------------------------------------------------------------------------------------------ #
#                                        UploadedFile Model Tests                                                    #
# ------------------------------------------------------------------------------------------------------------------ #
######################################################################################################################


@override_settings(MEDIA_ROOT=os.path.join(TEST_MEDIA_ROOT, "UploadedFileTests"))
class UploadedFileTests(TestCase):

    uploaded_files = {}
    admin_user = ""
    staff_user = ""
    uploader_user = ""
    other_user = ""

    @classmethod
    def setUpTestData(cls):
        print("\n")
        print("Creating test data for UploadedFile model..")
        create_test_uploaded_files(cls)
        print("Created test data for UploadedFile model!\n")

    @classmethod
    def tearDownClass(cls):
        print("\n")
        print("Cleaning up files and directories used for testing UploadedFile model..")
        delete_test_uploaded_files(cls)
        return super().tearDownClass()


    def test_setup_variables(self):
        """
        setUpTestData() is working as intended and has all data setup correctly for testing
        """
        self.assertEqual(len(self.uploaded_files.keys()), (len(TEST_FILE_PATHS)*len(UPLOAD_TYPES)))
        for key in self.uploaded_files.keys():
            uploaded_file = self.uploaded_files[key]
            try:
                uploaded_file.refresh_from_db()
                self.assertIsInstance(uploaded_file, UploadedFile)
                self.assertTrue(os.path.isfile(uploaded_file.file.path))
                self.assertIsNotNone(uploaded_file.uploader)
            except Exception as e:
                print(f"Error Validating test data for {key} this error was caused by: {e}")
        
        self.assertTrue(self.admin_user.is_superuser)
        
        self.assertIsNotNone(self.uploader_user)
        self.assertTrue(self.uploader_user.is_authenticated)
        self.assertFalse(self.uploader_user.is_superuser)
        

    def test_random_slug(self):
        """
        random_slug() returns a slug that is the correct length and is not in use by any other UploadedFile.
        """
        slug = random_slug()
        self.assertIs(len(slug), SLUG_LENGTH)
        self.assertFalse(UploadedFile.objects.filter(slug=slug).count() > 0)


##################################################
#           test filetype uploads                #
##################################################


    def test_unknown_filetype_upload(self):
        """
        test that when the file type is unknown it defaults to the 'File' file type and is uploaded to the correct directory
        """
        for type in UPLOAD_TYPES:
            uf: UploadedFile = self.uploaded_files[f"{type.lower()}-file"]
            self.assertEqual(uf.file_type, UploadedFile.FileType.FILE) # ensure default file type has been selected
            self.assertEqual(uf.mime_type, "application/octet-stream") # ensure default mime type has been selected
            self.assertEqual(uf.file_path, f"{type}/FILE/{uf.slug}.54m") # ensure file path is as expected
    
    def test_font_filetype_upload(self):
        """
        test that when the file type is a font it defaults to the 'FONT' file type and is uploaded to the correct directory
        """
        for type in UPLOAD_TYPES:
            uf: UploadedFile = self.uploaded_files[f"{type.lower()}-font"]
            self.assertEqual(uf.file_type, UploadedFile.FileType.FONT) # ensure correct file type has been selected
            self.assertEqual(uf.mime_type, "font/otf") # ensure correct mime type has been selected
            self.assertEqual(uf.file_path, f"{type}/FONT/{uf.slug}.otf") # ensure file path is as expected

    def test_model_filetype_upload(self):
        """
        test that when the file type is a model it defaults to the 'MODEL' file type and is uploaded to the correct directory
        """
        for type in UPLOAD_TYPES:
            uf: UploadedFile = self.uploaded_files[f"{type.lower()}-model"]
            self.assertEqual(uf.file_type, UploadedFile.FileType.MODEL) # ensure correct file type has been selected
            self.assertEqual(uf.mime_type, "model/obj") # ensure correct mime type has been selected
            self.assertEqual(uf.file_path, f"{type}/MODEL/{uf.slug}.obj") # ensure file path is as expected    

    def test_audio_filetype_upload(self):
        """
        test that when the file type is audio it defaults to the 'AUDIO' file type and is uploaded to the correct directory
        """
        for type in UPLOAD_TYPES:
            uf: UploadedFile = self.uploaded_files[f"{type.lower()}-audio"]
            self.assertEqual(uf.file_type, UploadedFile.FileType.AUDIO) # ensure correct file type has been selected
            self.assertEqual(uf.mime_type, "audio/mpeg") # ensure correct mime type has been selected
            self.assertEqual(uf.file_path, f"{type}/AUDIO/{uf.slug}.mp3") # ensure file path is as expected

    def test_video_filetype_upload(self):
        """
        test that when the file type is video it defaults to the 'VIDEO' file type and is uploaded to the correct directory
        """
        for type in UPLOAD_TYPES:
            uf: UploadedFile = self.uploaded_files[f"{type.lower()}-video"]
            self.assertEqual(uf.file_type, UploadedFile.FileType.VIDEO) # ensure correct file type has been selected
            self.assertEqual(uf.mime_type, "video/mp4") # ensure correct mime type has been selected
            self.assertEqual(uf.file_path, f"{type}/VIDEO/{uf.slug}.mp4") # ensure file path is as expected

    def test_image_filetype_upload(self):
        """
        test that when the file type is image it defaults to the 'IMAGE' file type and is uploaded to the correct directory
        """
        for type in UPLOAD_TYPES:
            uf: UploadedFile = self.uploaded_files[f"{type.lower()}-image"]
            self.assertEqual(uf.file_type, UploadedFile.FileType.IMAGE) # ensure correct file type has been selected
            self.assertEqual(uf.mime_type, "image/png") # ensure correct mime type has been selected
            self.assertEqual(uf.file_path, f"{type}/IMAGE/{uf.slug}.png") # ensure file path is as expected

    def test_zip_filetype_upload(self):
        """
        test that when the file type is image it defaults to the 'IMAGE' file type and is uploaded to the correct directory
        """
        for type in UPLOAD_TYPES:
            uf: UploadedFile = self.uploaded_files[f"{type.lower()}-zip"]
            self.assertEqual(uf.file_type, UploadedFile.FileType.APPLICATION) # ensure correct file type has been selected
            self.assertEqual(uf.mime_type, "application/zip") # ensure correct mime type has been selected
            self.assertEqual(uf.file_path, f"{type}/APPLICATION/{uf.slug}.zip") # ensure file path is as expected
            
    def test_text_filetype_upload(self):
        """
        test that when the file type is text it defaults to the 'TEXT' file type and is uploaded to the correct directory
        """
        for type in UPLOAD_TYPES:
            uf: UploadedFile = self.uploaded_files[f"{type.lower()}-text"]
            self.assertEqual(uf.file_type, UploadedFile.FileType.TEXT) # ensure correct file type has been selected
            self.assertEqual(uf.mime_type, "text/plain") # ensure correct mime type has been selected
            self.assertEqual(uf.file_path, f"{type}/TEXT/{uf.slug}.txt") # ensure file path is as expected
    
    def test_application_filetype_upload(self):
        """
        test that when the file type is an application it defaults to the 'APPLICATION' file type and is uploaded to the correct directory
        """
        for type in UPLOAD_TYPES:
            uf: UploadedFile = self.uploaded_files[f"{type.lower()}-application"]
            self.assertEqual(uf.file_type, UploadedFile.FileType.APPLICATION) # ensure correct file type has been selected
            self.assertEqual(uf.mime_type, "application/x-msdos-program") # ensure correct mime type has been selected
            self.assertEqual(uf.file_path, f"{type}/APPLICATION/{uf.slug}.exe") # ensure file path is as expected


##################################################
#           test set_expiration                  #
##################################################
            
    def test_set_expiration_past_date(self):
        """
        test that we can't set an expiry date in the past
        """
        for key in self.uploaded_files.keys():
            uf: UploadedFile = self.uploaded_files[key]
            uf.set_expiration(days=-10)
            self.assertEqual(timezone.localdate(), uf.expiration_date)

    def test_set_expiration_date_calculation(self):
        """
        test that expiration dates are calculated as expected
        """
        for key in self.uploaded_files.keys():
            uf: UploadedFile = self.uploaded_files[key]
            uf.set_expiration(weeks=1, months=1, years=1)
            expected = timezone.localdate() + timezone.timedelta(days=401)
            self.assertEqual(expected, uf.expiration_date)


##################################################
#           test set_archived                    #
##################################################
            

    def test_set_archived_persistent(self):
        """
        test that we cannot archive persistent files
        """
        for key in self.uploaded_files.keys():
            uf: UploadedFile = self.uploaded_files[key]
            uf.set_persistent()
            self.assertTrue(uf.persistent)
            try:
                uf.set_archived(days=1)
            except:
                self.assertRaisesMessage(expected_exception=ValueError, expected_message="Error: trying to archive a persistent file! This defeats the purpose of persistent files!")
            self.assertEqual(uf.state, UploadedFile.State.LOCAL)
            uf.persistent = False
            uf.save()

    def test_set_archived_state_expiration_change(self):
        """
        test that the state and expiration change on an archived file when we set_archived
        """
        for key in self.uploaded_files.keys():
            uf: UploadedFile = self.uploaded_files[key]
            old_expiration = uf.expiration_date
            old_state = uf.state
            uf.set_archived(years=100)
            self.assertNotEqual(uf.state, old_state)
            self.assertNotEqual(uf.expiration_date, old_expiration)
            uf.state = UploadedFile.State.LOCAL
            uf.save()


##################################################
#             test set_moving                    #
##################################################


    def test_set_moving_persistent(self):
        """
        Test that we cannot set persistent file to moving
        """
        for key in self.uploaded_files.keys():
                uf: UploadedFile = self.uploaded_files[key]
                uf.set_persistent()
                self.assertTrue(uf.persistent)
                try:
                    uf.set_moving()
                except:
                    self.assertRaisesMessage(expected_exception=ValueError, expected_message="Error: trying to move a persistent file! This defeats the purpose of persistent files!")
                self.assertEqual(uf.state, UploadedFile.State.LOCAL)
                uf.persistent = False
                uf.save()

    def test_set_moving_state_change(self):
        """
        Test that that state change on a file when we set_moving
        """
        for key in self.uploaded_files.keys():
            uf: UploadedFile = self.uploaded_files[key]
            old_state = uf.state
            uf.set_moving()
            self.assertNotEqual(uf.state, old_state)
            uf.state = UploadedFile.State.LOCAL
            uf.save()


##################################################
#             test can_be_managed_by             #
##################################################


    def test_user_can_manage_own_upload(self):
        """
        Test that can_be_managed_by returns true when the uploader is provided as the user
        """
    
        for key in self.uploaded_files.keys():
            uf: UploadedFile = self.uploaded_files[key]
            self.assertTrue(uf.can_be_managed_by(ApiUser.objects.get(pk=self.uploader_user.pk)))

    def test_super_user_can_manage_upload(self):
        """
        Test that can_be_managed_by returns True when the user provided is a SuperUser
        """
        for key in self.uploaded_files.keys():
            uf: UploadedFile = self.uploaded_files[key]
            self.assertTrue(uf.can_be_managed_by(self.admin_user))

    def test_anon_user_cannnot_manage_upload(self):
        """
        Test that can_be_managed_by returns False when an anon user is provided as the user
        """
        anon_user = AnonymousUser()
        for key in self.uploaded_files.keys():
            uf: UploadedFile = self.uploaded_files[key]
            self.assertFalse(uf.can_be_managed_by(anon_user))


    def test_none_user_cannnot_manage_upload(self):
        """
        Test that can_be_managed_by returns False when the user provided is None or non existent
        """
        none_user = None
        for key in self.uploaded_files.keys():
            uf: UploadedFile = self.uploaded_files[key]
            self.assertFalse(uf.can_be_managed_by(none_user))

    def test_other_user_cannnot_manage_upload(self):
        """
        Test that can_be_managed_by returns False when the user provided is different from the uploader
        """
        for key in self.uploaded_files.keys():
            uf: UploadedFile = self.uploaded_files[key]
            self.assertFalse(uf.can_be_managed_by(self.other_user))


##################################################
#               test thumbnail                   #
##################################################

    def test_unknown_filetype_thumbnail(self):
        """
        test that when the file type is unknown it still generates a thumbnail as expected
        """
        for type in UPLOAD_TYPES:
            uf: UploadedFile = self.uploaded_files[f"{type.lower()}-file"]
            self.assertTrue(uf.has_thumbnail) # ensure that the has_thumbnail property is working
            self.assertEqual(uf.thumbnail_path, f"{type}/FILE/THUMBNAIL/{uf.slug}.54m.svg") # ensure thumbnail file path is as expected
            self.assertIsNotNone(uf.thumbnail) # ensure that there is a thumbnail linked to the uploadedfile
            self.assertTrue(os.path.exists(uf.thumbnail.path)) # ensure that the thumbnail file actually exists
    
    def test_font_filetype_thumbnail(self):
        """
        test that when the file type is a font it still generates a thumbnail as expected
        """
        for type in UPLOAD_TYPES:
            uf: UploadedFile = self.uploaded_files[f"{type.lower()}-font"]
            self.assertTrue(uf.has_thumbnail) # ensure that the has_thumbnail property is working
            self.assertEqual(uf.thumbnail_path, f"{type}/FONT/THUMBNAIL/{uf.slug}.otf.svg") # ensure thumbnail file path is as expected
            self.assertIsNotNone(uf.thumbnail) # ensure that there is a thumbnail linked to the uploadedfile
            self.assertTrue(os.path.exists(uf.thumbnail.path)) # ensure that the thumbnail file actually exists

    def test_model_filetype_thumbnail(self):
        """
        test that when the file type is a model it still generates a thumbnail as expected
        """
        for type in UPLOAD_TYPES:
            uf: UploadedFile = self.uploaded_files[f"{type.lower()}-model"]
            self.assertTrue(uf.has_thumbnail) # ensure that the has_thumbnail property is working
            self.assertEqual(uf.thumbnail_path, f"{type}/MODEL/THUMBNAIL/{uf.slug}.obj.svg") # ensure thumbnail file path is as expected
            self.assertIsNotNone(uf.thumbnail) # ensure that there is a thumbnail linked to the uploadedfile
            self.assertTrue(os.path.exists(uf.thumbnail.path)) # ensure that the thumbnail file actually exists 

    def test_audio_filetype_thumbnail(self):
        """
        test that when the file type is audio it still generates a thumbnail as expected
        """
        for type in UPLOAD_TYPES:
            uf: UploadedFile = self.uploaded_files[f"{type.lower()}-audio"]
            self.assertTrue(uf.has_thumbnail) # ensure that the has_thumbnail property is working
            self.assertEqual(uf.thumbnail_path, f"{type}/AUDIO/THUMBNAIL/{uf.slug}.mp3.svg") # ensure thumbnail file path is as expected
            self.assertIsNotNone(uf.thumbnail) # ensure that there is a thumbnail linked to the uploadedfile
            self.assertTrue(os.path.exists(uf.thumbnail.path)) # ensure that the thumbnail file actually exists

    def test_video_filetype_thumbnail(self):
        """
        test that when the file type is video it still generates a thumbnail as expected
        """
        for type in UPLOAD_TYPES:
            uf: UploadedFile = self.uploaded_files[f"{type.lower()}-video"]
            self.assertTrue(uf.has_thumbnail) # ensure that the has_thumbnail property is working
            self.assertEqual(uf.thumbnail_path, f"{type}/VIDEO/THUMBNAIL/{uf.slug}.mp4.svg") # ensure thumbnail file path is as expected
            self.assertIsNotNone(uf.thumbnail) # ensure that there is a thumbnail linked to the uploadedfile
            self.assertTrue(os.path.exists(uf.thumbnail.path)) # ensure that the thumbnail file actually exists

    def test_image_filetype_thumbnail(self):
        """
        test that when the file type is image it still generates a thumbnail as expected
        """
        for type in UPLOAD_TYPES:
            uf: UploadedFile = self.uploaded_files[f"{type.lower()}-image"]
            self.assertTrue(uf.has_thumbnail) # ensure that the has_thumbnail property is working
            self.assertEqual(uf.thumbnail_path, f"{type}/IMAGE/THUMBNAIL/{uf.slug}.png.jpeg") # ensure thumbnail file path is as expected
            self.assertIsNotNone(uf.thumbnail) # ensure that there is a thumbnail linked to the uploadedfile
            self.assertTrue(os.path.exists(uf.thumbnail.path)) # ensure that the thumbnail file actually exists

    def test_zip_filetype_thumbnail(self):
        """
        test that when the file type is image it still generates a thumbnail as expected
        """
        for type in UPLOAD_TYPES:
            uf: UploadedFile = self.uploaded_files[f"{type.lower()}-zip"]
            self.assertTrue(uf.has_thumbnail) # ensure that the has_thumbnail property is working
            self.assertEqual(uf.thumbnail_path, f"{type}/APPLICATION/THUMBNAIL/{uf.slug}.zip.jpeg") # ensure thumbnail file path is as expected
            self.assertIsNotNone(uf.thumbnail) # ensure that there is a thumbnail linked to the uploadedfile
            self.assertTrue(os.path.exists(uf.thumbnail.path)) # ensure that the thumbnail file actually exists
            
    def test_text_filetype_thumbnail(self):
        """
        test that when the file type is text it still generates a thumbnail as expected
        """
        for type in UPLOAD_TYPES:
            uf: UploadedFile = self.uploaded_files[f"{type.lower()}-text"]
            self.assertTrue(uf.has_thumbnail) # ensure that the has_thumbnail property is working
            self.assertEqual(uf.thumbnail_path, f"{type}/TEXT/THUMBNAIL/{uf.slug}.txt.jpeg") # ensure thumbnail file path is as expected
            self.assertIsNotNone(uf.thumbnail) # ensure that there is a thumbnail linked to the uploadedfile
            self.assertTrue(os.path.exists(uf.thumbnail.path)) # ensure that the thumbnail file actually exists
    
    def test_application_filetype_thumbnail(self):
        """
        test that when the file type is an application it still generates a thumbnail as expected
        """
        for type in UPLOAD_TYPES:
            uf: UploadedFile = self.uploaded_files[f"{type.lower()}-application"]
            self.assertTrue(uf.has_thumbnail) # ensure that the has_thumbnail property is working
            self.assertEqual(uf.thumbnail_path, f"{type}/APPLICATION/THUMBNAIL/{uf.slug}.exe.svg") # ensure thumbnail file path is as expected
            self.assertIsNotNone(uf.thumbnail) # ensure that there is a thumbnail linked to the uploadedfile
            self.assertTrue(os.path.exists(uf.thumbnail.path)) # ensure that the thumbnail file actually exists


######################################################################################################################
# ------------------------------------------------------------------------------------------------------------------ #
#                                       Views and File fetching Tests                                                #
# ------------------------------------------------------------------------------------------------------------------ #
######################################################################################################################

@override_settings(MEDIA_ROOT=os.path.join(TEST_MEDIA_ROOT, "ViewsTests"))
class ViewsTests(TestCase):
    pass


######################################################################################################################
# ------------------------------------------------------------------------------------------------------------------ #
#                                               OEmbed Tests                                                         #
# ------------------------------------------------------------------------------------------------------------------ #
######################################################################################################################

@override_settings(MEDIA_ROOT=os.path.join(TEST_MEDIA_ROOT, "OEmbedTests"))
class OEmbedTests(TestCase):
    pass


######################################################################################################################
# ------------------------------------------------------------------------------------------------------------------ #
#                                   Celery Async and Periodic Tasks Tests                                            #
# ------------------------------------------------------------------------------------------------------------------ #
######################################################################################################################

@override_settings(MEDIA_ROOT=os.path.join(TEST_MEDIA_ROOT, "CeleryTasksTests"))
class CeleryTasksTests(TestCase):
    
    uploaded_files = {}
    admin_user = ""
    staff_user = ""
    uploader_user = ""
    other_user = ""

    @classmethod
    def setUpTestData(cls):
        print("\n")
        print("Creating test data for celery tasks..")
        create_test_uploaded_files(cls)
        print("Created test data for celery tasks!\n")

    @classmethod
    def tearDownClass(cls):
        print("\n")
        print("Cleaning up files and directories used for testing celery tasks..")
        delete_test_uploaded_files(cls)
        return super().tearDownClass()
    

    def test_setup_variables(self):
        """
        setUpTestData() is working as intended and has all data setup correctly for testing
        """
        self.assertEqual(len(self.uploaded_files.keys()), (len(TEST_FILE_PATHS)*len(UPLOAD_TYPES)))
        for key in self.uploaded_files.keys():
            uploaded_file = self.uploaded_files[key]
            try:
                uploaded_file.refresh_from_db()
                self.assertIsInstance(uploaded_file, UploadedFile)
                self.assertTrue(os.path.isfile(uploaded_file.file.path))
            except Exception as e:
                print(f"Error Validating test data for {key} this error was caused by: {e}")

    def test_sftp_connection(self):
        """
        test that the sftp connection works as intended and is configured correctly
        """
        self.assertTrue(tasks.test_sftp(debug=False))









