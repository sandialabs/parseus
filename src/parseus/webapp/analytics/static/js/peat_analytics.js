const peat_analytics = {
  // helper function to enable/disable the submit button based on valid input
  button_validation: function (select, btn, checked_boxes) {
    if (select.value === "" || checked_boxes.length == 0) {
      btn.disabled = true;
    } else {
      btn.disabled = false;
    }
  },

  button_validation_active: function (select, btn, active) {
    if (select.value === "" || active === null) {
      btn.disabled = true;
    } else {
      btn.disabled = false;
    }
  },

  peat_train_button_validation: function () {
    let checked = [
      ...document.querySelectorAll("input[name=train_box]:checked"),
    ].map((e) => e.value);
    const trainSelect = document.getElementById("trainSelect");
    const trainBtn = document.getElementById("train_btn");
    peat_analytics.button_validation(trainSelect, trainBtn, checked);
  },

  peat_predict_button_validation: function () {
    let selectedModel = document.querySelector("button.model-btn.active");
    const predictSelect = document.getElementById("predictSelect");
    const predictBtn = document.getElementById("predict_btn");
    peat_analytics.button_validation_active(predictSelect, predictBtn, selectedModel);
  },

  // Function to fetch selectable PEAT datasets from the analytics server.
  // Analytics exposes its own endpoint that delegates to whatever data-source
  // provider serves PEAT output, so this does not call into the PEAT app.
  fetchFolders: function (folderSelectId) {
    fetch("/analytics/peat_datasets/", {
      method: "GET",
      headers: {
        "Content-Type": "application/json/",
        "X-CSRFToken": $("input[name=csrfmiddlewaretoken]").val(),
      },
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error("Network response was not ok");
        }
        return response.json();
      })
      .then((folders) => {
        const folderSelect = document.getElementById(folderSelectId);
        folderSelect.innerHTML = '<option value="">--Select a folder--</option>';

        folders.forEach((folder) => {
          const option = document.createElement("option");
          option.value = folder;
          option.textContent = folder;
          folderSelect.appendChild(option);
        });
      })
      .catch((error) => {
        console.error("Error fetching folders:", error);
        document.getElementById(folderSelectId).innerHTML =
          '<option value="">--Error loading folders--</option>';
      });
  },

  setPeatTrainListeners: function () {
    const trainBoxes = document.querySelectorAll("input[name=train_box]");
    const trainSelect = document.getElementById("trainSelect");
    trainBoxes.forEach(function (checkbox) {
      checkbox.addEventListener("change", () => {
        peat_analytics.peat_train_button_validation();
      });
    });
    trainSelect.addEventListener("change", () => {
      peat_analytics.peat_train_button_validation();
    });
  },

  setPeatPredictListeners: function () {
    const predictSelect = document.getElementById("predictSelect");
    predictSelect.addEventListener("change", () => {
      peat_analytics.peat_predict_button_validation();
    });
  },
};

peat_analytics.peat_train_button_validation();
window.peat_analytics = peat_analytics;
