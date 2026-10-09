"""tests/test_umap_params.py - the 2-D and 3-D layouts share one parameter set (D-29)."""
from src import config, projection, projection_3d


def test_both_layouts_read_the_config_parameters():
    """D-29: each module held its own copy, free to drift apart silently."""
    assert projection.FINAL_PARAMS is config.UMAP_PARAMS
    assert projection_3d.FINAL_PARAMS is config.UMAP_PARAMS


def test_both_layouts_use_the_config_seed():
    assert projection.SEED == projection_3d.SEED == config.RANDOM_SEED


def test_values_unchanged():
    """The refactor moved the values; it must not have changed them."""
    assert config.UMAP_PARAMS == {"n_neighbors": 15, "min_dist": 0.1}
    assert config.RANDOM_SEED == 42
