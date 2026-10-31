"""Elasticsearch/OpenSearch analytic data source."""

from __future__ import annotations

from datetime import timedelta
from typing import Callable, Iterable, Optional

from parseus.analytics.capabilities import ElasticsearchSource, IndexQuery

from .base import AnalyticDataSource, DataSourceConfigurationError, RunWindow

_MATCH_ALL = {"match_all": {}}


class ElasticsearchIndexDataSource(AnalyticDataSource):
    """Data source for analytics backed by Elasticsearch/OpenSearch indices."""

    def __init__(
        self,
        ds_client,
        analytic_config,
        *,
        get_datastore_data: Callable,
        get_timerange: Callable,
        source: Optional[ElasticsearchSource] = None,
    ) -> None:
        self.ds_client = ds_client
        self.config = analytic_config
        self._get_datastore_data = get_datastore_data
        self._get_timerange = get_timerange
        self._source = source
        if ds_client is None:
            raise DataSourceConfigurationError(
                "ElasticsearchIndex requires a datastore client."
            )

    def _config_value(self, name: str, default=None):
        """Return an optional config value with a default for test/user configs."""
        return getattr(self.config, name, default)

    def _index_query(self, phase: str) -> IndexQuery:
        """Return the declared IndexQuery for a phase, or an empty default."""
        query = getattr(self._source, phase, None) if self._source else None
        return query if isinstance(query, IndexQuery) else IndexQuery()

    def get_fit_data(self, analytic):
        """Return datastore data for fitting an analytic."""
        index = self._config_value("fit_idx")
        if not index:
            raise DataSourceConfigurationError(
                "ElasticsearchIndex fit data requires fit_idx."
            )

        fit_start = self._config_value("fit_start")
        fit_end = self._config_value("fit_end")

        if isinstance(fit_start, str) and not fit_start.strip():
            fit_start = None
        if isinstance(fit_end, str) and not fit_end.strip():
            fit_end = None

        start, end = self._get_timerange(
            ds_client=self.ds_client,
            index_name=index,
            start=fit_start,
            end=fit_end,
        )

        spec = self._index_query("fit")
        return self._get_datastore_data(
            ds_client=self.ds_client,
            index=index,
            start=start,
            end=end,
            ip_filter=self._config_value("ip_filter", ""),
            query=spec.query or _MATCH_ALL,
            aggs=spec.aggs,
            composite_aggs=spec.composite_agg,
            return_fields=spec.return_fields,
        )

    def iter_run_windows(self, analytic) -> Iterable[RunWindow]:  # noqa: ARG002
        """Yield the configured run range, split by schedule if requested."""
        index = self._config_value("run_idx")
        if not index:
            raise DataSourceConfigurationError(
                "ElasticsearchIndex run data requires run_idx."
            )
        start, end = self._get_timerange(
            ds_client=self.ds_client,
            index_name=index,
            start=self._config_value("run_start"),
            end=self._config_value("run_end"),
        )
        while start < end:
            schedule = self._config_value("schedule", 0)
            if schedule:
                window_end = min(start + timedelta(seconds=schedule), end)
            else:
                window_end = end
            yield RunWindow(start=start, end=window_end)
            start = window_end

    def get_run_data(self, analytic, window: RunWindow):
        """Return datastore data for an analytic run window."""
        index = self._config_value("run_idx")
        if not index:
            raise DataSourceConfigurationError(
                "ElasticsearchIndex run data requires run_idx."
            )
        spec = self._index_query("run")
        return self._get_datastore_data(
            ds_client=self.ds_client,
            index=index,
            start=window.start,
            end=window.end,
            ip_filter=self._config_value("ip_filter", ""),
            query=spec.query or _MATCH_ALL,
            aggs=spec.aggs,
            composite_aggs=spec.composite_agg,
            return_fields=spec.return_fields,
        )

