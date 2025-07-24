import logging
import sys

def setup_logging():
    """
    Настраивает базовую конфигурацию логирования для всего приложения.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout
    )
    print("Логирование настроено.")

# Вызываем функцию настройки при импорте модуля, чтобы логирование
# было доступно сразу во всех частях приложения.
setup_logging() 