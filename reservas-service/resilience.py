import threading
import time
from enum import Enum


class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: int = 15
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self.failure_count = 0
        self.last_failure_time = 0.0
        self.state = CircuitState.CLOSED
        self.lock = threading.Lock()

    def can_execute(self) -> bool:
        with self.lock:
            if self.state == CircuitState.CLOSED:
                return True

            if self.state == CircuitState.OPEN:
                elapsed = time.time() - self.last_failure_time

                if elapsed >= self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    return True

                return False

            # HALF_OPEN: permite una solicitud de prueba.
            return True

    def register_success(self) -> None:
        with self.lock:
            self.failure_count = 0
            self.state = CircuitState.CLOSED

    def register_failure(self) -> None:
        with self.lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN

    def get_state(self) -> str:
        with self.lock:
            return self.state.value