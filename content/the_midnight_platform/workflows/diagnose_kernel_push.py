from pathlib import Path

from kaggle.api.kaggle_api_extended import KaggleApi
from requests import HTTPError


kernel_dir = Path(__file__).resolve().parent
api = KaggleApi(enable_oauth=True)
api.authenticate()

try:
    result = api.kernels_push(str(kernel_dir))
    print(result)
except HTTPError as exc:
    response = exc.response
    print(f"HTTP {response.status_code}")
    print(response.text[:12000])
    raise
