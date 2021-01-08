import logging

from . import launch, logging as logs


log = logging.getLogger("launch")
logs.setup_log()


def main():
    launch.main()


if __name__ == "__main__":
    main()
