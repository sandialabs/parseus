"""Analytic that detects unusual numbers of ports queried against a device."""

from functools import partial

import pandas as pd

from parseus.analytics.base import (
    Analytic,
    OutsideStdDevModel,
    replace_with_thresholds_iqr,
)
from parseus.analytics.capabilities import (
    ElasticsearchSource,
    IndexQuery,
    JoblibArtifact,
    Supervised,
)
from parseus.analytics.core import (
    SuppressionWindow,
    build_ecs_alert,
    window_now,
)
from parseus.analytics.filters import private_ip_filter
from parseus.analytics.network_anomalies._recon_common import build_interval_counter
from parseus.analytics.queries import CONN_DATASET_QUERY, histogram_cardinality_agg
from parseus.analytics.registry import register_analytic


def _portscan_agg(calendar_interval: str = "minute") -> dict:
    """Composite agg: destination IPs bucketed by time -> distinct dest ports."""
    return histogram_cardinality_agg(
        term_field="destination.ip",
        term_label="dest_ips",
        metric_field="destination.port",
        metric_label="destination_ports",
        calendar_interval=calendar_interval,
    )


@register_analytic(
    key="PortScanTargetAnalytic",
    family="network_anomalies",
    replace=True,
    data_source=ElasticsearchSource(
        fit=IndexQuery(
            query=CONN_DATASET_QUERY,
            composite_agg=_portscan_agg()
        ),
        run=IndexQuery(
            query=CONN_DATASET_QUERY,
            composite_agg=_portscan_agg(),
        ),
    ),
    training=Supervised(),
    persistence=JoblibArtifact(),
    init_args={"calendar_interval": "minute"},
    fit_idx={
        "index_name": "arkime_sessions3-*",
        "filter": private_ip_filter("source.ip"),
    },
    run_idx={
        "index_name": "arkime_sessions3-*",
        "filter": private_ip_filter("source.ip"),
    },
    out_idx={"index_name": "parseus-portscan-victim-out"},
)
class PortScanTargetAnalytic(Analytic):
    """
    Name: PortScanTargetAnalytic
    How: Reports when a destination device is having an unusual number of its ports queried.

    When: Looking for network or service enumeration on the network

    Usage: Not Listed

    Mitre-Data-Sources:
        + Network Traffic: Network Traffic Content

    Mitre-Techniques:
        + Automated Collection (T0802)
        + Network Service Scanning (T0841)
        + collection (TA0100)
        + discovery (TA0102)

    Purdue-Levels:
        + level-1
        + level-2
        + level-3
        + level-4
        + level-5

    Tags:
        + scanning
        + exfiltration
        + lateral-movement
    """

    def __init__(self, pull_duration=90, calendar_interval="minute", **kwargs):
        """
        Sets up the analytic to receive packets, and store the
        source and destination IPs from those packets.
        """
        super().__init__(pull_duration=pull_duration, **kwargs)

        build_portscan_counter = partial(
            build_interval_counter, outer_agg="dest_ips", inner_agg="destination_ports"
        )
        self._transform = build_portscan_counter
        self.portscan_counter_ = pd.DataFrame()
        self.logic_ = OutsideStdDevModel()
        self.calendar_interval = calendar_interval
        self.predict_results_doc = """
        Shows any devices in a given hour/day where tcp port connections fall
        outside the trained mean/stdev of the given device.
        """
        self.fit_results_doc = """
        Shows a dataframe of unique port counts hourly/daily
        of every device that receives a tcp connection.
        At this point, Data is not exact as Outliers have already
        been modified to to flatten the skew.
        """

    def data_source(self) -> ElasticsearchSource:
        """Build the ES source spec from the configured aggregation interval."""
        agg = _portscan_agg(self.calendar_interval)
        return ElasticsearchSource(
            fit=IndexQuery(query=CONN_DATASET_QUERY, composite_agg=agg),
            run=IndexQuery(query=CONN_DATASET_QUERY, composite_agg=agg),
        )

    def _fit(self, *regops_datasets):
        """
        Fits the analytic by storing IPs from conversations we have seen
        """

        self.portscan_counter_ = pd.concat(regops_datasets)
        self.portscan_counter_.fillna(0, inplace=True)
        # Replaced outliers skewing dataframe with IQR thresholds
        replace_with_thresholds_iqr(
            self.portscan_counter_, self.portscan_counter_.columns
        )
        self.logic_.fit_table(self.portscan_counter_)

    def _run(self, start, end, transformed_documents, state, **other_docs):
        """
        return:
         Alerts for abnormal number of port connections a device receives in
         a given time window
        """
        alerts = []
        suppression = SuppressionWindow(state, self.suppression_)
        now = window_now(end)

        predict_df = transformed_documents
        predict_df.fillna(0, inplace=True)

        _, results = self.logic_.run_table(None, predict_df, buffer=2)

        for ip in results:
            if ip not in self.logic_.stats_df.index:
                self._log.warning("Skipping %s because it was not present in fit stats", ip)
                continue

            ip_alert = results[results[ip].notnull()][ip].to_dict()
            mean = self.logic_.stats_df.loc[ip, "mean"]
            std = self.logic_.stats_df.loc[ip, "std"]

            for time, count in ip_alert.items():
                if not suppression.should_emit(
                "excess_ports_queried",
                ip,
                now=now,
                ):
                    continue

                alert = build_ecs_alert(
                    "excess ports queried alert",
                    (
                        f"Excess Ports Queried Alert: {ip} "
                        + f"usually gets requests to  {round(mean)} "
                        + f"+/- {round(std)} different ports, but at {time} "
                        + f"it got requests to {int(count)} ports."
                    ),
                    1.0,
                    category=["network"],
                    timestamp=time,
                    event_extra={"timestamp": end},
                    destination={"ip": ip},
                )
                alerts.append(alert)
        return alerts

    def get_fit_results(self):
        return self.portscan_counter_
