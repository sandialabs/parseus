import pandas as pd

from parseus.datastore.query_api import get_modbus_function_codes
from parseus.preprocessors import LOGGER
from parseus.preprocessors.function_code import (
    fc_transformer,
    get_function_codes_data,
    get_summary_from_function_codes,
)
from parseus.preprocessors.transform import one_to_many
from parseus.util.datetime_utils import datetime_parser


def get_function_codes_state(
    index="arkime_session*",
    start=None,
    end=None,
    calendar_interval="1d",
    ds_client=None,
):
    """
    Gets the modbus aggregation iterator, unrolls it and returns a dataframe
    """
    fc = get_modbus_function_codes(
        ds_client,
        index=index,
        start=start,
        end=end,
        ip_filter="",
        logger=LOGGER,
        calendar_interval=calendar_interval,
    )
    transformed = one_to_many(fc, transformer=fc_transformer)
    data = list(transformed)
    df = pd.DataFrame(data)
    df["@timestamp"] = df["@timestamp"].apply(lambda x: datetime_parser(x))
    df.set_index("@timestamp", inplace=True)
    df.sort_index(inplace=True)
    return df


def get_fc_response_data(fc_state):
    """
    Gets summary information of the function codes and returns a dictionary response
    back to client
    """
    data = {
        "fc_summary": get_summary_from_function_codes(fc_state),
        "conversation_list": get_function_codes_data(fc_state),
    }
    return data
