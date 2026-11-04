from django.conf import settings
from storages.backends.s3 import S3Storage


class ProxiedS3Storage(S3Storage):
    """S3 storage for a private bucket: files are served through Django's
    /media/ route (cms.views.media) instead of public S3 URLs, so the bucket
    never needs public access."""

    def url(self, name, parameters=None, expire=None, http_method=None):
        return settings.MEDIA_URL_PATH + name.lstrip("/")
