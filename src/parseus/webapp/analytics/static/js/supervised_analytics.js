const supervised_analytics = {
  // Shared by predictSupervised: addEventListener no-ops on a repeated reference,
  // so reusing this named function avoids stacking a new listener per predict click.
  warnBeforeUnload: function (e) {
    e.preventDefault();
  },

  update_trained_models: function ( analytic_type_str ) {
    let url = "/analytics/get_models/" + analytic_type_str;
    let headers = { "X-Csrftoken": $("input[name=csrfmiddlewaretoken]").val() };
    
    const trainedModels = document.getElementById("trained_models_box");
    const predictBtn = document.getElementById("predict_btn");
    $.ajax({
      type: "GET",
      url: url,
      headers: headers,
      success: function (data) {
        trainedModels.innerHTML = data;
        // localize the "Created at" timestamps now in the DOM
        parseusDatetime.hydrateTimestamps(trainedModels);
        predictBtn.disabled = true;
        // re-attach listeners lost when the box's HTML was replaced above
        let predict = document.querySelectorAll("button[name=predict_model]");
        analytics.add_on_model_click_btn();
        predict.forEach(function (btn) {
          btn.addEventListener("click", function() {
            const analytic_type = analytic_type_str.split(",")
            if (analytic_type.includes('NetworkSupervised')) {
              network_analytics.network_predict_button_validation();
            }
          });
        });
      },
      error: function (response, textStatus, exception) {
        console.error(
          `${response.status} Error updating trained models box: ${response.responseText}`
        );
      },
    });
  },

  predictSupervised: function (body) {
    let url = "/analytics/predict_model/";
    const databox = document.getElementById("data_box");
    const outidx = document.getElementById("outgoing_idx");
    const pushResultsBtn = document.getElementById("push_results_btn");
    // show spinner
    $("#spinner").removeClass("invisible");

    $.ajax({
      type: "POST",
      url: url,
      data: body,
      success: function (data) {
        toastSuccess(`Successfully predicted model`, 7000);
        // remove spinner if it was showing
        $("#spinner").addClass("invisible");

        databox.innerHTML = `
                    <pre class="overflow-visible"><code>${JSON.stringify(
                      data.alerts,
                      null,
                      2
                    )}</code></pre>
                `;

        outidx.value = data.outidx;
        pushResultsBtn.classList.remove("disabled");
      },
      error: function (response) {
        // remove spinner if it was showing
        $("#spinner").addClass("invisible");
        toastError(`${response.status} Error: ${response.responseText}`, 10000);
        console.error(`${response.status} Error: ${response.responseText}`);
      },
    });

    // Warn before leaving once a prediction has been run (there would be unsaved results).
    window.addEventListener("beforeunload", supervised_analytics.warnBeforeUnload);
  },

  trainSupervised: function (body, model_type) {
    let url = "/analytics/train_model/";
    const trainBtn = document.getElementById("train_btn");
    // show spinner
    $("#spinner").removeClass("invisible");

    $.ajax({
      type: "POST",
      url: url,
      data: body,
      success: function (data) {
        // loop through each result from training
        $.each(data, function (i, v) {
          if (v.status == "success") {
            toastSuccess(`Successfully trained ${v.model}`, 7000);
          } else {
            toastError(`Failed training ${v.model}: ${v.error}`, 10000);
            console.error(`Failed training ${v.model}: ${v.error}`);
          }
        });
        // update trained models
        supervised_analytics.update_trained_models(model_type);
        // remove spinner if it was showing
        $("#spinner").addClass("invisible");
        // disable train button
        trainBtn.disabled = true;
        // uncheck all the boxes
        analytics.uncheckAll();
      },
      error: function (response) {
        // remove spinner if it was showing
        $("#spinner").addClass("invisible");
        toastError(`${response.status} Error: ${response.responseText}`, 10000);
        console.error(`${response.status} Error: ${response.responseText}`);
      },
    });
  },

  // pop up delete trained model modal
  delete_trained_model: function (name, pk) {
    // fill out the necessary values in the modal
    $("#delete-model-modal input[name=delete-this-model]").val(name);
    $("#delete-model-modal input[name=delete-trained-model-pk]").val(pk);
    // show the modal
    deleteModal.show();
  },

  Train: function(analytic_type_str) {
    let data = {}
    let checkedBoxes = [...document.querySelectorAll("input[name=train_box]:checked"),
    ].map((e) => e.value);
    const analytic_type = analytic_type_str.split(",");
    const trainAppend = document.getElementById("train_append");
    if (analytic_type.includes('NetworkSupervised')) {
      const trainIPFilter = document.getElementById("train_ip_filter");
      const trainStartDate = document.getElementById("train_start");
      const trainEndDate = document.getElementById("train_end");
      data = {
        analytic_pks: checkedBoxes,
        user_save: trainAppend.value,
        ip_filter: trainIPFilter.value,
        start_date: trainStartDate.value,
        end_date: trainEndDate.value,
        csrfmiddlewaretoken: $('input[name=csrfmiddlewaretoken]').val(),
      };
    }
    else if (analytic_type.includes('PeatSupervised')) {
      const trainSelect = document.getElementById("trainSelect");
      data = {
        analytic_pks: checkedBoxes,
        user_save: trainAppend.value,
        index_name: trainSelect.value,
        csrfmiddlewaretoken: $("input[name=csrfmiddlewaretoken]").val(),
      };
    }
    supervised_analytics.trainSupervised(data, analytic_type_str);
  },

  Predict: function(analytic_type_str) {
    let model = document.querySelector("button.model-btn.active").value;
    let data = {}
    const analytic_type = analytic_type_str.split(",");
    if (analytic_type.includes('NetworkSupervised')) {
      const predictIPFilter = document.getElementById("predict_ip_filter");
      const predictStartDate = document.getElementById("predict_start");
      const predictEndDate = document.getElementById("predict_end");
      data = {
        model_pk: model,
        ip_filter: predictIPFilter.value,
        start_date: predictStartDate.value,
        end_date: predictEndDate.value,
        csrfmiddlewaretoken: $('input[name=csrfmiddlewaretoken]').val(),
      }
    }
    else if (analytic_type.includes('PeatSupervised')) {
      const predictSelect = document.getElementById("predictSelect");
      data = {
        model_pk: model,
        index_name: predictSelect.value,
        csrfmiddlewaretoken: $("input[name=csrfmiddlewaretoken]").val(),
      }
    }
    supervised_analytics.predictSupervised(data);
  }
};

window.supervised_analytics = supervised_analytics;
