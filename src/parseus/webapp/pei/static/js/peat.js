const peat = {
    getStatusIcons: function (status) {
        if (status === "done") {
            return '<span class="badge text-bg-success"><i class="bi-check2-circle me-1"></i>Done</span>';
        } else if (status === "running") {
            return '<span class="badge text-bg-primary"><i class="bi-arrow-clockwise me-1 rotate"></i>Running</span>';
        } else if (status === "started") {
            return '<span class="badge text-bg-secondary"><i class="bi-bus-front-fill me-1 pulse"></i>Starting soon</span>';
        } else if (status === "waiting") {
            return '<span class="badge text-bg-info"><i class="bi-hourglass-split me-1 pulse"></i>Waiting</span>';
        } else if (status === "error") {
            return '<span class="badge text-bg-danger"><i class="bi-x-circle me-1"></i>Error</span>';
        } else if (status === "stopped") {
            return '<span class="badge text-bg-warning"><i class="bi-stop-circle me-1"></i>Stopped</span>';
        } else {
            return '<span class="badge text-bg-dark"><i class="bi-question-circle me-1"></i>Unknown</span>';
        }
    },

    escapeHtml: function (value) {
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    },

    escapeAttribute: function (value) {
        return peat.escapeHtml(value);
    },

    // CSRF header pair used by every fetch() call in this file; token is read fresh each call.
    csrfHeaders: function () {
        return {
            'Content-Type': 'application/json',
            'X-CSRFToken': $('input[name=csrfmiddlewaretoken]').val()
        };
    },

    getDevices: function (devices) {
        const deviceList = Array.isArray(devices)
            ? devices.filter(device => device !== null && device !== undefined).map(device => String(device))
            : [];

        if (deviceList.length === 0) {
            return '<span class="text-body-secondary">No devices</span>';
        }

        const deviceCount = deviceList.length;
        const countLabel = deviceCount === 1 ? '1 device' : deviceCount + ' devices';
        const previewDevices = deviceList.slice(0, 3).map(device => peat.escapeHtml(device)).join(', ');
        const remainingCount = deviceCount - 3;
        const previewLabel = previewDevices + (remainingCount > 0 ? ' +' + remainingCount + ' more' : '');
        const deviceItems = deviceList
            .map(device => '<li><i class="bi-router me-2"></i><span>' + peat.escapeHtml(device) + '</span></li>')
            .join('');
        const popoverContent = '<div class="peat-devices-popover-content">'
            + '<div class="peat-devices-popover-help">Scroll to review all targets included in this run.</div>'
            + '<ul class="peat-devices-popover-list">' + deviceItems + '</ul>'
            + '</div>';

        return '<div class="peat-devices-cell">'
            + '<button type="button" class="btn btn-secondary btn-sm peat-devices-popover-toggle" '
            + 'data-bs-toggle="popover" data-bs-placement="auto" data-bs-trigger="click" data-bs-html="true" '
            + 'data-bs-custom-class="peat-devices-popover" data-bs-title="' + peat.escapeAttribute(countLabel) + '" '
            + 'data-bs-content="' + peat.escapeAttribute(popoverContent) + '" '
            + 'aria-label="Show ' + peat.escapeAttribute(countLabel) + '">'
            + '<i class="bi-hdd-network me-1"></i>' + peat.escapeHtml(countLabel)
            + '</button>'
            + '<span class="peat-devices-preview">' + previewLabel + '</span>'
            + '</div>';
    },

    getElementRoot: function (scope = document) {
        if (typeof scope === 'string') {
            return document.querySelector(scope);
        }
        return scope || document;
    },

    hideDevicePopovers: function () {
        document.querySelectorAll('.peat-devices-popover-toggle').forEach(popoverTriggerEl => {
            const popover = bootstrap.Popover.getInstance(popoverTriggerEl);
            if (popover) {
                popover.hide();
            }
        });
    },

    disposeDevicePopovers: function (scope = document) {
        const root = peat.getElementRoot(scope);
        if (!root) {
            return;
        }
        root.querySelectorAll('.peat-devices-popover-toggle').forEach(popoverTriggerEl => {
            const popover = bootstrap.Popover.getInstance(popoverTriggerEl);
            if (popover) {
                popover.dispose();
            }
        });
        document.querySelectorAll('.popover.peat-devices-popover').forEach(popoverEl => popoverEl.remove());
    },

    initializeDevicePopovers: function (scope = document) {
        const root = peat.getElementRoot(scope);
        if (!root) {
            return;
        }
        root.querySelectorAll('.peat-devices-popover-toggle').forEach(popoverTriggerEl => {
            bootstrap.Popover.getOrCreateInstance(popoverTriggerEl, {
                boundary: document.body,
                container: 'body',
                customClass: 'peat-devices-popover',
                html: true,
                sanitize: false,
                trigger: 'click'
            });

            if (popoverTriggerEl.dataset.peatDevicePopoverReady === 'true') {
                return;
            }
            popoverTriggerEl.dataset.peatDevicePopoverReady = 'true';
            popoverTriggerEl.addEventListener('shown.bs.popover', function () {
                document.querySelectorAll('.peat-devices-popover-toggle').forEach(otherTriggerEl => {
                    if (otherTriggerEl !== popoverTriggerEl) {
                        const otherPopover = bootstrap.Popover.getInstance(otherTriggerEl);
                        if (otherPopover) {
                            otherPopover.hide();
                        }
                    }
                });
            });
        });
    },

    peatRunDelete: function (url, checkboxName = "run_ids", deleteButtonSelector = "#delete-button") {
        const checkboxes = $(`input[name="${checkboxName}"]:checked`);
        const delete_ids = Array.from(checkboxes).map(checkbox => checkbox.value)
        fetch(url, {
            method: 'DELETE',
            headers: peat.csrfHeaders(),
            body: JSON.stringify({ ids: delete_ids })
        })
            .then(response => {
            if (response.status !== 204) {
                throw new Error('Network response was not ok');
            }
            })
            .then(data => {
            refreshTable()
            $(deleteButtonSelector).prop('disabled', true);
            })
            .catch(error => {
            console.error('There was a problem with the fetch operation:', error.message);
            });
    },

    peatConfigDelete: function (url) {
        const checkboxes = document.querySelectorAll('input[name="config_ids"]:checked');
        const delete_ids = Array.from(checkboxes).map(checkbox => checkbox.value)
        $('#delete-button').prop('disabled', true);
        fetch(url, {
            method: 'DELETE',
            headers: peat.csrfHeaders(),
            body: JSON.stringify({ ids: delete_ids })
        })
            .then(response => {
            if (response.status !== 204) {
                throw new Error('Network response was not ok');
            }
            })
            .then(data => {
            location.reload();
            })
            .catch(error => {
            console.error('There was a problem with the fetch operation:', error);
            });
    },

    smoothScrollToBottom: function (container = logContainer) {
        const targetScrollTop = container.scrollHeight;
        const startScrollTop = container.scrollTop;
        const distance = targetScrollTop - startScrollTop;
        const duration = 300;
        let startTime = null;

        function animation(currentTime) {
            if (startTime === null) startTime = currentTime;
            const timeElapsed = currentTime - startTime;
            const progress = Math.min(timeElapsed / duration, 1); // Normalize progress to [0, 1]
            const ease = progress * (2 - progress); // Ease-out curve
            container.scrollTop = startScrollTop + distance * ease;

            if (progress < 1) {
            requestAnimationFrame(animation);
            }
        }

        requestAnimationFrame(animation);
    },

    peatLogSocket: function (runDir, runMethod) {
        if (logContainer.peatLogSocket && logContainer.peatLogSocket.readyState <= WebSocket.OPEN) {
            logContainer.peatLogSocket.close();
        }

        const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
        const socket = new WebSocket(protocol + window.location.host + '/peat/results/log/');
        logContainer.peatLogSocket = socket;

        logContainer.setAttribute('run_dir', runDir);
        logContainer.setAttribute('run_method', runMethod);

        socket.onopen = function (event) {
            const request = {
            run_dir: runDir,
            run_method: runMethod,
            };
            socket.send(JSON.stringify(request));
        };

        socket.onmessage = function (event) {
            const data = JSON.parse(event.data);

            if (data.type === 'existing_log') {
            logContent.textContent += data.content;
            peat.smoothScrollToBottom();
            } else if (data.type === 'new_lines') {
            // +5 tolerance so a near-bottom scroll position still counts as "at bottom"
            const isAtBottom = logContainer.scrollHeight - logContainer.clientHeight <= logContainer.scrollTop + 5;

            logContent.textContent += data.content;

            if (isAtBottom) {
                peat.smoothScrollToBottom();
            }
            } else if (data.type === 'status') {
            if (data.message) {
                logContent.textContent += '\n' + data.message + '\n';
                peat.smoothScrollToBottom();
            }
            } else if (data.type === 'error') {
            if (data.message) {
                logContent.textContent += '\n' + data.message + '\n';
                peat.smoothScrollToBottom();
            }
            console.error(data.message);
            }
        };

        socket.onclose = function (event) {
            if (logContainer.peatLogSocket === socket) {
                logContainer.peatLogSocket = null;
                if (logContainer.getAttribute('run_dir') === runDir) {
                    logContainer.setAttribute('run_dir', 'none');
                    logContainer.removeAttribute('run_method');
                }
            }
            console.error('WebSocket closed:', event);
        };
    },

    createRunLink: function (url, run_dir, baseline) {
        var result = "";
        if (baseline) {
            result += `<i class="bi-star-fill me-2" title="baseline" style="color: gold;"></i>`;
        };
        if (run_dir) {
            result += `<a class="link-body-emphasis" href="${url}">${run_dir}</a>`;
        } else {
            result += "No data available"
        }
        return result
    },

    handleButtonClick: function (status, id, folder_name, pull_or_scan) {
        let button = $(`#button_${pull_or_scan}_${id}`)
        if (status === 'running' || status === 'started' || status === 'waiting') {
            let url = '/peat/run/stop/'
            button.prop('disabled', true);
            fetch(url, {
            method: 'POST',
            headers: peat.csrfHeaders(),
            body: JSON.stringify({
                "pull_or_scan": pull_or_scan,
                "pk": id
            }),
            })
            .then(response => {
                if (response.status !== 200) {
                throw new Error('Network response was not ok');
                }
                refreshTable();
                button.prop('disabled', false);
            })
            .catch(error => {
                console.error('There was a problem with the fetch operation:', error.message);
            });
        }
        else if (folder_name) {
            // Error and stopped runs can still have useful files, so download stays available.
            let url = '/peat/run/download/'
            button.prop('disabled', true);
            let nativeButton = button.get(0)
            let icon = nativeButton.querySelector('i'); 
            icon.classList.remove('bi-download')
            icon.classList.remove('bi-exclamation-circle')
            icon.classList.add('bi-hourglass-split')
            fetch(url, {
            method: 'POST',
            headers: peat.csrfHeaders(),
            body: JSON.stringify({
                "pull_or_scan": pull_or_scan,
                "pk": id
            }),
            })
            .then(response => {
                if (response.status === 404) {
                throw new Error('Run files are not available.');
                }
                if (response.status !== 200) {
                throw new Error('Network response was not ok');
                }
                return response.blob()
            })
            .then(blob => {
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = folder_name;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
            })
            .catch(error => {
                console.error('There was a problem with the fetch operation:', error.message);
                toastError(error.message || 'Unable to download this PEAT run.', 5000);
            })
            .finally(() => {
                icon.classList.remove('bi-hourglass-split')
                icon.classList.add('bi-download')
                button.prop('disabled', false);
                refreshTable();
            });
        }
        else {
            toastError('Run files are not available yet.', 5000);
        }
    },

    runDetailsButton: function (url, pull_or_scan) {
        const runLabel = pull_or_scan === "scan" ? "scan" : "pull";
        const tooltip = `Open the full PEAT ${runLabel} telemetry page with summary details and log output.`;
        return `<a class="btn btn-secondary" href="${url}" data-bs-toggle="tooltip" data-bs-placement="top" data-bs-custom-class="peat-tooltip" title="${tooltip}" aria-label="View ${runLabel} run details">
                    <i class="bi bi-eye"></i>
                </a>`;
    },

    downloadButton: function (status, id, folder_name, pull_or_scan) {
        let buttonClass = "btn";
        let buttonIcon = "";
        let tooltip = "";

        if (status === "running" || status === "started" || status === "waiting") {
            buttonClass += " btn-danger";
            buttonIcon += '<i class="bi bi-stop"></i>';
            tooltip = status === "waiting"
                ? `Cancel this waiting PEAT ${pull_or_scan} before it starts.`
                : `Stop this PEAT ${pull_or_scan}. Download becomes available once output files exist.`;
        } else if (folder_name) {
            buttonClass += " btn-primary";
            buttonIcon += '<i class="bi bi-download"></i>';
            tooltip = `Download the PEAT ${pull_or_scan} run files as a ZIP archive.`;
        }
        else {
            buttonClass += " btn-warning";
            buttonIcon += '<i class="bi bi-exclamation-circle"></i>';
            tooltip = "Run files are not available yet, so there is nothing to download.";
        }
        const safeFolderName = String(folder_name || '').replace(/'/g, "&#39;");
        const disabledAttr = !folder_name && status !== "running" && status !== "started" && status !== "waiting" ? " disabled" : "";
        let button = `<span class="d-inline-block" data-bs-toggle="tooltip" data-bs-placement="top" data-bs-custom-class="peat-tooltip" title="${tooltip}">
                        <button type="button" class="${buttonClass}" id="button_${pull_or_scan}_${id}" onclick="peat.handleButtonClick('${status}', ${id}, '${safeFolderName}', '${pull_or_scan}')"${disabledAttr}>
                            ${buttonIcon}
                        </button>
                      </span>`;
        return button;
    }
};
