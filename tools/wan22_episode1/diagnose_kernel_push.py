"""Print Kaggle's non-secret HTTP error body for a rejected kernel save."""

from pathlib import Path

from kaggle.api.kaggle_api_extended import KaggleApi
from requests import HTTPError


api = KaggleApi(enable_oauth=True)
api.authenticate()
try:
    response = api.kernels_push(str(Path(__file__).resolve().parent))
    print(f"SUCCESS: {response}")
except HTTPError as exc:
    response = exc.response
    print(f"HTTP_STATUS={response.status_code}")
    print(response.text[:8000])
    raise
