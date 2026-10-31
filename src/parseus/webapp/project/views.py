# views.py
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.template import loader
from django.views import View

from parseus.datastore.client import DataStore

from .forms import DataStoreForm


class IncorrectDatastoreError(Exception):
    pass


def home(request):
    template = loader.get_template("home.html")
    return HttpResponse(template.render(request=request))


def _get_database_client(request):
    datastore_host = request.session.get("datastore_host", settings.DEFAULT_DATASTORE)
    datastore_type = request.session.get("datastore_type", "elasticsearch")
    datastore_authenticate = request.session.get("datastore_authenticate", False)
    datastore_username = request.session.get("datastore_username", "")
    encrypted_password = request.session.get("datastore_password", "")
    if datastore_authenticate and datastore_username and encrypted_password:
        # Decrypt password
        seasoned_password = settings.CIPHER.decrypt(encrypted_password).decode()
        _, _, salt, _ = request.user.password.split("$")
        datastore_password = seasoned_password.replace(salt, "")
        auth = (datastore_username, datastore_password)
        client = DataStore(
            datastore_host,
            basic_auth=auth,
            base=datastore_type,
        )
    else:
        client = DataStore(datastore_host, base=datastore_type)
    return client


def get_database_url(request):
    datastore_host = request.session.get("datastore_host", settings.DEFAULT_DATASTORE)
    datastore_authenticate = request.session.get("datastore_authenticate", False)
    datastore_username = request.session.get("datastore_username", "")
    encrypted_password = request.session.get("datastore_password", "")
    if datastore_authenticate and datastore_username and encrypted_password:
        # Decrypt password
        seasoned_password = settings.CIPHER.decrypt(encrypted_password).decode()
        _, _, salt, _ = request.user.password.split("$")
        datastore_password = seasoned_password.replace(salt, "")
        base, sep, hostname = datastore_host.partition("//")
        return f"{base}{sep}{datastore_username}:{datastore_password}@{hostname}"
    return datastore_host


def get_database_status(request):
    message = ""
    datastore_authenticate = request.session.get("datastore_authenticate", False)
    datastore_username = request.session.get("datastore_username", "")

    # Test connection to the host
    try:
        client = _get_database_client(request)
        client.info()
        client_str = str(client)[1:-1]
        message = f"Connected to {client_str}"
        if datastore_authenticate and datastore_username:
            message += f" as {datastore_username}"
        status = True
    except Exception as e:
        message = f"Failed to connect to database: {type(e).__name__}"
        status = False
    response_data = {
        "status": status,
        "message": message,
    }
    return JsonResponse(response_data)


class CustomLoginView(LoginView):
    def form_valid(self, form):
        login(self.request, form.get_user())
        return JsonResponse({"success": True})

    def form_invalid(self, form):
        return JsonResponse({"success": False, "message": "Invalid credentials."})


class DataStoreView(View):
    form = DataStoreForm
    http_method_names = ["post"]

    def post(self, request):
        form = self.form(request.POST)
        if form.is_valid():
            messages = []
            datastore_type = form.cleaned_data["datastore_type"]
            datastore_host = form.cleaned_data["datastore_host"]
            datastore_authenticate = form.cleaned_data["datastore_authenticate"]
            datastore_username = form.cleaned_data["datastore_username"]
            datastore_password = form.cleaned_data["datastore_password"]
            if datastore_authenticate:
                auth = (datastore_username, datastore_password)
                client = DataStore(
                    datastore_host,
                    basic_auth=auth,
                    base=datastore_type,
                )
            else:
                client = DataStore(datastore_host, base=datastore_type)

            # Encrypt the password with user salt
            _, _, salt, _ = request.user.password.split("$")
            seasoned_password = salt + datastore_password
            encrypted_password = settings.CIPHER.encrypt(
                seasoned_password.encode()
            ).decode()

            # Save the info to the user's session
            request.session["datastore_type"] = datastore_type
            request.session["datastore_host"] = datastore_host
            request.session["datastore_authenticate"] = datastore_authenticate
            request.session["datastore_username"] = datastore_username
            request.session["datastore_password"] = encrypted_password

            # Test connection to the host
            try:
                info = client.info()
                dist = info.get("version", {}).get("distribution", "").lower()
                if datastore_type == "opensearch":
                    if dist != "opensearch":
                        raise IncorrectDatastoreError
            except IncorrectDatastoreError as e:
                messages.append(
                    (
                        "warning",
                        f"{type(e).__name__}: Wrong datastore type possibly selected",
                    )
                )
            except Exception as e:
                messages.append(
                    ("error", f"{type(e).__name__}: Failed to connect to database")
                )

            # Convert elastic setting to JSON for response
            response_data = {"host": datastore_host, "messages": messages}
            # Return saved object in response
            return JsonResponse(response_data)
        return HttpResponseBadRequest(form.errors.as_json())
