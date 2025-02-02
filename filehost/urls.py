from django.urls import path

from . import views

app_name = "filehost"

urlpatterns = [
    path("", views.homepage, name="homepage"),

    ##### User Upload Management #####
    path("uploads/", views.list_uploads, name="list-uploads"),
    path("uploads/<slug:slug>/", views.manage_upload, name="manage-upload"),
    # path("uploads/<slug:slug>/delete/", views.delete_upload, name="delete-upload"),
    path("uploads/<slug:slug>/delete/", views.DeleteUploadClass.as_view(), name="delete-upload"),
    path("uploads/<slug:slug>/update/", views.update_upload, name="update-upload"),
    # TODO Archive/Localise upload view?

    
    ##### File upload handlers #####
    path("email-upload/", views.handle_email_upload, name="email-upload"),
    path("api-upload/", views.handle_api_upload, name="api-upload"),
    path("manual-upload/", views.handle_manual_upload, name="manual-upload"),
    
    ##### Oembed Integration #####
    path("oembed", views.handle_oembed, name="oembed"),

    #####  Fetching Files  #####
    path("<slug:slug>/", views.fetch_file, name="fetch-file"),
    path("<slug:slug>/v/", views.fetch_file_formatted, name="fetch-file-formatted"),
    path("<slug:slug>/e/", views.fetch_file_email, name="fetch-file-email"),
    path("<slug:slug>/dl/", views.fetch_file_download, name="fetch-file-download"),
    path("<slug:slug>/dl-raw/", views.download_file_raw, name="download-file-raw"),
    path("<slug:slug>/raw/", views.fetch_file_raw, name="fetch-file-raw"),
    path("<slug:slug>/thmb/", views.fetch_file_thumbnail, name="fetch-file-thumbnail"),


]