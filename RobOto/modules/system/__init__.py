from .ping import Ping
from .shutdown import Shutdown


class System(Ping, Shutdown):
    pass
