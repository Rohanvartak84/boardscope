"""Side-effect-free polymorphic executor factory."""
from .executor import BoardExecutor


def create_executor(board) -> BoardExecutor:
    from .adapters import SSHBoard, Simulator
    from .uart import UARTBoard
    from .fallback import FallbackBoard
    implementations={'ssh':SSHBoard,'uart':UARTBoard,'simulator':Simulator,'auto':FallbackBoard}
    try:implementation=implementations[board['mode']]
    except (KeyError, TypeError):raise ValueError('Unsupported board transport') from None
    return implementation(board)
