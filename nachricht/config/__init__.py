import collections.abc


def _deep_update_dict(d, u):
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = _deep_update_dict(d.get(k, {}), v)
        else:
            d[k] = v
    return d


def combine(base, overlay):
    """
    Update the base object with values from the overlay object.
    """
    for key in dir(overlay):
        if callable(getattr(overlay, key)) or key.startswith("__"):
            continue

        if hasattr(base, key):
            new_value = getattr(overlay, key)
            current_value = getattr(base, key)

            if isinstance(current_value, dict) and isinstance(new_value, dict):
                merged_dict = current_value.copy()
                _deep_update_dict(merged_dict, new_value)
                setattr(base, key, merged_dict)
            else:
                setattr(base, key, new_value)
