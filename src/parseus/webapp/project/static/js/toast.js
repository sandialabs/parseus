function createToast(bgType, messageType, message, length) {
  // bgType should be one of the bootstrap bg types (e.g. bg-primary, bg-success, bg-danger)
  let element = $(`
        <div class="toast" role="alert" aria-live="assertive" aria-atomic="true" data-bs-delay="${length}" style="max-height:200px;">
            <div class="toast-header ${bgType}">
              <strong class="me-auto">${messageType}</strong>
              <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
            <div class="toast-body">${message}</div>
        </div>
    `);
  $("#toasts").append(element);
  bootstrap.Toast.getOrCreateInstance(element).show();
}

function toastError(message, length) {
  createToast("bg-danger", "Error", message, length);
}

function toastSuccess(message, length) {
  createToast("bg-success", "Success", message, length);
}

function toastWarning(message, length) {
  createToast("bg-warning", "Warning", message, length);
}

function toastInfo(message, length) {
  createToast("bg-secondary", "Info", message, length);
}
