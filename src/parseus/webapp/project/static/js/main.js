// Gets status of database connection
export function getDatabaseStatus() {
  // Don't poll from a backgrounded tab; the visibilitychange handler in
  // base.html refreshes immediately when the tab becomes visible again.
  if (document.hidden) return;

  const url = "/database/status/";
  fetch(url, {
    method: "POST",
    headers: {
      "X-CSRFToken": $("input[name=csrfmiddlewaretoken]").val(),
    },
  })
    .then((response) => {
      if (response.status !== 200) {
        throw new Error("Network response was not ok");
      }
      return response.json();
    })
    .then((data) => {
      updateDatastoreStatus(data.status == true);
    })
    .catch((error) => {
      console.error(
        "There was a problem with the fetch operation:",
        error.message
      );
      updateDatastoreStatus(false, "Status unavailable");
    });
}

// Last status that was written to the DOM. Re-applying an identical state would
// remove and re-add the status classes, which restarts the CSS animations on the
// status dot and can flash the chip for a frame.
let lastRenderedStatus = null;

function updateDatastoreStatus(isOnline, labelOverride = null) {
  const userButton = document.getElementById("user-console-button");
  const statusDot = document.getElementById("user-icon");
  const statusText = document.getElementById("database-status-text");

  if (!userButton || !statusDot) {
    return;
  }

  const statusClass = isOnline ? "is-datastore-online" : "is-datastore-offline";
  const statusLabel = labelOverride || (isOnline ? "Datastore live" : "Datastore offline");

  if (lastRenderedStatus === `${statusClass}|${statusLabel}`) {
    return;
  }
  lastRenderedStatus = `${statusClass}|${statusLabel}`;

  userButton.classList.remove("is-datastore-online", "is-datastore-offline");
  statusDot.classList.remove("is-datastore-online", "is-datastore-offline");

  userButton.classList.add(statusClass);
  statusDot.classList.add(statusClass);
  userButton.setAttribute("aria-label", `User menu. ${statusLabel}.`);

  if (statusText) {
    statusText.textContent = statusLabel;
  }
}

// Login modal
export function login_modal() {
  const loginModal = new bootstrap.Modal("#login-modal");
  loginModal.show();
}

// General settings modal
export function settings_modal() {
  bootstrap.Modal.getOrCreateInstance("#settings-modal").show();
}

// Activate tooltips
const tooltipTriggerList = document.querySelectorAll(
  '[data-bs-toggle="tooltip"]'
);
[...tooltipTriggerList].forEach(
  (tooltipTriggerEl) => new bootstrap.Tooltip(tooltipTriggerEl)
);

// Display a message to the user
function displayMessage(message) {
  const message_type = message[0];
  const message_value = message[1];
  switch (message_type) {
    case "error":
      toastError(message_value, 5000);
      break;
    case "success":
      toastSuccess(message_value, 5000);
      break;
    case "warning":
      toastWarning(message_value, 5000);
      break;
    default:
      toastInfo(message_value, 5000);
  }
}

// handle elastic modal form submission
function handleElasticSave(event) {
  event.preventDefault();
  const form = document.getElementById("elastic-form");
  // Validate inputs
  if (!form.checkValidity()) {
    $(form).addClass("was-validated");
    return;
  }

  // Form is valid
  $(form).removeClass("was-validated");
  $("#elastic-form input, #elastic-form select").removeClass("is-valid is-invalid");
  $("#elastic-form .invalid-feedback").html("");

  // Disable button and make it a spinner
  let saveButton = $("#elastic-form-save");
  const saveButtonDefault = saveButton.html();
  saveButton.attr("disabled", true);
  saveButton.html(`
        <span class="spinner-border spinner-border-sm" aria-hidden="true"></span>
        <span role="status">Checking connection...</span>
    `);
  // Submit form
  $.ajax({
    method: "POST",
    url: "/database/",
    data: $(form).serialize(),
    timeout: 10000,
    success: (data, textStatus, jqXHR) => {
      if (data.messages.length > 0) {
        data.messages.forEach(function (message) {
          displayMessage(message);
        });
      } else {
        toastSuccess("Saved Datastore settings", 3000);
        bootstrap.Modal.getOrCreateInstance("#settings-modal").hide();
        getDatabaseStatus();
        // Clear password field
        $("#id_datastore_password, #opensearch-password").val("");
        // Remove validation from fields
        $("#elastic-form input, #elastic-form select").removeClass("is-valid is-invalid");
      }

      // Work around a Bootstrap modal backdrop that can be left behind.
      const backdrop = document.querySelector(".modal-backdrop");
      if (backdrop) {
        backdrop.remove();
      }
    },
    error: (jqXHR, textStatus, errorThrown) => {
      let status = jqXHR.status;
      if (status == 400) {
        // bad request, update fields with error messages
        let response = JSON.parse(jqXHR.responseText);
        Object.keys(response).forEach((k) => {
          const message = response[k][0]["message"];
          const invalidMessage = $(`#elastic-${k}-invalid`);
          const field = $(`#elastic-${k}, #id_${k}, [name='${k}']`).first();

          // set invalid text
          invalidMessage.html(message);
          // mark field invalid
          field.addClass("is-invalid");
          // mark other fields valid (ignoring hidden fields)
          $("#elastic-form input:not(.is-invalid):not([type=hidden]), #elastic-form select:not(.is-invalid)").addClass(
            "is-valid"
          );
        });
      } else {
        // other error
        toastError(`Error ${status}: ${errorThrown}`, 5000);
      }
    },
    complete: () => {
      // reset button
      saveButton.attr("disabled", false);
      saveButton.html(saveButtonDefault);
    },
  });
}

function toggleOpenseachInput() {
  const checkbox = document.getElementById("id_datastore_authenticate");
  const inputs = document.querySelectorAll(
    "#opensearch-group input[type=text], #opensearch-group input[type=password]"
  );
  inputs.forEach((input) => {
    input.disabled = !checkbox.checked;
  });
  document.getElementById("os-username").hidden = !checkbox.checked;
  document.getElementById("os-password").hidden = !checkbox.checked;
}

function submitLogin(event) {
  event.preventDefault();
  const loginButton = document.getElementById("login-button");
  const loginMessage = document.getElementById("loginMessage");
  const loginButtonDefault = loginButton.innerHTML;

  loginButton.disabled = true;
  loginButton.innerHTML = `
    <span class="spinner-border spinner-border-sm" aria-hidden="true"></span>
    <span role="status">Unlocking workspace...</span>
  `;
  loginMessage.innerText = "";

  const formData = new FormData(this);

  fetch("/login/modal/", {
    method: "POST",
    body: formData,
    headers: {
      "X-Requested-With": "XMLHttpRequest",
    },
  })
    .then((response) => response.json())
    .then((data) => {
      if (data.success) {
        window.location.reload();
      } else {
        loginMessage.innerText = data.message;
        loginButton.disabled = false;
        loginButton.innerHTML = loginButtonDefault;
      }
    })
    .catch((error) => {
      console.error("Error:", error);
      loginMessage.innerText = "Something interrupted the sign-in handshake. Please try again.";
      loginButton.disabled = false;
      loginButton.innerHTML = loginButtonDefault;
    });
}

// Set active link
$(".nav-link")
  .filter((i, element) => element.pathname == window.location.pathname)
  .addClass("active");

// Set event listeners and run functions when module is imported
document
  .getElementById("sign-in-form")
  .addEventListener("submit", submitLogin);
document
  .getElementById("id_datastore_authenticate")
  .addEventListener("change", toggleOpenseachInput);
document
  .getElementById("elastic-form-save")
  .addEventListener("click", handleElasticSave);
toggleOpenseachInput();
