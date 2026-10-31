import logging
from io import StringIO

import pandas as pd
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.template import loader

from parseus.interfaces.ot_data import get_fc_response_data, get_function_codes_state
from parseus.preprocessors.reg_updates import map_shortname_to_canonical
from parseus.webapp.project.views import _get_database_client

from . import utility

logger = logging.getLogger("archi")


def get_ot_network(request):
    template = loader.get_template("registers/register_base.html")
    return HttpResponse(template.render(request=request))


def registers(request):
    template = loader.get_template("registers/register_analysis.html")
    return HttpResponse(template.render(request=request))


def registers_query(request):
    """
    Get register operations data from the given elastic instance. Optionally allow
    start and end time filters.

    :param request: Django Request
    :return: Django Response
    """
    # TODO: Convert this to a task so the web server can still run while data is fetched
    # and processed.
    try:
        # Get register state data
        reg_state = utility.get_reg_state(
            index=request.GET.get("index"),
            start=request.GET.get("start"),
            end=request.GET.get("end"),
            dshost=_get_database_client(request),
        )

        # Cache reg state data on the user's session
        request.session["reg_state"] = reg_state.to_json()

        # create name mapping
        short_to_con = map_shortname_to_canonical(reg_state)
        shortconlist = [
            [a, b] for a, b in zip(short_to_con.keys(), short_to_con.values())
        ]
        shortconlist.insert(0, ["Short Name", "Long Name"])

        # Create JSON structure to send back to client
        data = {
            "summary": utility.get_summary_from_reg_state(reg_state),
            "counts": utility.get_counts_from_reg_state(reg_state),
            "conversations": utility.get_conversations_from_reg_state(
                reg_state, include_points=True
            ),
            "name_map_array": shortconlist,
        }
        return JsonResponse(data)
    except Exception as e:
        logger.error(e)
        return HttpResponseBadRequest("Error loading register summary data.")


def state(request):
    template = loader.get_template("registers/state.html")
    return HttpResponse(template.render(request=request))


def state_data(request):
    """
    Get clustered register state over time from the given elastic instance. Optionally
    allow start and end time filters.

    :param request: Django Request
    :return: Django Response
    """
    # TODO: Convert this to a task so the web server can still run while data is fetched
    # and processed.
    try:
        # Get register state data
        reg_state = pd.read_json(StringIO(request.session["reg_state"]))
        # Filter reg_state to selected registers
        register_filter = request.GET.getlist("registers[]")
        logger.debug(
            f"state_data: filtering reg_state by these registers: {register_filter}"
        )
        filtered_reg_state = reg_state[register_filter]
        logger.debug(f"state_data: filtered reg_state\n{filtered_reg_state}")

        graph = request.GET.get("graph", "")
        if graph == "Register State Over Time":
            data = {"states": utility.get_clustered_states_dict(filtered_reg_state)}
        elif graph == "Register Updates Heatmap":
            data = {
                "heatmap": utility.get_reg_updates_heatmap_dict(
                    filtered_reg_state, reg_state
                )
            }
        elif graph == "State Transition Graph":
            data = {
                "node_edge": utility.get_node_edge_dict(filtered_reg_state, "state_id")
            }
        else:
            logger.error("Unknown graph type: %s", graph)
            data = {}

        return JsonResponse(data)
    except Exception as e:
        logger.error(e)
        return HttpResponseBadRequest(e)


def function_codes_query(request):
    """
    Get elastic data and format it into function codes. Optionally allow start and end dates.
    start and end time filters.

    :param request: Django Request
    :return: Django Response
    """

    try:
        # get function codes data frame
        fc_state = get_function_codes_state(
            index=request.GET.get("index"),
            start=request.GET.get("start"),
            end=request.GET.get("end"),
            calendar_interval=request.GET.get("groupby", "1d"),
            ds_client=_get_database_client(request),
        )

        # Create JSON structure to send back to client
        data = get_fc_response_data(fc_state)
        return JsonResponse(data)
    except Exception as e:
        logger.error(e)
        return HttpResponseBadRequest("Error loading function code data.")
