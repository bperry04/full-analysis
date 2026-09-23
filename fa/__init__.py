"""Full Analysis — free-data stock/company analyzer with traceable horizon scores."""

import pandas as _pd

# pandas 3 stores strings in Arrow arrays by default; row-wise work on them (XBRL resolution, chain normalisation) is
# 10-50x slower than numpy object arrays. Python storage keeps semantics identical and the pipeline fast.
try:
    _pd.set_option("mode.string_storage", "python")
except Exception:  # pragma: no cover
    pass

__version__ = "0.1.0"
