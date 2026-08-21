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
