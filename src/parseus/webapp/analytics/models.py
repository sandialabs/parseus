"""Django-database models used by the Analytics app."""

from django.db import models


class AnalyticUserInput(models.Model):
    """Per-analytic deployment overrides for data retrieval.

    A single model for every data-source type. Universal fields (indices,
    ``init_args``, ``suppression``, ``run_state``) are real columns; any
    source-specific deployment config lives in ``source_config``, a JSON object
    keyed by the fields the analytic's declared data source advertises via
    ``DataSource.config_schema()``. Adding a new source type therefore needs no
    new model or migration — the source declares its config and maps it into the
    runtime cfg (``DataSource.apply_config``).
    """

    run_idx_name = models.CharField(max_length=300, blank=True)
    fit_idx_name = models.CharField(max_length=300, blank=True)
    out_idx_name = models.CharField(max_length=300, blank=True)
    init_args = models.JSONField(default=dict, null=True, blank=True)
    # Operator-set alert-suppression window (Prometheus-style duration, e.g.
    # "0s" = alert every run, "24h" = at most once/day per finding, "infinite").
    # Flows through get_analytic_cfg() into the analytic's suppression init arg.
    suppression = models.CharField(max_length=20, blank=True, default="0s")
    # Run-to-run state (suppression memory, dedup marks) for unsupervised
    # analytics, which have no TrainedModel row to persist onto. Supervised
    # analytics store their run state on TrainedModel.run_state instead.
    run_state = models.JSONField(default=dict, blank=True)
    # Source-specific deployment config, keyed by the analytic's data-source
    # config_schema() (e.g. ES: fit_idx_filter/run_idx_filter/schedule/
    # pull_duration). Empty for sources with no extra config.
    source_config = models.JSONField(default=dict, blank=True)

    @property
    def analytic_cfg(self):
        cfg = {}
        if self.analytic.requires_fit:
            cfg["fit_idx"] = {"index_name": self.fit_idx_name}
        cfg["run_idx"] = {"index_name": self.run_idx_name}
        cfg["out_idx"] = {"index_name": self.out_idx_name}
        cfg["init_args"] = self.init_args
        cfg["suppression"] = self.suppression or "0s"
        return cfg

    def get_analytic_cfg(self):
        """Return the runtime cfg: universal fields plus source-specific config.

        The declared data source maps its ``source_config`` into the cfg shape it
        expects (:meth:`DataSource.apply_config`), so this stays generic across
        source types.
        """
        cfg = self.analytic_cfg
        data_source = self._declared_data_source()
        if data_source is not None:
            data_source.apply_config(cfg, self.source_config or {})
        return cfg

    def _declared_data_source(self):
        """Return the analytic's declared DataSource capability, or None."""
        from parseus.analytics.registry import find_spec_for_class
        from parseus.analytics.spec import load_class

        try:
            analytic_cls = load_class(self.analytic.analytic_class)
        except Exception:
            return None
        spec = find_spec_for_class(analytic_cls)
        return spec.data_source if spec else None

    def __str__(self):
        return self.analytic.name


class Analytic(models.Model):
    """Database-tracked state for a registry-declared analytic."""

    analytic_class = models.CharField(max_length=200, unique=True)
    # Tombstone flag: set False by upload_analytic_config when the registry no
    # longer provides this analytic_class (e.g. a plugin was uninstalled). The
    # row (and any TrainedModel FK pointing at it) is never deleted by that
    # sync — only an explicit admin action should hard-delete an Analytic, and
    # only once it has no remaining TrainedModel rows. Re-appearing in the
    # registry flips this back to True.
    is_active = models.BooleanField(default=True)
    ui = models.OneToOneField(
        AnalyticUserInput, on_delete=models.CASCADE, related_name="analytic"
    )

    def __str__(self):
        return self.analytic_class

    # --- Display metadata, resolved from the registry spec -------------------
    #
    # None of these are DB columns. A retired analytic (is_active=False) may
    # have no matching spec once its code/plugin is gone; every property below
    # degrades to a safe default rather than raising, so admin/history views
    # showing a retired row do not break.

    @property
    def spec(self):
        """Return this analytic's registered :class:`AnalyticSpec`, or ``None``."""
        from parseus.analytics.registry import find_spec_for_class_path

        return find_spec_for_class_path(self.analytic_class)

    @property
    def name(self) -> str:
        """Registry key for this analytic.

        Deliberately the spec's ``key`` (not ``display_name``/``spec.name``):
        callers use this value to look the spec back up by key (e.g.
        ``get_analytic_config(analytic_name=analytic_obj.name)``), so it has to
        stay the exact lookup key, matching what this field held before it
        became a resolved property.
        """
        spec = self.spec
        return spec.key if spec else self.analytic_class

    @property
    def model(self) -> str:
        return self.analytic_class.split(".")[-1]

    @property
    def family(self) -> str:
        spec = self.spec
        return spec.family if spec else "uncategorized"

    @property
    def requires_fit(self) -> bool:
        spec = self.spec
        return spec.requires_fit if spec else True

    @property
    def location(self) -> str:
        spec = self.spec
        return spec.location if spec else ""

    @property
    def train_desc(self) -> str:
        spec = self.spec
        return spec.train_desc if spec else ""

    @property
    def predict_desc(self) -> str:
        spec = self.spec
        return spec.predict_desc if spec else ""

    @property
    def summary(self) -> str:
        spec = self.spec
        return spec.summary if spec else ""

    @property
    def detection_logic(self) -> str:
        spec = self.spec
        return spec.detection_logic if spec else ""

    @property
    def mitre_techniques(self) -> list:
        spec = self.spec
        return list(spec.mitre_techniques) if spec else []

    @property
    def purdue_levels(self) -> list:
        spec = self.spec
        return list(spec.purdue_levels) if spec else []

    @property
    def labels(self) -> list:
        spec = self.spec
        return list(spec.labels) if spec else []

    @property
    def maturity(self) -> str:
        spec = self.spec
        return spec.maturity if spec else "experimental"


class TrainedModel(models.Model):
    """A trained analytic artifact stored in the database.

    The learned state is an opaque binary joblib blob (``artifact``); the
    plaintext ``manifest`` (schema version, source class, Parseus version,
    creation time) is stored alongside it as JSON so it is inspectable in the
    admin without deserialising the state.

    ``run_state`` holds the analytic's *run-to-run* state (suppression memory,
    dedup marks) — plain JSON-serialisable data, evolving each run and stored
    separately from the immutable trained-model blob (the DB counterpart of the
    engine's separate ``{Analytic}_celery.state`` artifact).
    """

    name = models.CharField(max_length=200)
    family = models.CharField(max_length=200)
    instance_name = models.CharField(max_length=100, blank=True)
    artifact = models.BinaryField()
    manifest = models.JSONField(default=dict, blank=True)
    run_state = models.JSONField(default=dict, blank=True)
    analytic = models.ForeignKey(
        Analytic, on_delete=models.SET_NULL, null=True
    )  # FK to analytic used
    drawing_data = models.TextField(null=True, blank=True)
    analytic_class = models.CharField(
        max_length=200, null=True
    )  # needed in case of config overwrites

    def __str__(self):
        return f"{self.instance_name}"


class TrainedModelMetadata(models.Model):
    """Database entry to store metadata related to a trained model"""

    model = models.ForeignKey(
        TrainedModel, on_delete=models.CASCADE
    )  # FK to trained data
    name = models.CharField(max_length=100, blank=True)
    instance_name = models.CharField(max_length=100, blank=True)
    family = models.CharField(max_length=100, blank=True)
    supervised = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    es_host = models.CharField(max_length=100, blank=True)
    idx = models.CharField(max_length=150, blank=True)
    query = models.CharField(max_length=3000, blank=True, null=True)
    aggs = models.CharField(max_length=3000, blank=True, null=True)
    comp_aggs = models.CharField(max_length=3000, blank=True, null=True)
    return_fields = models.CharField(max_length=3000, blank=True, null=True)
    ip_filter = models.GenericIPAddressField(null=True)
    start_date = models.CharField(max_length=50, blank=True, null=True)
    end_date = models.CharField(max_length=50, blank=True, null=True)
    init_args = models.JSONField(default=dict, blank=True, null=True)
    fit_idx = models.JSONField(default=dict)
    run_idx = models.JSONField(default=dict)

    def __str__(self):
        return f"{self.instance_name}"
