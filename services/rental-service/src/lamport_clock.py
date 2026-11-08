"""
Módulo thread-safe de Relógio Lógico de Lamport (RF-02 / Issue #6).
Garante ordenação causal (happens-before) em nós e chamadas distribuídas.
"""

import threading
from typing import Optional


class LamportClock:
    """
    Implementação thread-safe do algoritmo de Relógio Lógico de Leslie Lamport (1978).
    
    Regras de atualização:
    1. Evento interno / emissão local: L = L + 1
    2. Recepção de mensagem com timestamp L_msg: L = max(L, L_msg) + 1
    """

    def __init__(self, initial_time: int = 0):
        self._time: int = initial_time
        self._lock: threading.Lock = threading.Lock()

    def get_time(self) -> int:
        """Retorna o tempo lógico atual sem avançar o contador."""
        with self._lock:
            return self._time

    def tick(self, incoming_time: Optional[int] = None) -> int:
        """
        Avança o relógio lógico de acordo com as regras de causalidade de Lamport.
        Retorna o novo timestamp lógico.
        """
        with self._lock:
            if incoming_time is not None:
                try:
                    inc = int(incoming_time)
                    if 0 <= inc <= 9007199254740991:
                        self._time = max(self._time, inc) + 1
                    else:
                        self._time += 1
                except (ValueError, TypeError):
                    self._time += 1
            else:
                self._time += 1
            return self._time

    def reset(self, initial_time: int = 0) -> None:
        """Reinicia o contador lógico (útil para suítes de testes automatizados)."""
        with self._lock:
            self._time = initial_time

    def __repr__(self) -> str:
        with self._lock:
            return f"LamportClock(time={self._time})"


# Instância singleton padrão por processo
clock = LamportClock()


def get_lamport_time() -> int:
    """Helper global para obter o carimbo lógico atual."""
    return clock.get_time()


def tick_lamport(incoming: Optional[int] = None) -> int:
    """Helper global compatível com a interface legada dos endpoints."""
    return clock.tick(incoming)
