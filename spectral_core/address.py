"""Exact endpoint identifiers for the first Spectral Core emulator."""
from dataclasses import dataclass

@dataclass(frozen=True, order=True)
class SpectralAddress:
    """Opaque exact ID; decimal symbols are neutral labels for ten base clusters."""
    value: str

    def __post_init__(self):
        if not self.value:
            raise ValueError("A spectral address cannot be empty")
        if any(symbol not in "0123456789" for symbol in self.value):
            raise ValueError("Spectral addresses must contain only symbols 0–9")

    @property
    def tail_first(self):
        """Address symbols in the user's tail-first processing order."""
        return self.value[::-1]

    def __str__(self):
        return self.value
