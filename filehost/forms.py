from django import forms
from filehost.models import UploadedFile

class UploadedFileForm(forms.Form):
    file = forms.FileField(
        label='Select a file',
        help_text='max. 42MB'
    )
    expiration = forms.DateTimeField(
        label='Define an expiration date (Optional)',
        help_text='YYYY-MM-DD',
        required=False
    )
    persistent = forms.BooleanField(
        label='File is persistent?',
        help_text='(file will not expire or be archived)',
        required=False
    )
    featured = forms.BooleanField(
        label='File can be featured?',
        help_text='(Featured files are displayed on homepage)',
        required=True,
        initial=True,
    )
    access = forms.ChoiceField(
        label='Access Privacy (Required)',
        help_text="Public=anyone can view; Members Only=only users with an acccount; Private=only you",
        initial=UploadedFile.Access.PUBLIC,
        choices=UploadedFile.Access.CHOICES,
        required=True

    )