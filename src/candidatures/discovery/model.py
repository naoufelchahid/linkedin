"""Compatibilité : voir linkedin_discovery.model."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module('linkedin_discovery.model')
