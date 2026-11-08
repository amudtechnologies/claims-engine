from django.db import models


class ClaimWindow(models.Model):
    """The 20-business-day claim window for one publication period's unclaimed
    deposits (Ley 1743 of 2014, Acuerdo PCSJA21-11731 of 2021 — see
    project-context.md §2). Dates are entered manually per period rather than
    computed from publication date + 20 business days, since that would need a
    Colombian holiday calendar and the actual publication date can drift from
    the nominal period.
    """

    period = models.CharField(max_length=16, unique=True, help_text="e.g. 2026-1")
    opens_on = models.DateField(null=True, blank=True)
    closes_on = models.DateField()

    class Meta:
        ordering = ["-period"]

    def __str__(self) -> str:
        return self.period


class ServiceRequest(models.Model):
    """A visitor asking us to collect ("Quiero recuperarlo") or verify
    ("Solicitar verificación") what this radar found for a document number.
    The claimable figures are recomputed server-side when the request is
    saved, never taken from the form, and kept as they stood at that moment.

    Holds contact data and a national ID next to money: admin-only, the
    restricted-access tier D23 requires (project-context.md §5).
    """

    class RequestType(models.TextChoices):
        COLLECTION = "collection", "Cobro"
        VERIFICATION = "verification", "Verificación"

    class Relationship(models.TextChoices):
        HOLDER = "holder", "Titular"
        REPRESENTATIVE = "representative", "Representante o apoderado"
        OTHER = "other", "Otro"

    document_number = models.CharField("identificación consultada", max_length=32)
    radar = models.CharField(max_length=64)
    request_type = models.CharField("tipo de solicitud", max_length=16, choices=RequestType)
    name = models.CharField("nombre", max_length=200)
    email = models.EmailField("correo")
    phone = models.CharField("teléfono", max_length=32)
    relationship = models.CharField(
        "relación con la identificación", max_length=16, choices=Relationship
    )
    data_processing_consent = models.BooleanField("autorización de tratamiento de datos")
    claimable_count = models.PositiveIntegerField("depósitos vigentes al solicitar")
    claimable_amount_cop = models.BigIntegerField("valor vigente al solicitar (COP)")
    created_at = models.DateTimeField("fecha", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "solicitud"
        verbose_name_plural = "solicitudes"

    def __str__(self) -> str:
        return f"{self.get_request_type_display()} · {self.document_number} · {self.name}"
