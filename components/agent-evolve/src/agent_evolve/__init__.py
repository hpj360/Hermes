"""agent-evolve: GEPA-style agent-definition self-evolution with statistical rigor.

Generate variants, evaluate on real runs, promote only statistically
significant winners (Welch t-test + Bonferroni). Zero dependencies.
"""

from .evolve import (
    EvaluateFn,
    Experiment,
    GEPAExperiment,
    LlmJsonClient,
    Variant,
    VariantResult,
    auto_generate_variants,
    get_latest_promotion,
    list_experiments,
    load_experiment,
    registry_dir,
    run_cycle,
    run_gepa_cycle,
    run_gepa_split_run,
    run_split_run,
    save_experiment,
    score_variant,
)
from .redteam import (
    DEFAULT_DENYLIST,
    REDTEAM_PATHS,
    audit_denylist_coverage,
    matches_denylist,
)
from .stats import (
    SplitRunResult,
    compare_variants,
    mean,
    should_promote,
    stddev,
    welch_ttest,
)

__all__ = [
    "DEFAULT_DENYLIST",
    "REDTEAM_PATHS",
    "EvaluateFn",
    "Experiment",
    "GEPAExperiment",
    "LlmJsonClient",
    "SplitRunResult",
    "Variant",
    "VariantResult",
    "audit_denylist_coverage",
    "auto_generate_variants",
    "compare_variants",
    "get_latest_promotion",
    "list_experiments",
    "load_experiment",
    "matches_denylist",
    "mean",
    "registry_dir",
    "run_cycle",
    "run_gepa_cycle",
    "run_gepa_split_run",
    "run_split_run",
    "save_experiment",
    "score_variant",
    "should_promote",
    "stddev",
    "welch_ttest",
]

__version__ = "0.1.0"
