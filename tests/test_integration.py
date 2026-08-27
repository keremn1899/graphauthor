"""Full-pipeline tests (require OPENROUTER_API_KEY)."""

from __future__ import annotations

import os
import time

import pytest
from dotenv import load_dotenv

load_dotenv()

pytestmark = pytest.mark.integration


