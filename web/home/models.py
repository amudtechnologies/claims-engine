from django.db import models


class CompanyProfile(models.Model):
    """Amud Technologies' own registration and contact details — the system's
    transactional data about itself, not pipeline output.
    """

    name = models.CharField(max_length=255)
    nit = models.CharField(max_length=32, verbose_name="NIT")
    phone = models.CharField(max_length=32)
    email = models.EmailField()
    address = models.CharField(max_length=255)
    description = models.TextField()

    class Meta:
        verbose_name = "company profile"
        verbose_name_plural = "company profile"

    def __str__(self) -> str:
        return self.name
