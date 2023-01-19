from typing import TypeVar, Union

from pymongo.operations import (
    DeleteMany,
    DeleteOne,
    InsertOne,
    ReplaceOne,
    UpdateMany,
    UpdateOne,
)
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
Request = TypeVar(
    "Request", DeleteMany, DeleteOne, InsertOne, ReplaceOne, UpdateMany, UpdateOne
)
Results = TypeVar("Results")
