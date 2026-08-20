"""Read the authoritative status of the private Episode 1 Kaggle kernel."""

from kaggle.api.kaggle_api_extended import KaggleApi


api = KaggleApi(enable_oauth=True)
api.authenticate()
print(api.kernels_status("kaapav/echo-100-episode-1-wan-2-2"))
