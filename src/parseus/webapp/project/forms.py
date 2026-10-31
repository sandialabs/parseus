"""Forms accessible to the whole project."""

from django import forms


class DataStoreForm(forms.Form):
    DATASTORE_CHOICES = (
        ("elasticsearch", "Elasticsearch"),
        ("opensearch", "OpenSearch"),
    )
    datastore_host = forms.URLField(
        required=True, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    datastore_type = forms.ChoiceField(
        choices=DATASTORE_CHOICES, widget=forms.Select(attrs={"class": "form-select"})
    )
    datastore_authenticate = forms.BooleanField(
        required=False,
        initial=False,
        label="Use Authentication",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    datastore_username = forms.CharField(
        required=False,
        label="Datastore Username",
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "username"}
        ),
    )
    datastore_password = forms.CharField(
        required=False,
        label="Datastore Password",
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "password"}
        ),
    )
