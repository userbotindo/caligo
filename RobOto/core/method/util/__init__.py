from .restart import Restart
from .shutdown import Terminate


class Util(Restart, Terminate):
    pass
