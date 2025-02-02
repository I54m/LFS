from django.http import HttpRequest
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from .models import UploadedFile
from PIL import Image
from dicttoxml import dicttoxml
import json 

PROVIDER_NAME = "i54m"
PROVIDER_URL = "https://i54m.com"

AUTHOR_NAME = "lfs.i54m.com"
AUTHOR_URL = "https://lfs.i54m.com"

CACHE_AGE = 3600

CACHED_OEMBED_DICT = {
    "slug": ("dict_response", "last_accessed")
}

# {
#    "version": "1.0",
#    "type": "rich",

#    "provider_name": "FWD:Everyone",
#    "provider_url": "https://www.fwdeveryone.com"

#    "author_name": "Alex Krupp",
#    "author_url": "https://www.fwdeveryone.com/u/alex3917",

#     "html": "<iframe src=\"https://oembed.fwdeveryone.com?thread-id=e8RFukWTS5Wo54fBNbZ2yQ\" width=\"700\" height=\"825\" scrolling=\"yes\" frameborder=\"0\" allowfullscreen></iframe>",
#     "width": 700,
#     "height": 825,

#     "thumbnail_url": "https://ddc2txxlo9fx3.cloudfront.net/static/fwd_media_preview.png",
#     "thumbnail_width": 280,
#     "thumbnail_height": 175,

#     "referrer": "",
#     "cache_age": 3600,        
# }

# {
# 	"version": "1.0",
# 	"type": "photo",
# 	"width": 240,
# 	"height": 160,
# 	"title": "ZB8T0193",
# 	"url": "http://farm4.static.flickr.com/3123/2341623661_7c99f48bbf_m.jpg",
# 	"author_name": "Bees",
# 	"author_url": "http://www.flickr.com/photos/bees/",
# 	"provider_name": "Flickr",
# 	"provider_url": "http://www.flickr.com/"
# }

# {
#   "version": "1.0",
#   "type": "rich",
#   "provider_name": "Imgur",
#   "provider_url": "https://imgur.com",
#   "width": 540,
#   "height": 500,
#   "html": "
# <blockquote class=\"imgur-embed-pub\" lang=\"en\" data-id=\"EkJOFLl\">
#   <a href=\"https://imgur.com/EkJOFLl\">15th link in the description.</a>
# </blockquote>
# <script async src=\"//s.imgur.com/min/embed.js\" charset=\"utf-8\"></script>
# ",
#   "author_name": "TheOneThatGotBanned",
#   "author_url": "https://imgur.com/user/TheOneThatGotBanned"
# }

# TODO oembed other file types than just video and image
def build_oembed_dict(request: HttpRequest, uploaded_file: UploadedFile, max_width, max_height, referrer=""):

    # Check cache for response and if response is cached then retrun the cached response and update last_accessed
    if uploaded_file.slug in CACHED_OEMBED_DICT.keys():
        resp, last_accessed = CACHED_OEMBED_DICT[uploaded_file.slug]
        CACHED_OEMBED_DICT[uploaded_file.slug] = (resp, timezone.now())
        return None, resp
    
    # Response is not cached, create a new one...

    oembed_response = {
        "version": "1.0",
        "provider_name": f"{PROVIDER_NAME}",
        "provider_url": f"{PROVIDER_URL}",
        "author_name": f"{AUTHOR_NAME}",
        "author_url": f"{AUTHOR_URL}",
        "referrer": f"{referrer}",
        "title": f"{uploaded_file.slug}",
        "cache_age": f"{CACHE_AGE}",
    }
    
    match uploaded_file.file_type:

        case UploadedFile.FileType.IMAGE:
            oembed_response["type"] = "photo"
            img = Image.open(uploaded_file.file.path)
            img_width, img_height = img.size
            
            if img_width > max_width or img_height > max_height:
                # Resize image and save to a different temp location?
                width = max_width
                height = max_height
                
            if max_width == 0:
                width = img_width
            if max_height == 0:
                height = img_height

            # absolute_url = request.build_absolute_uri(uploaded_file.file.url)

            oembed_response["url"] = f"{request.build_absolute_uri(uploaded_file.file.url)}"
            # oembed_response["html"] = f'<img src="{absolute_url}" alt="{uploaded_file.slug}" width="{width}" height="{height}">'
            oembed_response["width"] = f"{width}"
            oembed_response["height"] = f"{height}"

            # thumb_width, thumb_height = uploaded_file.thumbnail.size

            oembed_response["thumbnail_url"] = f"https://{request.get_host()}/{uploaded_file.slug}/thmb/"
            oembed_response["thumbnail_width"] = f"{uploaded_file.thumbnail.width}"
            oembed_response["thumbnail_height"] = f"{uploaded_file.thumbnail.height}"

            img.close()

        case UploadedFile.FileType.VIDEO:
            oembed_response["type"] = "video"
            # TODO oembed video

        case _:
            # Default type. If the uploaded_file is not an image or video we will just link to it
            oembed_response["type"] = "link"

    # Cache the oembed response then return the response
    CACHED_OEMBED_DICT[uploaded_file.slug] = (oembed_response, timezone.now())
    return None, oembed_response




def build_oembed_json(request: HttpRequest, uploaded_file: UploadedFile, max_width, max_height, referrer=""):
    status, dictionary = build_oembed_dict(request, uploaded_file, max_width, max_height, referrer)
    # Check status and return if there was an error
    if status is not None:
        return status, None
    # Convert dict to JSON string then return
    return None, json.dumps(dictionary, cls=DjangoJSONEncoder)
    

def build_oembed_xml(request: HttpRequest, uploaded_file: UploadedFile, max_width, max_height, referrer=""):
    status, dictionary = build_oembed_dict(request, uploaded_file, max_width, max_height, referrer)
    # Check status and return if there was an error
    if status is not None:
        return status, None
    # convert dictionary to XML String then return
    return None, dicttoxml(dictionary, custom_root="oembed", attr_type=False)