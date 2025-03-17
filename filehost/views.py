from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import  JsonResponse, HttpResponse, FileResponse, HttpResponseBadRequest, HttpResponseNotFound, HttpResponseNotAllowed, HttpRequest, HttpResponseForbidden
from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings
from .models import UploadedFile
from .forms import UploadedFileForm
from filehost import tasks, oembed
from device_detector import DeviceDetector
from i54m_apiuser.models import ApiKey, ApiUser
import os

from django.views.generic import DeleteView, UpdateView

##### Home/Landing Page #####
def homepage(request: HttpRequest):
    recent_image_uploads = UploadedFile.objects.filter(featured=True, state=UploadedFile.State.LOCAL, file_type=UploadedFile.FileType.IMAGE, access=UploadedFile.Access.PUBLIC).order_by('-uploaded_at')[:10]
    return render(request=request, template_name="filehost/index.html", context={'recent_image_uploads': recent_image_uploads,}) # 200 OK

##### Fetch Uploaded File or 404 #####
def check_uploaded_file(slug: str, request: HttpRequest, localise=True, display_messages=True):
    '''
        Attempts to fetch the uploaded file and performs various checks needed before returning the file.\n
        returns: 400 Bad Request, 404 Not Found, 403 Forbidden or the UploadedFile Object
    '''
    if request == None:
        return HttpResponseBadRequest("No request was provided when fetching the uploaded file. Without a request object we cannot determine access rights!"), None # 400 Bad Request
    
    try:
        uploadedfile = UploadedFile.objects.get(slug=slug)
    except UploadedFile.DoesNotExist:
        # UploadedFile does not exist, indicating moved or deleted
        return HttpResponseNotFound("That file does not exist on our system, if this is a mistake then it may have been moved or deleted."), None # 404 Not Found
    
    match uploadedfile.state:

        case UploadedFile.State.ARCHIVED:
            if localise:
                # File is Archived, we will need to fetch it before serving the file, in the mean time the thumbnail will be shown
                tasks.localise_file.delay(uploadedfile.slug)
                if display_messages:
                    messages.warning(request, "This file is archived and is now being de-archived for viewing, please try again shortly for the full version.")
            elif display_messages:
                    messages.warning(request, "This file is currently archived, only a thumbnail preview is available.")


        case UploadedFile.State.LOCAL:
            if not os.path.exists(uploadedfile.file.path):
                # File is local check it actually exists before continuing
                # Actual file no longer exists, remove persistence and delete model then return Not found response (check failed)
                uploadedfile.persistent = False
                uploadedfile.save()
                uploadedfile.delete()
                # Indicate file deletion as the check failed
                return HttpResponseNotFound("We don't have that file anymore. It may have been moved or deleted! We have removed all traces of it from our system so it will now have to be reuploaded!"), None # 404 Not Found
        
        case UploadedFile.State.MOVING:
            # File is currently being moved (either to or from Archives) and we will not be able to show the full version
            if display_messages:
                    messages.warning(request, "This file is archived and is currently being moved, please try again shortly for the full version.")

    if uploadedfile.access == UploadedFile.Access.PUBLIC:
        # File can be accessed publicly, return the uploadedfile object
        return None, uploadedfile

    user = request.user

    if not user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next={request.path}"), None 
    
    if uploadedfile.access == UploadedFile.Access.MEMBERS_ONLY:
        # File can be accessed by members, user is a member, return the uploadedfile object
        return None, uploadedfile
    
    if uploadedfile.access == UploadedFile.Access.PRIVATE:
        if user == uploadedfile.uploader:
            # File is private, user is the uploader of the file, return the uploadedfile object
            return None, uploadedfile
        elif user.is_superuser:
            all_error_messages_content = [msg.message for msg in list(messages.get_messages(request)) if msg.level_tag == 'warning']
            if f"{uploadedfile.slug} is set to private and owned by: {user.username}, You can view this as you are an admin!" not in all_error_messages_content:
                if display_messages:
                    messages.warning(request, f"{uploadedfile.slug} is set to private and owned by: {user.username}, You can view this as you are an admin!")
            # File is private, user is an admin, return the uploadedfile object
            return None, uploadedfile

    return HttpResponse(status=500, content="Somehow the uploaded file was found but we were not able to determine access rules, Was another access level added without being added to the pre fetching checks?"), None # 500 Internal Server Error

##################################################
#                File Management                 #
##################################################

@login_required
def list_uploads(request: HttpRequest):
    recent_uploads = UploadedFile.objects.filter(uploader=request.user.pk).order_by('-uploaded_at')[:10]
    all_uploads = UploadedFile.objects.filter(uploader=request.user.pk).order_by('-uploaded_at')
    return render(request=request, template_name="filehost/list.html", context={'recent_uploads': recent_uploads, 'all_uploads': all_uploads,}) # 200 OK

class DeleteUploadClass(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = UploadedFile
    permission_denied_message = "You do not have permission to manage or delete this uploaded file!"

    def get_success_url(self):
        messages.success(self.request, f"Successfully deleted: {self.object.slug}")
        return reverse('filehost:list-uploads')
    
    def test_func(self):
        return self.get_object().can_be_managed_by(self.request.user)
    
    def dispatch(self, request, *args, **kwargs):
        user_test_result = self.get_test_func()()
        if not user_test_result:
            return HttpResponseForbidden(self.get_permission_denied_message()) # 403 Forbidden
        return super().dispatch(request, *args, **kwargs)

class UpdateUploadClass(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = UploadedFile
    template_name_suffix = "_update"
    permission_denied_message = "You do not have permission to manage or delete this uploaded file!"
    fields = ["expiration_date", "persistent", "uploader", "access", "featured"]
    # read only fields: ("file", "slug", "uploaded_at", "state", "upload_type", "file_type", "mime_type", "thumbnail")

    def get_success_url(self):
        messages.success(self.request, f"Successfully updated: {self.object.slug}")
        return reverse('filehost:fetch-file-formatted', slug=self.get_object.slug)

    def test_func(self):
        return self.get_object().can_be_managed_by(self.request.user)
    
    def dispatch(self, request, *args, **kwargs):
        user_test_result = self.get_test_func()()
        if not user_test_result:
            return HttpResponseForbidden(self.get_permission_denied_message()) # 403 Forbidden
        return super().dispatch(request, *args, **kwargs)


##################################################
#                File Uploading                  #
##################################################


@csrf_exempt
def handle_api_upload(request: HttpRequest):
    if request.method != 'POST':
        return JsonResponse({
                "status": 400,
                "data": {
                    "error": '400 - Bad Request. POST is currently the only allowed method for api uploads!',
                }
            }, status=400) # 400 Bad Request
    
    id = request.META.get('HTTP_APP_ID') or request.POST.get('app_id')
    
    if not id:
        return JsonResponse({
                "status": 400,
                "data": {
                    "error": '400 - Bad Request. No App Id was provided in headers or POST data!',
                }
            }, status=400) # 400 Bad Request

    try:
        api_key = ApiKey.objects.get(app_id=id)
    except ObjectDoesNotExist:
        return JsonResponse({
                "status": 401,
                "data": {
                    "error": '401 - Unauthorized. Invalid App Id!',
                }
            }, status=401) # 401 Unauthorized
    
    if not api_key.active:
        return JsonResponse({
                "status": 401,
                "data": {
                    "error": '401 - Unauthorized. This Api Key is not active!',
                }
            }, status=401) # 401 Unauthorized
    
    secret = request.META.get('HTTP_API_SECRET') or request.POST.get('api_secret') 
    
    if not secret:
        return JsonResponse({
                "status": 400,
                "data": {
                    "error": '400 - Bad Request. No Api Secret was provided in headers or POST data!',
                }
            }, status=400) # 400 Bad Request
    

    if not api_key.has_valid_api_secret(secret_key=secret):
        return JsonResponse({
                "status": 401,
                "data": {
                    "error": '401 - Unauthorized. Invalid Api Secret!',
                }
            }, status=401) # 401 Unauthorized
    
    # api key is authorized, update last accessed on api key then proceed with file upload
    api_key.update_last_accessed(request)

    try:
        user = ApiUser.objects.get(pk=api_key.api_user.pk)
    except ObjectDoesNotExist:
        return JsonResponse({
                "status": 400,
                "data": {
                    "error": '400 - Bad Request. Api Key is not linked to a valid user?!',
                }
            }, status=400) # 400 Bad Request
    
    file = request.FILES.get('uploaded_file') or request.FILES.get('file')
    if file:
        try:
            # Get persistent and featured flags from headers or post data or to none when not provided
            persistent = str.lower(request.META.get('HTTP_PERSISTENT') or request.POST.get('persistent') or "none")
            featured = str.lower(request.META.get('HTTP_FEATURED') or request.POST.get('featured') or "none")

            # Convert from string to Boolean
            if persistent == "true": persistent = True
            else: persistent = False

            if featured == "false": featured = False
            else: featured = True

            access = str.lower(request.META.get('HTTP_ACCESS') or request.POST.get('access') or "none")
            match access:
                case "private":
                    access = UploadedFile.Access.PRIVATE
                case "members_only":
                    access = UploadedFile.Access.MEMBERS_ONLY
                case _:
                    access = UploadedFile.Access.PUBLIC

            uploaded_file = UploadedFile(file=file, upload_type=UploadedFile.UploadType.API, uploader=user, persistent=persistent, featured=featured, access=access)
            uploaded_file.set_expiration(months=3)
            uploaded_file.save()
            url = f"https://{request.get_host()}/{uploaded_file.slug}"
        except Exception as e:
            return JsonResponse({
                "status": 500,
                "data": {
                    "error": f'500 - Internal Server Error Occurred! Error: {e}',
                }
            }, status=418) # 418 I'm a teapot (Internal Server Error - Teapot error thrown to avoid Cloudflare thinking there is a server connection issue)

        return JsonResponse({
                "status": 200,
                "data": {
                    "url": url,
                    "thumbnail_url": f"{url}/thmb/",
                    "deletion_url": f"https://{request.get_host()}/uploads/{uploaded_file.slug}/delete/"
                }
            }, status=200) # 200 OK
    else:
        return JsonResponse({
                "status": 404,
                "data": {
                    "error": '404 - Not Found. No file was provided!',
                }
            }, status=404) # 404 Not Found
    
def handle_email_upload(request: HttpRequest):
    # TODO need to work out how to do this so that the email server and web server can be seperate but still have an internal auth system or maybe just use API upload view
    return JsonResponse({
                "status": 501,
                "data": {
                    "error": '501 - Not Implemented',
                }
            }, status=501) # 501 Not Implemented

    file = request.FILES.get('uploaded_file')
    if file:
        uploaded_file = UploadedFile(file=file, upload_type=UploadedFile.UploadType.API, uploader=user)
        uploaded_file.set_expiration(months=12)
        uploaded_file.access = UploadedFile.Access.PRIVATE
        uploaded_file.save()
        url = f"https://{request.get_host()}/{uploaded_file.slug}"
        return JsonResponse({
                "status": 200,
                "data": {
                    "url": url,
                }
            }) # 200 OK
    else:
        return JsonResponse({
                "status": 404,
                "data": {
                    "error": '404 - Not Found. No file was provided!',
                }
            }, status=404) # 404 Not Found

@login_required # To prevent unauthorized uploads we require a logged in user
def handle_manual_upload(request: HttpRequest):
    try:
        user = ApiUser.objects.get(pk=request.user.pk)
    except ObjectDoesNotExist:
        return HttpResponse("Error: The currently logged in user does not exist?!", status=400) # 400 Bad Request

    # Handle manual file upload
    if request.method == 'POST':
        form = UploadedFileForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = UploadedFile(file=request.FILES['file'], upload_type=UploadedFile.UploadType.MANUAL, uploader=user)
            if form.data.get('expiration'):
                uploaded_file.expiration_date = form.data.get('expiration')
            else:
                uploaded_file.set_expiration(months=3)
            if form.data.get('persistent') == 'on':
                uploaded_file.set_persistent()

            if form.data.get('featured') == 'off':
                uploaded_file.featured=False
            else:
                uploaded_file.featured=True
        
            uploaded_file.save()
            
            # Reload the page with the success alert
            form = UploadedFileForm()
            return render(request=request, template_name="filehost/manual_upload.html", context={'form': form, 'uploaded_file_slug': uploaded_file.slug}) # 200 OK   # 302 Found
        else:
            #serve the manual file upload page
            return render(request=request, template_name="filehost/manual_upload.html", context={'form': form, }) # 200 OK
    else:
        form = UploadedFileForm() # A new, empty, unbound form
        #serve the manual file upload page
        return render(request=request, template_name="filehost/manual_upload.html", context={'form': form,}) # 200 OK
    

##################################################
#                File Fetching                   #
##################################################


def fetch_file(request: HttpRequest, slug):
    # Redirects to formatted view, this helps to make link shorter but also add the /v/ on the end for viewing


    # status, uploaded_file = check_uploaded_file(slug)
    # if status is not None:
    #     return status
    # device = DeviceDetector(request.META['HTTP_USER_AGENT']).parse()
    # if device.client_type() != "browser": #  and (uploaded_file.file_type in UploadedFile.FileType.RAW_VIEWING or uploaded_file.mime_type == "application/pdf")
    #     return fetch_file_raw(request=request, slug=uploaded_file.slug)
    
    return redirect("filehost:fetch-file-formatted", slug=slug) # 302 Found

def fetch_file_formatted(request: HttpRequest, slug): 
    status, uploaded_file = check_uploaded_file(slug, request)
    if status is not None:
        return status
    context = {'uploaded_file': uploaded_file}
    if uploaded_file.file_type == UploadedFile.FileType.TEXT:
        f = open(uploaded_file.file.path, 'r')
        lines = f.readlines(512000)
        f.close()
        if uploaded_file.file.size >= 512000:
            messages.warning(request, "This file is larger than 5MB. The preview has been limited.")
        context['text_file_lines'] = lines
    if uploaded_file.can_be_managed_by(request.user):
        context['authorized'] = True
    else:
        context['authorized'] = False
    return render(request=request, template_name="filehost/formatted_view.html", context=context) # 200 OK

def fetch_file_email(request: HttpRequest, slug): # TODO Email View
    status, uploaded_file = check_uploaded_file(slug, request)
    if status is not None:
        return status
    return HttpResponse(status=501) # 501 Not Implemented

    
def fetch_file_download(request: HttpRequest, slug):
    status, uploaded_file = check_uploaded_file(slug, request)
    if status is not None:
        return status
    context = {'uploaded_file': uploaded_file}
    if uploaded_file.file_type == UploadedFile.FileType.TEXT:
        f = open(uploaded_file.file.path, 'r')
        lines = f.readlines(512000)
        f.close()
        if uploaded_file.file.size >= 512000:
            messages.warning(request, "This file is larger than 5MB. The preview has been limited.")
        context['text_file_lines'] = lines
    return render(request=request, template_name="filehost/download.html", context=context) # 200 OK

def download_file_raw(request: HttpRequest, slug):
    status, uploaded_file = check_uploaded_file(slug, request)
    if status is not None:
        return status
    return FileResponse(open(uploaded_file.file.path, "rb"), as_attachment=True) # 200 OK



def fetch_file_raw(request: HttpRequest, slug):
    status, uploaded_file = check_uploaded_file(slug, request, display_messages=False)
    if status is not None:
        return status
    return FileResponse(open(uploaded_file.file.path, "rb"), as_attachment=False) # 200 OK

def fetch_file_thumbnail(request: HttpRequest, slug):
    status, uploaded_file = check_uploaded_file(slug, request, localise=False, display_messages=False)
    if status is not None:
        return status
    if uploaded_file.has_thumbnail:
        return FileResponse(open(uploaded_file.thumbnail.path, "rb"), as_attachment=False) # 200 OK
    else:
        return HttpResponseNotFound("This Uploaded File does not have a thumbnail associated with it!") # 302 Found


##################################################
#                   Oembed API                   #
##################################################

# http://flickr.com/services/oembed?url=http%3A//flickr.com/photos/bees/2362225867/&maxwidth=300&maxheight=400&format=json
def handle_oembed(request: HttpRequest):
    if not request.method == 'GET':
        return HttpResponseNotAllowed("GET is the only supported method for the oembed handler!")  # 405 Not Allowed
    
    url = request.GET.get('url', '')
    max_width = request.GET.get('maxwidth', 0)
    max_height = request.GET.get('maxheight', 0)
    resp_format = request.GET.get('format', 'json').lower()
    referrer = request.GET.get('referrer', '')
    
    # Get the uploaded file by the slug in the url, if it cannot be found return 404 as per oembed specs    
    slug = os.path.basename(os.path.normpath(url))
    status, uploaded_file = check_uploaded_file(slug, request)
    if status is not None:
        return status
    
    # Ensure that the max_width and max_height are valid integers before continuing, 
    # if not then return 400 'Bad Request' to indicate we cannot process the request due to a client error
    try:
        max_width = int(max_width)
    except:
        return HttpResponse(reason="max_width is not a valid integer!", status=400) # 400 Bad Request
    try:
        max_height = int(max_height)
    except:
        return HttpResponse(reason="max_height is not a valid integer!", status=400) # 400 Bad Request

    if resp_format == 'json':
        status, resp = oembed.build_oembed_json(request, uploaded_file, max_width, max_height, referrer)
        if status is not None:
            return status
        else:
            return HttpResponse(content=resp, content_type='application/json', status=200) # 200 OK

    if resp_format == 'xml':
        status, resp = oembed.build_oembed_xml(request, uploaded_file, max_width, max_height, referrer)
        if status is not None:
            return status
        return HttpResponse(content=resp, content_type='text/xml', status=200) # 200 OK