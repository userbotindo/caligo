from typing import TypeVar, Union

from pymongo.operations import DeleteOne, InsertOne, ReplaceOne
from pymongo.read_preferences import (
    Nearest,
    Primary,
    PrimaryPreferred,
    Secondary,
    SecondaryPreferred,
)

ReadPreferences = Union[
    Primary, PrimaryPreferred, Secondary, SecondaryPreferred, Nearest
]
Request = Union[DeleteOne, InsertOne, ReplaceOne]
Results = TypeVar("Results")
