from django import forms
from peat import module_api

from .models import PeatConfig, PeatDevice


class PeatBuilderForm(forms.ModelForm):
    class Meta:
        model = PeatConfig
        fields = [
            "name",
            "description",
            "author",
            "debug",
            "intensive_scan",
            "assume_online",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.TextInput(attrs={"class": "form-control"}),
            "author": forms.TextInput(attrs={"class": "form-control"}),
            "debug": forms.Select(attrs={"class": "form-select"}),
            "intensive_scan": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "assume_online": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        # Check if an instance is provided
        instance = kwargs.get("instance", None)
        super().__init__(*args, **kwargs)

        if instance:  # If updating, remove the special_field
            self.fields.pop("filename")

    def clean_debug(self):
        debug = self.cleaned_data.get("debug")
        if not (0 <= debug <= 4):
            raise forms.ValidationError("Debug must be between 0 and 4.")
        return debug


class PeatConfigForm(forms.ModelForm):
    class Meta:
        model = PeatConfig
        fields = [
            "filename",
            "name",
            "description",
            "author",
            "debug",
            "intensive_scan",
            "assume_online",
        ]
        widgets = {
            "filename": forms.FileInput(attrs={"class": "form-control"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.TextInput(attrs={"class": "form-control"}),
            "author": forms.TextInput(attrs={"class": "form-control"}),
            "debug": forms.Select(attrs={"class": "form-select"}),
            "intensive_scan": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "assume_online": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        # Check if an instance is provided
        instance = kwargs.get("instance", None)
        super().__init__(*args, **kwargs)

        if instance:  # If updating, remove the special_field
            self.fields.pop("filename")

    def clean_debug(self):
        debug = self.cleaned_data.get("debug")
        if not (0 <= debug <= 4):
            raise forms.ValidationError("Debug must be between 0 and 4.")
        return debug


class PeatDeviceForm(forms.ModelForm):
    CHOICES = [(x.lower(), x) for x in module_api.names]
    peat_module = forms.ChoiceField(
        choices=CHOICES, widget=forms.Select(attrs={"class": "form-select"})
    )

    class Meta:
        model = PeatDevice
        fields = [
            "label",
            "comment",
            "ip",
            "hostname",
            "mac",
            "serial_port",
            "name",
            "peat_module",
            "options",
        ]
        widgets = {
            "label": forms.TextInput(attrs={"class": "form-control"}),
            "comment": forms.TextInput(attrs={"class": "form-control"}),
            "ip": forms.TextInput(attrs={"class": "form-control"}),
            "hostname": forms.TextInput(attrs={"class": "form-control"}),
            "mac": forms.TextInput(attrs={"class": "form-control"}),
            "serial_port": forms.TextInput(attrs={"class": "form-control"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            # "peat_module" widget is set on the field above, not here.
            "options": forms.Textarea(attrs={"class": "form-control"}),
        }
