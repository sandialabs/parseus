// Browser-native version of the network analytics helpers. Dependencies are loaded
// as regular static assets by the templates instead of being imported by webpack.

function isIP(value) {
    if (!value) return false;

    const parts = value.split(".");
    const isIPv4 = parts.length === 4 && parts.every(part => {
        if (!/^\d+$/.test(part)) return false;
        const number = Number(part);
        return number >= 0 && number <= 255 && String(number) === part;
    });
    if (isIPv4) return true;

    if (!value.includes(":")) return false;
    try {
        const url = new URL(`http://[${value}]/`);
        return Boolean(url.hostname);
    } catch (_) {
        return false;
    }
}

// converts any input with class flatpickr to a flatpickr date time picker
function initializeFlatpickr(){
    flatpickr(".flatpickr", {
        enableTime: true,
        time_24hr: true,
        allowInput: true,
        enableSeconds: true,
        altInput: true,
        altFormat: "M j, Y H:i:S", // format to show user
        dateFormat: "Y-m-d\\TH:i:S", // format for elastic request
    });
}

// helper function to validate optional IP input and check if its empty
function ip_filter_validation(ip_filter_e) {
    if (isIP(ip_filter_e.value)) {
        ip_filter_e.classList.remove("invalid");
    } else if (!ip_filter_e.value) {
        ip_filter_e.classList.remove("invalid");
    } else {
        ip_filter_e.classList.add("invalid");
    };
}

function train_ip_filter_validation(){
    const trainIPFilter = document.getElementById("train_ip_filter");
    ip_filter_validation(trainIPFilter);
}

function predict_ip_filter_validation(){
    const predictIPFilter = document.getElementById("predict_ip_filter");
    ip_filter_validation(predictIPFilter);
}

function button_validation(StartDate, EndDate, IPFilter, Btn, checked){
    // check that ip filter is valid and dates are valid
    if (StartDate.classList.contains("invalid") ||
        EndDate.classList.contains("invalid") ||
        IPFilter.classList.contains("invalid") ||
        checked.length == 0) {
            Btn.disabled = true;
    } else {
        Btn.disabled = false;
    };
}

function train_button_validation() {
    let checked = [...document.querySelectorAll('input[name=train_box]:checked')].map(e => e.value);
    const trainStartDate = document.getElementById("train_start");
    const trainEndDate = document.getElementById("train_end");
    const trainIPFilter = document.getElementById("train_ip_filter");
    const trainBtn = document.getElementById("train_btn");
    button_validation(trainStartDate, trainEndDate, trainIPFilter, trainBtn, checked);
};

function network_predict_button_validation() {
    let active_btn = [...document.querySelectorAll('button.model-btn.active')].map(e => e.value);
    const predictStartDate = document.getElementById("predict_start");
    const predictEndDate = document.getElementById("predict_end");
    const predictIPFilter = document.getElementById("predict_ip_filter");
    const predictBtn = document.getElementById("predict_btn");
    button_validation(predictStartDate, predictEndDate, predictIPFilter, predictBtn, active_btn);
};

// helper function to validate start vs end date
function date_validation(start_date_e, end_date_e, dates_box) {
    // there are two input boxes per date box due to alternate flatpickr date showing
    // get all date inputs to apply validation correctly
    let inputs = dates_box.querySelectorAll(".flatpickr");
    if (new Date(start_date_e.value) > new Date(end_date_e.value)) {
        // invalidate date range
        inputs.forEach(function (currentValue) {
            currentValue.classList.add("invalid");
        });
    } else {
        // remove invalidation
        inputs.forEach(function (currentValue) {
            currentValue.classList.remove("invalid");
        });
    };
};

function train_date_validation(){
    const trainStartDate = document.getElementById("train_start");
    const trainEndDate = document.getElementById("train_end");
    const trainDates = document.getElementById("train_dates");
    date_validation(trainStartDate, trainEndDate, trainDates);
}

function predict_date_validation(){
    const predictStartDate = document.getElementById("predict_start");
    const predictEndDate = document.getElementById("predict_end");
    const predictDates = document.getElementById("predict_dates");
    date_validation(predictStartDate, predictEndDate, predictDates);
}


function setNetworkTrainListeners(){
    const trainStartDate = document.getElementById("train_start");
    const trainEndDate = document.getElementById("train_end");
    const trainIPFilter = document.getElementById("train_ip_filter");
    const trainBoxes = document.querySelectorAll("input[name=train_box]");
    trainEndDate.addEventListener("input", () => {
        train_date_validation()
        train_button_validation();
    });
    trainStartDate.addEventListener("input", () => {
        train_date_validation()
        train_button_validation();
    });
    // train: event listener to check that optional IP filter is valid or empty
    trainIPFilter.addEventListener("input", () => {
        train_ip_filter_validation()
        train_button_validation();
    });
    // train: event listener on input check boxes
    trainBoxes.forEach(function (checkbox) {
        checkbox.addEventListener("change", () => {
            train_button_validation();
        });
    });
}

function setNetworkPredictListeners(){
    const predictStartDate = document.getElementById("predict_start");
    const predictEndDate = document.getElementById("predict_end");
    const predictIPFilter = document.getElementById("predict_ip_filter");
    const predictBoxes = document.querySelectorAll("button[name=predict_model]");
    // predict: event listeners on input for validating start vs end date
    predictEndDate.addEventListener("input", () => {
        predict_date_validation()
        network_predict_button_validation()
    });
    predictStartDate.addEventListener("input", () => {
        predict_date_validation()
        network_predict_button_validation()
    });
    // predict: event listener to check that optional IP filter is valid or empty
    predictIPFilter.addEventListener("input", () => {
        predict_ip_filter_validation()
        network_predict_button_validation()
    });
    // predict: event listener on buttons
    predictBoxes.forEach(function (btn) {
        btn.addEventListener("click", () => {
            network_predict_button_validation()
        });
    });
}

window.network_analytics = {
    initializeFlatpickr,
    train_button_validation,
    network_predict_button_validation,
    setNetworkTrainListeners,
    setNetworkPredictListeners,
};
