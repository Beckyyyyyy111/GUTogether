"""
Annotation data model for audio annotations.
Handles annotation structure, validation, and serialization.
"""

from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class Annotation:
    """
    Represents a single audio annotation with timing, metadata, and visual properties.
    """
    name: str                           # Unique name for the annotation
    start: float                        # Start time in seconds
    stop: float                         # Stop time in seconds
    comment: str = ""                   # Optional comment/description
    color: str = "#FF6B6B"              # Hex color for visualization
    channel: str = "mono"               # Channel: "mono", "left", "right", or "both"
    exported_filename: Optional[str] = None  # Filename if exported
    exported_path: Optional[str] = None      # Full path of exported file
    created_timestamp: str = ""         # ISO timestamp of creation
    modified_timestamp: str = ""        # ISO timestamp of last modification

    @classmethod
    def from_dict(cls, data: dict) -> "Annotation":
        """Create Annotation from dictionary (for JSON deserialization)."""
        # Handle legacy data without new fields
        return cls(
            name=data.get("name", ""),
            start=float(data.get("start", 0.0)),
            stop=float(data.get("stop", 0.0)),
            comment=data.get("comment", ""),
            color=data.get("color", "#FF6B6B"),
            channel=data.get("channel", "mono"),
            exported_filename=data.get("exported_filename"),
            exported_path=data.get("exported_path"),
            created_timestamp=data.get("created_timestamp", ""),
            modified_timestamp=data.get("modified_timestamp", ""),
        )

    def to_dict(self) -> dict:
        """Convert Annotation to dictionary (for JSON serialization)."""
        return asdict(self)

    def validate(self) -> tuple[bool, str]:
        """
        Validate annotation data.
        Returns (is_valid, error_message).
        """
        if not self.name or not self.name.strip():
            return False, "Annotation name is required."
        
        if self.start >= self.stop:
            return False, "Start time must be less than stop time."
        
        if self.start < 0 or self.stop < 0:
            return False, "Times must be non-negative."
        
        valid_channels = {"mono", "left", "right", "both"}
        if self.channel not in valid_channels:
            return False, f"Invalid channel: {self.channel}"
        
        return True, ""

    def is_color_valid(self) -> bool:
        """Check if color is a valid hex color code."""
        if not self.color:
            return False
        
        color_str = self.color.lstrip("#")
        if len(color_str) not in (3, 6):
            return False
        
        try:
            int(color_str, 16)
            return True
        except ValueError:
            return False

    def get_duration(self) -> float:
        """Get annotation duration in seconds."""
        return self.stop - self.start

    def overlaps_with(self, other: "Annotation") -> bool:
        """Check if this annotation overlaps with another."""
        return not (self.stop <= other.start or self.start >= other.stop)
