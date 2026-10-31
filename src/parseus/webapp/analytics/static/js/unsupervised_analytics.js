const unsupervised_analytics = {
  Predict: function (analytic_type) {
    let checkedBoxes = [
      ...document.querySelectorAll("input[name=train_box]:checked"),
    ].map((e) => e.value);
    let url = "";
    let body = {};
    if (analytic_type == "NetworkUnsupervised") {
      body = {
        analytic_pks: checkedBoxes,
        ip_filter: trainIPFilter.value,
        start_date: trainStartDate.value,
        end_date: trainEndDate.value,
        csrfmiddlewaretoken: $("input[name=csrfmiddlewaretoken]").val(),
      };
      url = "/analytics/predict_network_unsupervised/";
    } 
    else if (analytic_type == "PeatUnsupervised") {
      body = {
        analytic_pks: checkedBoxes,
        index_name: trainSelect.value,
        csrfmiddlewaretoken: $("input[name=csrfmiddlewaretoken]").val(),
      };
      url = "/analytics/predict_peat_unsupervised/";
    }
    // show spinner
    $("#spinner").removeClass("invisible");
    $.ajax({
      url: url,
      method: "POST",
      data: body,
      success: function (data) {
        $("#spinner").addClass("invisible");
        // the view returns a full accordion fragment to render the new alerts
        $("#accordionAlerts").replaceWith(data);
        document.getElementById("push_unsupervised_results_btn").classList.remove("disabled");
        toastSuccess(`Successfully predicted model(s)`, 7000);
      },
      error: function (response) {
        $("#spinner").addClass("invisible");
        console.error(`${response.status} Error: ${response.responseText}`);
        toastError(`${response.status} Error: ${response.responseText}`, 10000);
      },
    });
  },

  push_results: function () {
    let url = "/analytics/push_results/";
    const outidx = document.getElementById("outgoing_idx");
    const analyticAlerts = JSON.parse(document.getElementById("unsupervised-alerts-json").textContent);
    const combined = Object.values(analyticAlerts).flat();
    let outgoing_idx = outidx.value;
    let data = {
      es_data: JSON.stringify(combined),
      outidx: outgoing_idx,
      csrfmiddlewaretoken: $("input[name=csrfmiddlewaretoken]").val(),
    };

    // show spinner
    $("#spinner").removeClass("invisible");

    $.ajax({
      type: "POST",
      url: url,
      data: data,
      success: function (response) {
        // remove spinner if it was showing
        $("#spinner").addClass("invisible");
        toastSuccess("Successfully pushed results to elastic", 7000);
      },
      error: function (response) {
        // remove spinner if it was showing
        $("#spinner").addClass("invisible");
        toastError(`${response.status} Error: ${response.responseText}`, 10000);
        console.error(`${response.status} Error: ${response.responseText}`);
      },
    });
  },
};

$("#push_unsupervised_results_btn").on("click", unsupervised_analytics.push_results);
window.unsupervised_analytics = unsupervised_analytics;
