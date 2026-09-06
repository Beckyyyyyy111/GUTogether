"""Template filter plugin.

Copy this file, rename it, and implement your custom filter logic.
"""

# import numpy as np
#
#
# class FilterUnit:
#     """Template class for custom filter units.
#
#     This placeholder class is intentionally commented out because
#     `template_filter.py` is excluded by `discover_filters()` and the class is
#     never instantiated in normal app execution.
#
#     Required methods:
#     - get_parameter_schema()
#     - apply()
#     """
#
#     name = "Template Filter"
#     description = "Example filter template for plugin development."
#
#     def get_parameter_schema(self):
#         """Return parameter definitions for UI generation."""
#         return [
#             {
#                 "key": "gain",
#                 "label": "Gain",
#                 "type": "float",
#                 "default": 1.0,
#                 "min": 0.0,
#                 "max": 2.0,
#                 "step": 0.1,
#             }
#         ]
#
#     def apply(self, audio, sr, channel_index, params, source_path, temp_dir):
#         """Apply filter to selected channel and return filtered channel.
#
#         Args:
#             audio: np.ndarray with shape (channels, samples)
#             sr: sample rate
#             channel_index: selected channel index
#             params: dict of user parameters
#             source_path: input file path (if available)
#             temp_dir: temporary directory path
#
#         Returns:
#             np.ndarray: filtered channel samples
#         """
#         gain = float(params.get("gain", 1.0))
#         channel = np.asarray(audio[channel_index], dtype=np.float32)
#         return np.clip(channel * gain, -1.0, 1.0)
