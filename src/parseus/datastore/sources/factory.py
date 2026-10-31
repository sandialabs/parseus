from typing import Callable, Optional

from parseus.analytics.capabilities import (
    DataSource,
    ElasticsearchSource,
    PeatFileSource,
)
from parseus.datastore.query_api import get_datastore_data, get_peat_data

from .base import AnalyticDataSource, DataSourceConfigurationError
from .elasticsearch import ElasticsearchIndexDataSource
from .peat_file import PeatFileDataSource


SourceBuilder = Callable[..., AnalyticDataSource]


def _build_elasticsearch_source(
    ds_client,
    analytic_config,
    *,
    get_timerange,
    data_source: ElasticsearchSource,
) -> AnalyticDataSource:
    return ElasticsearchIndexDataSource(
        ds_client,
        analytic_config,
        get_datastore_data=get_datastore_data,
        get_timerange=get_timerange,
        source=data_source,
    )


def _build_peat_file_source(
    ds_client,
    analytic_config,
    *,
    get_timerange,  # noqa: ARG001
    data_source: PeatFileSource,  # noqa: ARG001
) -> AnalyticDataSource:
    return PeatFileDataSource(
        analytic_config,
        get_peat_data=get_peat_data,
    )


_SOURCE_BUILDERS: dict[type[DataSource], SourceBuilder] = {
    ElasticsearchSource: _build_elasticsearch_source,
    PeatFileSource: _build_peat_file_source,
}


def build_data_source(
    ds_client,
    analytic_config,
    *,
    get_timerange,
    data_source: Optional[DataSource] = None,
) -> AnalyticDataSource:
    """Build the runtime data source for a declared analytic source."""

    if data_source is None:
        raise DataSourceConfigurationError(
            "Analytic has no declared data source."
        )

    for source_cls, builder in _SOURCE_BUILDERS.items():
        if isinstance(data_source, source_cls):
            return builder(
                ds_client,
                analytic_config,
                get_timerange=get_timerange,
                data_source=data_source,
            )

    raise DataSourceConfigurationError(
        f"Unknown analytic data source type: {type(data_source).__name__}"
    )
