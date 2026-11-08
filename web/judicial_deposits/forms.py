from django import forms

from .models import ServiceRequest


class ServiceRequestForm(forms.ModelForm):
    """The short form behind "Quiero recuperarlo" and "Solicitar
    verificación". The document number, radar and claimable figures are set
    by the view, not submitted."""

    data_processing_consent = forms.BooleanField(
        required=True,
        error_messages={
            "required": "Debe autorizar el tratamiento de sus datos para enviar la solicitud."
        },
    )

    class Meta:
        model = ServiceRequest
        fields = [
            "request_type",
            "name",
            "email",
            "phone",
            "relationship",
            "data_processing_consent",
        ]
        widgets = {
            "request_type": forms.HiddenInput,
            "relationship": forms.RadioSelect,
            "name": forms.TextInput(attrs={"autocomplete": "name"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "phone": forms.TextInput(attrs={"autocomplete": "tel", "inputmode": "tel"}),
        }
        error_messages = {
            "name": {"required": "Escriba su nombre."},
            "email": {
                "required": "Escriba su correo.",
                "invalid": "Escriba un correo válido.",
            },
            "phone": {"required": "Escriba un teléfono de contacto."},
            "relationship": {"required": "Indique su relación con la identificación consultada."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Radio buttons, not a select: no "---------" blank choice.
        self.fields["relationship"].choices = ServiceRequest.Relationship.choices

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        if sum(character.isdigit() for character in phone) < 7:
            raise forms.ValidationError("Escriba un teléfono válido.")
        return phone
