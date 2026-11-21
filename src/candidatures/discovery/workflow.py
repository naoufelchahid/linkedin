"""Compatibilité : voir linkedin_discovery.workflow."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module('linkedin_discovery.workflow')
