"""Shared Show/Hide choices for command responses."""
from enum import Enum


class Visibility(str, Enum):
    Show = 'show'
    Hide = 'hide'
